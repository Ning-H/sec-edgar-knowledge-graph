from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query
from neo4j import Driver

from algorithms import louvain, pagerank, similarity
from algorithms.export_utils import write_csv
from algorithms.neo4j_utils import neo4j_driver
from api.csv_outputs import read_csv_rows


app = FastAPI(
    title="SEC EDGAR Financial Knowledge Graph API",
    description="Read-only API for the 25-company SEC filing knowledge graph pilot.",
    version="0.1.0",
)


def get_driver() -> Iterator[Driver]:
    with neo4j_driver() as driver:
        yield driver


DriverDep = Annotated[Driver, Depends(get_driver)]


@app.get("/health")
def health(driver: DriverDep) -> dict[str, Any]:
    try:
        with driver.session() as session:
            result = session.run("RETURN 1 AS ok").single()
        return {"status": "ok", "neo4j": bool(result and result["ok"] == 1)}
    except Exception as exc:  # pragma: no cover - defensive API boundary
        return {"status": "degraded", "neo4j": False, "error": str(exc)}


@app.get("/summary")
def summary(driver: DriverDep) -> dict[str, Any]:
    with driver.session() as session:
        labels = session.run(
            """
            MATCH (n)
            UNWIND labels(n) AS label
            RETURN label, count(*) AS count
            ORDER BY count DESC, label
            """
        ).data()
        relationships = session.run(
            """
            MATCH ()-[r]->()
            RETURN type(r) AS type, count(*) AS count
            ORDER BY count DESC, type
            """
        ).data()
        review_statuses = session.run(
            """
            MATCH ()-[r]->()
            RETURN coalesce(r.review_status, "unknown") AS status, count(*) AS count
            ORDER BY count DESC, status
            """
        ).data()
    return {"labels": labels, "relationships": relationships, "review_statuses": review_statuses}


@app.get("/companies")
def companies(
    driver: DriverDep,
    focal_only: bool = True,
    limit: Annotated[int, Query(ge=1, le=250)] = 50,
) -> list[dict[str, Any]]:
    query = """
    MATCH (c:Company)
    WITH c, exists { MATCH (c)-[:FILED]->(:Filing) } AS is_focal
    WHERE $focal_only = false OR is_focal
    RETURN c.ticker AS ticker,
           c.name AS name,
           c.cik AS cik,
           is_focal,
           COUNT { (c)--() } AS degree
    ORDER BY is_focal DESC, degree DESC, ticker
    LIMIT $limit
    """
    with driver.session() as session:
        return session.run(query, focal_only=focal_only, limit=limit).data()


@app.get("/companies/{ticker}")
def company_detail(ticker: str, driver: DriverDep) -> dict[str, Any]:
    with driver.session() as session:
        row = session.run(
            """
            MATCH (c:Company)
            WHERE toUpper(c.ticker) = toUpper($ticker)
            OPTIONAL MATCH (c)-[:FILED]->(f:Filing)
            RETURN c.ticker AS ticker,
                   c.name AS name,
                   c.cik AS cik,
                   COUNT { (c)--() } AS degree,
                   collect(DISTINCT {
                     accession_number: f.accession_number,
                     form_type: f.form_type,
                     path: f.path
                   }) AS filings
            """,
            ticker=ticker,
        ).single()
    if row is None or row["ticker"] is None:
        raise HTTPException(status_code=404, detail=f"Company {ticker} was not found.")
    return dict(row)


@app.get("/companies/{ticker}/neighbors")
def company_neighbors(
    ticker: str,
    driver: DriverDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[dict[str, Any]]:
    with driver.session() as session:
        return session.run(
            """
            MATCH (c:Company)
            WHERE toUpper(c.ticker) = toUpper($ticker)
            MATCH (c)-[r]-(n)
            RETURN type(r) AS relationship,
                   labels(n)[0] AS label,
                   coalesce(n.ticker, n.name, n.key, n.accession_number) AS key,
                   n.name AS name,
                   r.confidence AS confidence,
                   coalesce(r.review_status, "unknown") AS review_status,
                   r.source_text AS source_text
            ORDER BY relationship, label, key
            LIMIT $limit
            """,
            ticker=ticker,
            limit=limit,
        ).data()


@app.get("/algorithms/pagerank")
def pagerank_endpoint(
    refresh: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[dict[str, Any]]:
    path = Path("data/algorithms/pagerank.csv")
    if refresh:
        pagerank.recreate_company_projection()
        rows = pagerank.run_pagerank(limit=limit)
        write_csv(path, rows, ["ticker", "name", "is_focal", "score", "degree"])
        return rows
    return read_csv_rows(path, limit)


@app.get("/algorithms/communities")
def communities_endpoint(
    refresh: bool = False,
    limit: Annotated[int, Query(ge=1, le=250)] = 100,
) -> list[dict[str, Any]]:
    path = Path("data/algorithms/communities.csv")
    if refresh:
        pagerank.recreate_company_projection()
        rows = louvain.run_louvain()
        write_csv(path, rows, ["ticker", "name", "communityId", "community_size", "is_focal"])
        louvain.write_report(rows, Path("algorithms/community_report.md"))
        return rows[:limit]
    return read_csv_rows(path, limit)


@app.get("/algorithms/similarity")
def similarity_endpoint(
    refresh: bool = False,
    limit: Annotated[int, Query(ge=1, le=250)] = 100,
) -> list[dict[str, Any]]:
    path = Path("data/algorithms/similarity.csv")
    if refresh:
        rows = similarity.compute_similarity()
        write_csv(
            path,
            rows,
            [
                "ticker",
                "name",
                "similar_ticker",
                "similar_name",
                "jaccard",
                "shared_feature_count",
                "shared_features",
            ],
        )
        return rows[:limit]
    return read_csv_rows(path, limit)

