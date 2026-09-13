import hashlib
from pathlib import Path

from buy_or_wait import config
from buy_or_wait.main import run_pipeline


def test_full_pipeline_smoke_and_reproducibility():
    output = run_pipeline()
    first = output.read_bytes()
    lines = first.decode("utf-8").splitlines()
    assert lines[0].split(",") == config.OUTPUT_COLUMNS
    assert len(lines) == 251
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(output.read_bytes()).hexdigest()

