"""evidence_extractor.py - VLM/LLM extraction from images and messages (untrusted)."""

import os
import json
import base64
import hashlib
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from datetime import datetime

from buy_or_wait.llm_client import LLMClient, LLMResponse

logger = logging.getLogger(__name__)

EVIDENCE_CACHE_DIR = Path(__file__).parent / "cache" / "evidence"
EVIDENCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_EXTRACTION_PROMPT = (Path(__file__).parent / "prompts" / "image_extraction_prompt.md").read_text()
MESSAGE_EXTRACTION_PROMPT = (Path(__file__).parent / "prompts" / "message_extraction_prompt.md").read_text()

DATASET_IMAGES_DIR = Path(__file__).parent.parent / "dataset" / "media" / "images"


@dataclass
class ImageFact:
    fact_type: str
    amount: Optional[float]
    currency: Optional[str]
    date: Optional[str]
    reference_id: Optional[str]
    confidence: float
    evidence_summary: str
    no_relevant_fact: bool
    image_id: str
    event_id: Optional[str] = None
    request_id: Optional[str] = None
    raw_response: Optional[str] = None


@dataclass
class MessageFact:
    amendment_type: Optional[str]
    event_id: Optional[str]
    field: Optional[str]
    old_value: Optional[str]
    new_value: Optional[str]
    currency: Optional[str]
    effective_date: Optional[str]
    confidence: float
    evidence_summary: str
    no_relevant_fact: bool
    message_id: str
    request_id: Optional[str] = None
    raw_response: Optional[str] = None


def _get_image_cache_key(image_id: str, image_bytes: bytes) -> str:
    content_hash = hashlib.sha256(image_bytes).hexdigest()[:16]
    return f"img_{image_id}_{content_hash}"


def _get_message_cache_key(message_id: str, message_text: str) -> str:
    content_hash = hashlib.sha256(message_text.encode()).hexdigest()[:16]
    return f"msg_{message_id}_{content_hash}"


def _load_evidence_cache(cache_key: str) -> Optional[Dict]:
    cache_path = EVIDENCE_CACHE_DIR / f"{cache_key}.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text())
        except Exception as e:
            logger.warning(f"Evidence cache read failed: {e}")
    return None


def _save_evidence_cache(cache_key: str, data: Dict):
    cache_path = EVIDENCE_CACHE_DIR / f"{cache_key}.json"
    try:
        cache_path.write_text(json.dumps(data))
    except Exception as e:
        logger.warning(f"Evidence cache write failed: {e}")


def _encode_image(image_path: Path) -> Optional[bytes]:
    try:
        return image_path.read_bytes()
    except Exception as e:
        logger.warning(f"Failed to read image {image_path}: {e}")
        return None


def _image_to_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode()


def extract_image_fact(
    llm_client: LLMClient,
    image_id: str,
    event_id: Optional[str],
    request_id: Optional[str],
    max_retries: int = 1,
) -> ImageFact:
    """Extract financial facts from an image using VLM."""
    cache_key = _get_image_cache_key(image_id, b"")
    cached = _load_evidence_cache(cache_key)
    if cached:
        logger.info(f"Cache hit for image {image_id}")
        return ImageFact(**cached)

    image_path = DATASET_IMAGES_DIR / f"{image_id}.png"
    image_bytes = _encode_image(image_path)
    if image_bytes is None:
        return ImageFact(
            fact_type="other",
            amount=None,
            currency=None,
            date=None,
            reference_id=None,
            confidence=0.0,
            evidence_summary="Image file not found or unreadable",
            no_relevant_fact=True,
            image_id=image_id,
            event_id=event_id,
            request_id=request_id,
        )

    image_b64 = _image_to_base64(image_bytes)
    cache_key = _get_image_cache_key(image_id, image_bytes)
    cached = _load_evidence_cache(cache_key)
    if cached:
        logger.info(f"Cache hit for image {image_id} (with content hash)")
        return ImageFact(**cached)

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": IMAGE_EXTRACTION_PROMPT},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": image_b64,
                    },
                },
            ],
        }
    ]

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            response = llm_client.complete_json(
                messages=messages,
                system="",
                request_type=f"image_extraction_{image_id}",
                max_retries=0,
            )

            fact = ImageFact(
                fact_type=response.get("fact_type", "other"),
                amount=response.get("amount"),
                currency=response.get("currency"),
                date=response.get("date"),
                reference_id=response.get("reference_id"),
                confidence=response.get("confidence", 0.0),
                evidence_summary=response.get("evidence_summary", ""),
                no_relevant_fact=response.get("no_relevant_fact", False),
                image_id=image_id,
                event_id=event_id,
                request_id=request_id,
                raw_response=json.dumps(response),
            )

            if fact.confidence < 0.5 and attempt < max_retries:
                logger.warning(f"Low confidence ({fact.confidence}) for image {image_id}, retrying with stricter prompt")
                strict_prompt = IMAGE_EXTRACTION_PROMPT + "\n\nBe extremely conservative. Only extract facts you are highly certain about. If uncertain, return no_relevant_fact: true."
                messages[0]["content"][0]["text"] = strict_prompt
                continue

            _save_evidence_cache(cache_key, asdict(fact))
            return fact

        except Exception as e:
            last_error = e
            logger.warning(f"Image extraction attempt {attempt + 1} failed for {image_id}: {e}")
            if attempt < max_retries:
                continue

    logger.error(f"Image extraction failed for {image_id} after retries: {last_error}")
    return ImageFact(
        fact_type="other",
        amount=None,
        currency=None,
        date=None,
        reference_id=None,
        confidence=0.0,
        evidence_summary=f"Extraction failed: {last_error}",
        no_relevant_fact=True,
        image_id=image_id,
        event_id=event_id,
        request_id=request_id,
    )


def extract_message_fact(
    llm_client: LLMClient,
    message_id: str,
    message_text: str,
    related_event_id: Optional[str],
    request_id: Optional[str],
    max_retries: int = 1,
) -> MessageFact:
    """Extract financial amendments from a message using LLM."""
    cache_key = _get_message_cache_key(message_id, message_text)
    cached = _load_evidence_cache(cache_key)
    if cached:
        logger.info(f"Cache hit for message {message_id}")
        return MessageFact(**cached)

    messages = [
        {"role": "user", "content": f"{MESSAGE_EXTRACTION_PROMPT}\n\nMessage:\n{message_text}"}
    ]

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            response = llm_client.complete_json(
                messages=messages,
                system="",
                request_type=f"message_extraction_{message_id}",
                max_retries=0,
            )

            fact = MessageFact(
                amendment_type=response.get("amendment_type"),
                event_id=response.get("event_id") or related_event_id,
                field=response.get("field"),
                old_value=response.get("old_value"),
                new_value=response.get("new_value"),
                currency=response.get("currency"),
                effective_date=response.get("effective_date"),
                confidence=response.get("confidence", 0.0),
                evidence_summary=response.get("evidence_summary", ""),
                no_relevant_fact=response.get("no_relevant_fact", False),
                message_id=message_id,
                request_id=request_id,
                raw_response=json.dumps(response),
            )

            if fact.confidence < 0.5 and attempt < max_retries:
                logger.warning(f"Low confidence ({fact.confidence}) for message {message_id}, retrying")
                continue

            _save_evidence_cache(cache_key, asdict(fact))
            return fact

        except Exception as e:
            last_error = e
            logger.warning(f"Message extraction attempt {attempt + 1} failed for {message_id}: {e}")
            if attempt < max_retries:
                continue

    logger.error(f"Message extraction failed for {message_id} after retries: {last_error}")
    return MessageFact(
        amendment_type=None,
        event_id=related_event_id,
        field=None,
        old_value=None,
        new_value=None,
        currency=None,
        effective_date=None,
        confidence=0.0,
        evidence_summary=f"Extraction failed: {last_error}",
        no_relevant_fact=True,
        message_id=message_id,
        request_id=request_id,
    )


def extract_all_image_facts(
    llm_client: LLMClient,
    images_data: List[Dict[str, Any]],
) -> List[ImageFact]:
    """Extract facts from all images."""
    facts = []
    for img in images_data:
        fact = extract_image_fact(
            llm_client,
            image_id=img["image_id"],
            event_id=img.get("related_event_id"),
            request_id=img.get("request_id"),
        )
        facts.append(fact)
    return facts


def extract_all_message_facts(
    llm_client: LLMClient,
    messages_data: List[Dict[str, Any]],
) -> List[MessageFact]:
    """Extract facts from all messages."""
    facts = []
    for msg in messages_data:
        fact = extract_message_fact(
            llm_client,
            message_id=msg["message_id"],
            message_text=msg["message_text"],
            related_event_id=msg.get("related_event_id"),
            request_id=msg.get("request_id"),
        )
        facts.append(fact)
    return facts