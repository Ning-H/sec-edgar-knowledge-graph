from __future__ import annotations

import re
from pathlib import Path

import typer
from rdflib import Graph, Literal, Namespace, RDF, URIRef
from rdflib.namespace import XSD
from rich.console import Console

from loading.sample_reader import load_sample_graph


FKG = Namespace("https://github.com/Ning-H/sec-edgar-knowledge-graph/ontology#")
RES = Namespace("https://github.com/Ning-H/sec-edgar-knowledge-graph/resource/")

app = typer.Typer(help="Mirror extracted sample graph into an RDF Turtle store.")
console = Console()


def build_rdf_graph(sample_path: Path) -> Graph:
    sample = load_sample_graph(sample_path)
    graph = Graph()
    graph.bind("fkg", FKG)
    graph.bind("res", RES)

    for company in sample.companies:
        subject = _resource("company", company["ticker"])
        graph.add((subject, RDF.type, FKG.Company))
        graph.add((subject, FKG.ticker, Literal(company["ticker"])))
        graph.add((subject, FKG.name, Literal(company["name"])))
        if company.get("cik"):
            graph.add((subject, FKG.cik, Literal(company["cik"])))

    for filing in sample.filings:
        subject = _resource("filing", filing["accession_number"])
        graph.add((subject, RDF.type, FKG.Filing))
        graph.add((subject, FKG.accessionNumber, Literal(filing["accession_number"])))
        graph.add((subject, FKG.formType, Literal(filing["form_type"])))

    for entity in sample.entities:
        subject = _resource(entity["label"], entity["key"])
        graph.add((subject, RDF.type, FKG[entity["label"]]))
        graph.add((subject, FKG.name, Literal(entity["name"])))
        graph.add((subject, FKG.confidence, Literal(entity["confidence"], datatype=XSD.decimal)))
        graph.add((subject, FKG.extractionMethod, Literal(entity["extraction_method"])))

    for relationship in sample.relationships:
        source = _resource(relationship["source_label"], relationship["source_key"])
        target = _resource(relationship["target_label"], relationship["target_key"])
        graph.add((source, FKG[_camel_case(relationship["predicate"])], target))
        statement = _resource(
            "statement",
            f"{relationship['source_key']}_{relationship['predicate']}_{relationship['target_key']}",
        )
        graph.add((statement, RDF.type, FKG.Event))
        graph.add((statement, FKG.sourceText, Literal(relationship["source_text"])))
        graph.add((statement, FKG.confidence, Literal(relationship["confidence"], datatype=XSD.decimal)))
        graph.add((statement, FKG.extractionMethod, Literal(relationship["extraction_method"])))

    return graph


@app.command()
def main(
    sample_path: Path = typer.Option(Path("data/extracted/phase3_sample_extraction.jsonl")),
    output: Path = typer.Option(Path("data/rdf/sample_graph.ttl")),
) -> None:
    graph = build_rdf_graph(sample_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    graph.serialize(destination=output, format="turtle")
    console.print(f"Wrote {len(graph)} RDF triples to {output}")


def _resource(kind: str, key: str) -> URIRef:
    return RES[f"{_slug(kind)}/{_slug(key)}"]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).casefold()).strip("-") or "unknown"


def _camel_case(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.title() for part in parts[1:])


if __name__ == "__main__":
    app()
