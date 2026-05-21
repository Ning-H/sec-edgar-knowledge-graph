from __future__ import annotations

from dashboard.api_client import normalize_base_url


def test_normalize_base_url_defaults_and_trims() -> None:
    assert normalize_base_url("") == "http://127.0.0.1:8000"
    assert normalize_base_url(" http://localhost:9000/// ") == "http://localhost:9000/"
