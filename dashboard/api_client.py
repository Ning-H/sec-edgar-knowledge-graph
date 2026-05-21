from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import requests


class ApiError(RuntimeError):
    pass


def normalize_base_url(base_url: str) -> str:
    stripped = base_url.strip()
    if not stripped:
        return "http://127.0.0.1:8000"
    return stripped.rstrip("/") + "/"


def api_get(base_url: str, path: str, params: dict[str, Any] | None = None) -> Any:
    url = urljoin(normalize_base_url(base_url), path.lstrip("/"))
    try:
        response = requests.get(url, params=params, timeout=8)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ApiError(f"Could not fetch {url}: {exc}") from exc
    return response.json()

