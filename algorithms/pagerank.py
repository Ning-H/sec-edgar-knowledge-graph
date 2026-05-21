from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from algorithms.export_utils import write_csv
from algorithms.neo4j_utils import neo4j_driver


GRAPH_NAME = "financial_kg_company_projection"
BUSINESS_RELATIONSHIPS = ["COMPETES_WITH", "SUPPLIES", "CUSTOMER_OF", "SUBSIDIARY_OF"]

app = typer.Typer(help="Run PageRank over the pilot company relationship graph.")
console = Console()


def recreate_company_projection() -> None:
    relationship_projection = {rel: {"orientation": "UNDIRECTED"} for rel in BUSINESS_RELATIONSHIPS}
    with neo4j_driver() as driver:
        with driver.session() as session:
            exists = session.run(
                "CALL gds.graph.exists($name) YIELD exists RETURN exists", name=GRAPH_NAME
            ).single()["exists"]
            if exists:
                session.run("CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName", name=GRAPH_NAME).consume()
            session.run(
                """
                CALL gds.graph.project(
                  $name,
                  "Company",
                  $relationship_projection
                )
                YIELD graphName
                RETURN graphName
                """,
                name=GRAPH_NAME,
                relationship_projection=relationship_projection,
            ).consume()


def run_pagerank(limit: int = 50) -> list[dict]:
    with neo4j_driver() as driver:
        with driver.session() as session:
            rows = session.run(
                """
                CALL gds.pageRank.stream($name)
                YIELD nodeId, score
                WITH gds.util.asNode(nodeId) AS node, score
                WITH node, score, exists { MATCH (node)-[:FILED]->(:Filing) } AS is_focal
                WHERE exists {
                  MATCH (focal:Company)-[:FILED]->(:Filing)
                  WHERE focal.ticker = node.ticker
                } OR score > 0 OR is_focal
                RETURN node.ticker AS ticker,
                       node.name AS name,
                       is_focal,
                       score,
                       COUNT { (node)--() } AS degree
                ORDER BY is_focal DESC, score DESC
                LIMIT $limit
                """,
                name=GRAPH_NAME,
                limit=limit,
            ).data()
    return rows


@app.command()
def main(output: Path = typer.Option(Path("data/algorithms/pagerank.csv"))) -> None:
    recreate_company_projection()
    rows = run_pagerank()
    write_csv(output, rows, ["ticker", "name", "is_focal", "score", "degree"])
    console.print(f"Wrote {len(rows)} PageRank rows to {output}")


if __name__ == "__main__":
    app()
