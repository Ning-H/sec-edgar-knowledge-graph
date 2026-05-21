from __future__ import annotations

from pathlib import Path

import pytest

from extraction.entity_resolution import CompanyResolver
from extraction.filing_text import load_filing_sections
from extraction.ner_pipeline import extract_entities_from_text, load_nlp
from extraction.relation_extraction import heuristic_extract_relations


SAMPLE_TICKERS = ["AAPL", "JPM", "WMT", "CAT", "PFE"]


def test_filing_section_extraction_on_sample_if_available() -> None:
    path = Path("data/raw/10-K/AAPL_0000320193_000032019325000079.html")
    if not path.exists():
        pytest.skip("Local SEC sample filings are not present.")

    filing = load_filing_sections(path)

    assert filing.metadata.ticker == "AAPL"
    assert filing.full_text
    assert any(filing.sections.values())


def test_ner_and_heuristic_relations_on_five_samples_if_available() -> None:
    raw_dir = Path("data/raw/10-K")
    paths = [next(iter(sorted(raw_dir.glob(f"{ticker}_*.html"))), None) for ticker in SAMPLE_TICKERS]
    if any(path is None for path in paths):
        pytest.skip("Local SEC sample filings are not present.")

    nlp = load_nlp()
    for path in paths:
        assert path is not None
        filing = load_filing_sections(path)
        entities = extract_entities_from_text(
            filing.extraction_text, filing.metadata.accession_number, nlp, max_chars=40_000
        )
        relationships = heuristic_extract_relations(
            filing.extraction_text, filing.metadata.ticker, entities, max_sentences=30
        )
        assert entities
        assert isinstance(relationships, list)


def test_company_resolution_exact_ticker_if_available() -> None:
    companies = Path("data/processed/sp500_companies.csv")
    if not companies.exists():
        pytest.skip("Local S&P 500 company index is not present.")

    resolver = CompanyResolver(companies)
    resolved = resolver.resolve("AAPL")

    assert resolved.status == "linked"
    assert resolved.ticker == "AAPL"
