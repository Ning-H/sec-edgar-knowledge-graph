from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import typer
from rich.console import Console

from algorithms.export_utils import write_csv
from algorithms.neo4j_utils import neo4j_driver
from algorithms.pagerank import GRAPH_NAME, recreate_company_projection


app = typer.Typer(help="Run Louvain community detection over the pilot graph.")
console = Console()


def run_louvain() -> list[dict]:
    with neo4j_driver() as driver:
        with driver.session() as session:
            rows = session.run(
                """
                CALL gds.louvain.stream($name)
                YIELD nodeId, communityId
                WITH gds.util.asNode(nodeId) AS node, communityId
                RETURN node.ticker AS ticker,
                       node.name AS name,
                       communityId,
                       exists { MATCH (node)-[:FILED]->(:Filing) } AS is_focal
                """,
                name=GRAPH_NAME,
            ).data()
    community_sizes = Counter(int(row["communityId"]) for row in rows)
    for row in rows:
        row["community_size"] = community_sizes[int(row["communityId"])]
    return sorted(
        rows,
        key=lambda row: (
            not row["is_focal"],
            -int(row["community_size"]),
            int(row["communityId"]),
            row["ticker"] or "",
        ),
    )


def write_report(rows: list[dict], output: Path) -> None:
    communities: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        communities[int(row["communityId"])].append(row)
    size_counts = Counter(int(row["communityId"]) for row in rows)
    focal_counts = {
        community_id: sum(1 for row in members if row["is_focal"])
        for community_id, members in communities.items()
    }
    top = sorted(
        communities.items(),
        key=lambda item: (focal_counts[int(item[0])], len(item[1])),
        reverse=True,
    )[:10]

    lines = [
        "# Pilot Community Report",
        "",
        "This report is generated from the 25-company pilot graph, not the full S&P 500 graph.",
        "Reviewable heuristic edges are included, so communities are directional portfolio-demo signals.",
        "",
        f"Total communities: {len(communities)}",
        f"Total company nodes: {len(rows)}",
        "",
        "## Largest Communities",
        "",
    ]
    for community_id, members in top:
        sample = ", ".join(row["ticker"] for row in members[:15])
        lines.append(
            f"- Community {community_id}: {size_counts[community_id]} companies, "
            f"{focal_counts[community_id]} focal companies. Sample: {sample}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


@app.command()
def main(
    output: Path = typer.Option(Path("data/algorithms/communities.csv")),
    report: Path = typer.Option(Path("algorithms/community_report.md")),
) -> None:
    recreate_company_projection()
    rows = run_louvain()
    write_csv(output, rows, ["ticker", "name", "communityId", "community_size", "is_focal"])
    write_report(rows, report)
    console.print(f"Wrote {len(rows)} community rows to {output}")
    console.print(f"Wrote community report to {report}")


if __name__ == "__main__":
    app()
