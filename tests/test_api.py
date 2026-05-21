from __future__ import annotations

import csv
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app, get_driver


class FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def data(self) -> list[dict]:
        return self._rows

    def single(self) -> dict | None:
        return self._rows[0] if self._rows else None


class FakeSession:
    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def run(self, query: str, **_params: object) -> FakeResult:
        if "RETURN 1 AS ok" in query:
            return FakeResult([{"ok": 1}])
        if "UNWIND labels(n) AS label" in query:
            return FakeResult([{"label": "Company", "count": 25}])
        if "RETURN type(r) AS type" in query:
            return FakeResult([{"type": "SUPPLIES", "count": 10}])
        if "review_status" in query and "RETURN coalesce" in query:
            return FakeResult([{"status": "approved", "count": 10}])
        if "MATCH (c:Company)" in query and "RETURN c.ticker AS ticker" in query:
            return FakeResult(
                [
                    {
                        "ticker": "CAT",
                        "name": "Caterpillar Inc.",
                        "cik": "0000018230",
                        "is_focal": True,
                        "degree": 20,
                    }
                ]
            )
        return FakeResult([])


class FakeDriver:
    def session(self) -> FakeSession:
        return FakeSession()


def test_health_and_summary_use_driver_dependency() -> None:
    app.dependency_overrides[get_driver] = lambda: FakeDriver()
    client = TestClient(app)
    try:
        assert client.get("/health").json() == {"status": "ok", "neo4j": True}
        summary = client.get("/summary").json()
        assert summary["labels"] == [{"label": "Company", "count": 25}]
        assert summary["relationships"] == [{"type": "SUPPLIES", "count": 10}]
        assert summary["review_statuses"] == [{"status": "approved", "count": 10}]
    finally:
        app.dependency_overrides.clear()


def test_algorithm_output_endpoint_reads_generated_csv(tmp_path: Path, monkeypatch) -> None:
    output_dir = tmp_path / "data" / "algorithms"
    output_dir.mkdir(parents=True)
    with (output_dir / "pagerank.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticker", "name", "score"])
        writer.writeheader()
        writer.writerow({"ticker": "CAT", "name": "Caterpillar Inc.", "score": "8.0"})

    monkeypatch.chdir(tmp_path)
    client = TestClient(app)

    assert client.get("/algorithms/pagerank").json() == [
        {"ticker": "CAT", "name": "Caterpillar Inc.", "score": 8.0}
    ]
