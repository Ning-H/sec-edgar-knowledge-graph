from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from pathlib import Path

import typer
from rich.console import Console

from algorithms.export_utils import write_csv
from algorithms.neo4j_utils import neo4j_driver


app = typer.Typer(help="Compute interpretable company similarity using shared graph neighborhoods.")
console = Console()


def feature_rows() -> list[dict]:
    with neo4j_driver() as driver:
        with driver.session() as session:
            return session.run(
                """
                MATCH (c:Company)-[:FILED]->(:Filing)
                OPTIONAL MATCH (c)-[r:SUPPLIES|EXPOSED_TO|COMPETES_WITH|CUSTOMER_OF|SUBSIDIARY_OF]->(n)
                WITH c, r, n
                WHERE r IS NULL OR r.review_status IN ["approved", "review"]
                WITH c, collect(DISTINCT CASE
                  WHEN r IS NULL THEN null
                  ELSE type(r) + ":" + coalesce(n.ticker, n.name, n.key)
                END) AS features
                RETURN c.ticker AS ticker, c.name AS name, features
                ORDER BY ticker
                """
            ).data()


def compute_similarity(top_k: int = 10) -> list[dict]:
    rows = feature_rows()
    features_by_ticker = {
        row["ticker"]: {feature for feature in row["features"] if feature and feature != "null:null"}
        for row in rows
    }
    names = {row["ticker"]: row["name"] for row in rows}
    similarities: list[dict] = []
    for left, right in combinations(sorted(features_by_ticker), 2):
        left_features = features_by_ticker[left]
        right_features = features_by_ticker[right]
        union = left_features | right_features
        if not union:
            continue
        shared = left_features & right_features
        score = len(shared) / len(union)
        if score <= 0:
            continue
        similarities.append(
            {
                "ticker": left,
                "name": names[left],
                "similar_ticker": right,
                "similar_name": names[right],
                "jaccard": round(score, 4),
                "shared_feature_count": len(shared),
                "shared_features": "; ".join(sorted(shared)[:12]),
            }
        )
        similarities.append(
            {
                "ticker": right,
                "name": names[right],
                "similar_ticker": left,
                "similar_name": names[left],
                "jaccard": round(score, 4),
                "shared_feature_count": len(shared),
                "shared_features": "; ".join(sorted(shared)[:12]),
            }
        )
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in similarities:
        grouped[row["ticker"]].append(row)
    output_rows: list[dict] = []
    for ticker, ticker_rows in grouped.items():
        output_rows.extend(
            sorted(ticker_rows, key=lambda row: (row["jaccard"], row["shared_feature_count"]), reverse=True)[:top_k]
        )
    return sorted(output_rows, key=lambda row: (row["ticker"], -row["jaccard"], row["similar_ticker"]))


@app.command()
def main(output: Path = typer.Option(Path("data/algorithms/similarity.csv"))) -> None:
    rows = compute_similarity()
    write_csv(
        output,
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
    console.print(f"Wrote {len(rows)} similarity rows to {output}")


if __name__ == "__main__":
    app()
