from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from algorithms import louvain, pagerank, similarity
from algorithms.export_utils import write_csv


app = typer.Typer(help="Run all pilot graph algorithms.")
console = Console()


@app.command()
def main() -> None:
    pagerank.recreate_company_projection()
    pagerank_rows = pagerank.run_pagerank()
    write_csv(
        Path("data/algorithms/pagerank.csv"),
        pagerank_rows,
        ["ticker", "name", "is_focal", "score", "degree"],
    )
    community_rows = louvain.run_louvain()
    write_csv(
        Path("data/algorithms/communities.csv"),
        community_rows,
        ["ticker", "name", "communityId", "community_size", "is_focal"],
    )
    louvain.write_report(community_rows, Path("algorithms/community_report.md"))
    similarity_rows = similarity.compute_similarity()
    write_csv(
        Path("data/algorithms/similarity.csv"),
        similarity_rows,
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
    console.print(
        f"Wrote {len(pagerank_rows)} PageRank rows, {len(community_rows)} community rows, "
        f"and {len(similarity_rows)} similarity rows."
    )


if __name__ == "__main__":
    app()
