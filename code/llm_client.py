"""llm_client.py - Thin wrapper around Anthropic API with token/cost logging and caching."""

import os
import json
import hashlib
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from functools import lru_cache

try:
    import anthropic
except ImportError:
    anthropic = None

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent.parent / "cache" / "llm"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

USAGE_LOG_DIR = Path(__file__).parent.parent / "evaluation"
USAGE_LOG_DIR.mkdir(parents=True, exist_ok=True)
USAGE_LOG_FILE = USAGE_LOG_DIR / "usage_report.md"


@dataclass
class LLMUsage:
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    timestamp: str
    request_type: str
    cache_hit: bool = False


@dataclass
class LLMResponse:
    content: str
    usage: LLMUsage
    raw_response: Any = None


class LLMClient:
    """Anthropic API client with caching and usage tracking."""

    MODEL_PRICING = {
        "claude-3-haiku-20240307": {"input": 0.25 / 1_000_000, "output": 1.25 / 1_000_000},
        "claude-3-sonnet-20240229": {"input": 3.0 / 1_000_000, "output": 15.0 / 1_000_000},
        "claude-3-opus-20240229": {"input": 15.0 / 1_000_000, "output": 75.0 / 1_000_000},
        "claude-3-5-sonnet-20241022": {"input": 3.0 / 1_000_000, "output": 15.0 / 1_000_000},
        "claude-3-5-haiku-20241022": {"input": 0.8 / 1_000_000, "output": 4.0 / 1_000_000},
    }

    DEFAULT_MODEL = "claude-3-5-haiku-20241022"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        enable_cache: bool = True,
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.enable_cache = enable_cache
        self._client = None
        self._usage_log: List[LLMUsage] = []

        if self.api_key and anthropic:
            self._client = anthropic.Anthropic(api_key=self.api_key)

    @property
    def client(self):
        if self._client is None:
            if not self.api_key:
                raise ValueError("ANTHROPIC_API_KEY not set")
            if not anthropic:
                raise ImportError("anthropic package not installed")
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def _get_cache_key(self, messages: List[Dict], system: str = "") -> str:
        """Generate stable cache key from request content."""
        content = json.dumps({"messages": messages, "system": system, "model": self.model}, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def _get_cache_path(self, cache_key: str) -> Path:
        return CACHE_DIR / f"{cache_key}.json"

    def _load_cache(self, cache_key: str) -> Optional[LLMResponse]:
        if not self.enable_cache:
            return None
        cache_path = self._get_cache_path(cache_key)
        if cache_path.exists():
            try:
                with open(cache_path, "r") as f:
                    data = json.load(f)
                usage = LLMUsage(**data["usage"])
                usage.cache_hit = True
                return LLMResponse(content=data["content"], usage=usage, raw_response=data.get("raw_response"))
            except Exception as e:
                logger.warning(f"Cache read failed: {e}")
        return None

    def _save_cache(self, cache_key: str, response: LLMResponse):
        if not self.enable_cache:
            return
        cache_path = self._get_cache_path(cache_key)
        try:
            data = {
                "content": response.content,
                "usage": asdict(response.usage),
                "raw_response": response.raw_response,
            }
            with open(cache_path, "w") as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning(f"Cache write failed: {e}")

    def _calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        pricing = self.MODEL_PRICING.get(self.model, self.MODEL_PRICING[self.DEFAULT_MODEL])
        return input_tokens * pricing["input"] + output_tokens * pricing["output"]

    def _log_usage(self, usage: LLMUsage):
        self._usage_log.append(usage)
        self._write_usage_report()

    def _write_usage_report(self):
        try:
            total_input = sum(u.input_tokens for u in self._usage_log)
            total_output = sum(u.output_tokens for u in self._usage_log)
            total_cost = sum(u.cost_usd for u in self._usage_log)
            avg_input = total_input / len(self._usage_log) if self._usage_log else 0
            avg_output = total_output / len(self._usage_log) if self._usage_log else 0
            avg_cost = total_cost / len(self._usage_log) if self._usage_log else 0

            lines = [
                "# LLM Usage Report",
                "",
                f"Model: {self.model}",
                f"Total Requests: {len(self._usage_log)}",
                f"Total Input Tokens: {total_input:,}",
                f"Total Output Tokens: {total_output:,}",
                f"Total Cost (USD): ${total_cost:.6f}",
                f"Average Input Tokens/Request: {avg_input:.1f}",
                f"Average Output Tokens/Request: {avg_output:.1f}",
                f"Average Cost/Request: ${avg_cost:.6f}",
                "",
                "## Request Details",
                "",
                "| Timestamp | Type | Input Tokens | Output Tokens | Cost (USD) | Cache Hit |",
                "|-----------|------|--------------|---------------|------------|-----------|",
            ]
            for u in self._usage_log:
                lines.append(
                    f"| {u.timestamp} | {u.request_type} | {u.input_tokens} | {u.output_tokens} | ${u.cost_usd:.6f} | {u.cache_hit} |"
                )

            USAGE_LOG_FILE.write_text("\n".join(lines))
        except Exception as e:
            logger.warning(f"Failed to write usage report: {e}")

    def complete(
        self,
        messages: List[Dict[str, str]],
        system: str = "",
        request_type: str = "completion",
        max_retries: int = 1,
    ) -> LLMResponse:
        """Complete a chat request with caching and retry logic."""
        cache_key = self._get_cache_key(messages, system)

        cached = self._load_cache(cache_key)
        if cached:
            logger.info(f"Cache hit for {request_type}")
            return cached

        if not self.client:
            raise RuntimeError("LLM client not initialized. Set ANTHROPIC_API_KEY.")

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    system=system if system else anthropic.NOT_GIVEN,
                    messages=messages,
                )

                content = response.content[0].text if response.content else ""
                input_tokens = response.usage.input_tokens
                output_tokens = response.usage.output_tokens
                cost = self._calculate_cost(input_tokens, output_tokens)

                usage = LLMUsage(
                    model=self.model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    request_type=request_type,
                    cache_hit=False,
                )

                llm_response = LLMResponse(content=content, usage=usage, raw_response=response.model_dump())
                self._save_cache(cache_key, llm_response)
                self._log_usage(usage)
                return llm_response

            except Exception as e:
                last_error = e
                logger.warning(f"LLM request attempt {attempt + 1} failed: {e}")
                if attempt < max_retries:
                    time.sleep(2 ** attempt)

        raise RuntimeError(f"LLM request failed after {max_retries + 1} attempts: {last_error}")

    def complete_json(
        self,
        messages: List[Dict[str, str]],
        system: str = "",
        request_type: str = "json_completion",
        max_retries: int = 1,
    ) -> Dict[str, Any]:
        """Complete and parse JSON response."""
        response = self.complete(messages, system, request_type, max_retries)
        try:
            return json.loads(response.content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Raw content: {response.content[:500]}")
            raise