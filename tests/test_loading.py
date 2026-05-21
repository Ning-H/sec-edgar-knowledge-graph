from __future__ import annotations

from pathlib import Path

import pytest

from loading.rdf_loader import build_rdf_graph
from loading.sample_reader import load_sample_graph


def test_sample_graph_reader_if_available() -> None:
    sample = Path("data/extracted/phase3_sample_extraction.jsonl")
    if not sample.exists():
        pytest.skip("Local Phase 3 sample extraction output is not present.")

    graph = load_sample_graph(sample)

    assert graph.companies
    assert graph.filings
    assert graph.entities
    assert graph.relationships
    assert any(rel["type"] == "FILED" for rel in graph.relationships)


def test_rdf_graph_builder_if_available() -> None:
    sample = Path("data/extracted/phase3_sample_extraction.jsonl")
    if not sample.exists():
        pytest.skip("Local Phase 3 sample extraction output is not present.")

    graph = build_rdf_graph(sample)

    assert len(graph) > 0
