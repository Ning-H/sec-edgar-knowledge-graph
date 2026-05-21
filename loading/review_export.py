from __future__ import annotations

import csv
import json
from pathlib import Path

import typer
from rich.console import Console

from loading.sample_reader import LoadPolicy, relationship_quality


app = typer.Typer(help="Export extracted relationships for human review before graph loading.")
console = Console()


@app.command()
def main(
    sample_path: Path = typer.Option(Path("data/extracted/phase3_sample_extraction.jsonl")),
    output: Path = typer.Option(Path("data/extracted/relationship_review.csv")),
    strict: bool = typer.Option(False, help="Mark reviewable edges as excluded from strict loads."),
    heuristic_min_confidence: float = typer.Option(0.55, help="Minimum confidence for heuristic edges."),
) -> None:
    policy = LoadPolicy(
        heuristic_min_confidence=heuristic_min_confidence,
        include_reviewable=not strict,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with sample_path.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            for relationship in record["relationships"]:
                quality = relationship_quality(relationship, policy)
                rows.append(
                    {
                        "ticker": record["ticker"],
                        "accession_number": record["filing"]["accession_number"],
                        "subject": relationship["subject"],
                        "predicate": relationship["predicate"],
                        "object": relationship["object"],
                        "object_type": relationship["object_type"],
                        "confidence": relationship["confidence"],
                        "extraction_method": relationship["extraction_method"],
                        "review_status": quality["review_status"],
                        "load_decision": quality["load_decision"],
                        "source_text": relationship["source_text"],
                        "rationale": relationship["rationale"],
                    }
                )

    fieldnames = [
        "ticker",
        "accession_number",
        "subject",
        "predicate",
        "object",
        "object_type",
        "confidence",
        "extraction_method",
        "review_status",
        "load_decision",
        "source_text",
        "rationale",
    ]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    console.print(f"Wrote {len(rows)} review rows to {output}")


if __name__ == "__main__":
    app()
