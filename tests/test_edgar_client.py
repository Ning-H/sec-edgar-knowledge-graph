from __future__ import annotations

import time

from ingestion.edgar_client import EdgarClient, EdgarClientConfig


def test_rate_limit_waits_between_requests() -> None:
    client = EdgarClient(EdgarClientConfig(user_agent="Test test@example.com", requests_per_second=2))
    client._last_request_at = time.monotonic()
    start = time.monotonic()

    client._respect_rate_limit()

    assert time.monotonic() - start >= 0.45
