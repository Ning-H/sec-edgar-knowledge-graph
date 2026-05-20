from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"


class EdgarClientError(RuntimeError):
    """Raised when the SEC EDGAR client cannot complete a request."""


@dataclass(frozen=True)
class EdgarClientConfig:
    user_agent: str
    requests_per_second: float = 8.0
    timeout_seconds: int = 30

    @classmethod
    def from_env(cls) -> "EdgarClientConfig":
        load_dotenv()
        user_agent = os.getenv("SEC_USER_AGENT", "").strip()
        if not user_agent or "example.com" in user_agent:
            raise EdgarClientError(
                "Set SEC_USER_AGENT in .env to a real contact string, e.g. "
                "'Ning Han your.email@example.com'. The SEC requires this."
            )

        return cls(
            user_agent=user_agent,
            requests_per_second=float(os.getenv("SEC_REQUESTS_PER_SECOND", "8")),
            timeout_seconds=int(os.getenv("SEC_TIMEOUT_SECONDS", "30")),
        )


class EdgarClient:
    """Small SEC client that centralizes fair-access headers and rate limiting."""

    def __init__(self, config: EdgarClientConfig | None = None) -> None:
        self.config = config or EdgarClientConfig.from_env()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.config.user_agent,
                "Accept-Encoding": "gzip, deflate",
            }
        )
        self._last_request_at = 0.0

    def get_json(self, url: str) -> dict[str, Any]:
        response = self._get(url)
        return response.json()

    def get_text(self, url: str) -> str:
        return self._get(url).text

    def download_text(self, url: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(self.get_text(url), encoding="utf-8")
        return destination

    def _get(self, url: str) -> requests.Response:
        self._respect_rate_limit()
        headers = {}
        if "data.sec.gov" in url:
            headers["Host"] = "data.sec.gov"
        elif "sec.gov" in url:
            headers["Host"] = "www.sec.gov"

        response = self.session.get(url, headers=headers, timeout=self.config.timeout_seconds)
        self._last_request_at = time.monotonic()
        if response.status_code >= 400:
            raise EdgarClientError(f"SEC request failed: {response.status_code} {url}")
        return response

    def _respect_rate_limit(self) -> None:
        min_interval = 1.0 / self.config.requests_per_second
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
