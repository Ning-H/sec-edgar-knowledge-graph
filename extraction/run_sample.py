from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import typer
from rich.console import Console

from extraction.entity_resolution import CompanyResolver, resolve_org_mentions
from extraction.filing_text import load_filing_sections
from extraction.ner_pipeline import extract_entities_from_text, load_nlp, summarize_entities
from extraction.relation_extraction import (
    ClaudeRelationExtractor,
    RELATION_EXTRACTION_PROMPT,
    heuristic_extract_business_profile,
    heuristic_extract_relations,
)


DEFAULT_TICKERS = ["AAPL", "JPM", "WMT", "CAT", "PFE"]
PILOT_25_TICKERS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "JPM",
    "BAC",
    "GS",
    "WMT",
    "COST",
    "HD",
    "PFE",
    "JNJ",
    "UNH",
    "CAT",
    "BA",
    "GE",
    "XOM",
    "CVX",
    "NEE",
    "DUK",
    "PLD",
    "AMT",
    "LIN",
    "APD",
    "CMCSA",
]

app = typer.Typer(help="Run Phase 3 sample extraction on 5 diverse filings.")
console = Console()


def find_latest_filing(raw_dir: Path, ticker: str) -> Path:
    matches = sorted((raw_dir / "10-K").glob(f"{ticker}_*.html"))
    if not matches:
        raise FileNotFoundError(f"No 10-K filing found for {ticker} in {raw_dir / '10-K'}")
    return matches[-1]


@app.command()
def main(
    raw_dir: Path = typer.Option(Path("data/raw")),
    output: Path = typer.Option(Path("data/extracted/phase3_sample_extraction.jsonl")),
    stats_output: Path = typer.Option(Path("data/extracted/phase3_sample_stats.json")),
    companies_csv: Path = typer.Option(Path("data/processed/sp500_companies.csv")),
    tickers: str = typer.Option(
        ",".join(DEFAULT_TICKERS),
        help="Comma-separated tickers to extract, or 'pilot25'.",
    ),
) -> None:
    nlp = load_nlp()
    resolver = CompanyResolver(companies_csv)
    company_names = dict(
        zip(
            resolver.companies["ticker"].astype(str),
            resolver.companies["name"].astype(str),
            strict=False,
        )
    )
    llm = ClaudeRelationExtractor()
    records: list[dict] = []
    stats: list[dict] = []

    selected_tickers = _parse_tickers(tickers)
    for ticker in selected_tickers:
        filing_path = find_latest_filing(raw_dir, ticker)
        filing = load_filing_sections(filing_path)
        focal_company = company_names.get(ticker, ticker)
        entities = extract_entities_from_text(
            filing.extraction_text, filing.metadata.accession_number, nlp
        )
        if llm.available:
            relationships = llm.extract(filing.extraction_text, focal_company)
            if not relationships:
                relationships = heuristic_extract_relations(
                    filing.full_text, focal_company, entities
                )
        else:
            relationships = heuristic_extract_relations(filing.full_text, focal_company, entities)
        relationships = _merge_relationships(
            relationships,
            heuristic_extract_business_profile(filing.sections.get("business", ""), focal_company),
        )
        resolutions = resolve_org_mentions(entities, resolver, limit=30)
        record = {
            "ticker": ticker,
            "filing": asdict(filing.metadata),
            "sections_found": {
                section: bool(text) for section, text in filing.sections.items()
            },
            "entity_summary": summarize_entities(entities),
            "entities": [asdict(entity) for entity in entities[:80]],
            "relationships": [asdict(relationship) for relationship in relationships],
            "entity_resolution": [asdict(resolution) for resolution in resolutions],
            "relation_extraction_prompt": RELATION_EXTRACTION_PROMPT,
        }
        records.append(record)
        stats.append(
            {
                "ticker": ticker,
                "entity_count": len(entities),
                "relationship_count": len(relationships),
                "high_confidence_relationship_count": sum(
                    rel.confidence >= 0.7 for rel in relationships
                ),
                "entity_summary": summarize_entities(entities),
                "relationship_type_counts": _count_relationship_types(relationships),
            }
        )
        console.print(
            f"{ticker}: {len(entities)} entities, {len(relationships)} relationships"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    stats_output.write_text(json.dumps({"filings": stats}, indent=2), encoding="utf-8")
    console.print(f"Wrote extraction JSONL to {output}")
    console.print(f"Wrote extraction stats to {stats_output}")


def _parse_tickers(tickers: str) -> list[str]:
    if tickers.strip().casefold() == "pilot25":
        return PILOT_25_TICKERS
    return [ticker.strip().upper() for ticker in tickers.split(",") if ticker.strip()]


def _count_relationship_types(relationships) -> dict[str, int]:
    counts: dict[str, int] = {}
    for relationship in relationships:
        counts[relationship.predicate] = counts.get(relationship.predicate, 0) + 1
    return counts


def _merge_relationships(*groups):
    merged = []
    seen = set()
    for group in groups:
        for relationship in group:
            key = (
                relationship.subject.casefold(),
                relationship.predicate,
                relationship.object.casefold(),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(relationship)
    return merged


if __name__ == "__main__":
    app()
