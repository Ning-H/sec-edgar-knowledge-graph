from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from fastapi import HTTPException


def read_csv_rows(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"{path} does not exist yet. Run `uv run python -m algorithms.run_all` first.",
        )
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [{key: coerce_value(value) for key, value in row.items()} for row in csv.DictReader(handle)]
    return rows[:limit]


def coerce_value(value: str | None) -> Any:
    if value is None or value == "":
        return value
    if value == "True":
        return True
    if value == "False":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value
