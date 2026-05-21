from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import typer
from dotenv import load_dotenv
from neo4j import GraphDatabase
from rdflib import Graph
from rdflib.namespace import RDF
from rich.console import Console


app = typer.Typer(help="Validate Neo4j and RDF sample graph loads.")
console = Console()


@app.command()
def main(rdf_path: Path = typer.Option(Path("data/rdf/sample_graph.ttl"))) -> None:
    load_dotenv()
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            os.getenv("NEO4J_USER", "neo4j"),
            os.getenv("NEO4J_PASSWORD", "financial-kg-local"),
        ),
    )
    try:
        with driver.session() as session:
            node_counts = session.run(
                """
                MATCH (n)
                UNWIND labels(n) AS label
                RETURN label, count(*) AS count
                ORDER BY label
                """
            ).data()
            relationship_counts = session.run(
                """
                MATCH ()-[r]->()
                RETURN type(r) AS type, count(*) AS count
                ORDER BY type
                """
            ).data()
            orphan_counts = session.run(
                """
                MATCH (n)
                WHERE NOT (n)--()
                RETURN labels(n) AS labels, count(*) AS count
                """
            ).data()
    finally:
        driver.close()

    rdf_graph = Graph()
    rdf_graph.parse(rdf_path, format="turtle")
    predicate_counts = Counter(str(predicate) for _, predicate, _ in rdf_graph)
    result = {
        "neo4j": {
            "node_counts": node_counts,
            "relationship_counts": relationship_counts,
            "orphan_counts": orphan_counts,
        },
        "rdf": {
            "triple_count": len(rdf_graph),
            "type_counts": _rdf_type_counts(rdf_graph),
            "predicate_counts": dict(predicate_counts.most_common(20)),
        },
        "checks": {
            "neo4j_has_nodes": sum(row["count"] for row in node_counts) > 0,
            "neo4j_has_relationships": sum(row["count"] for row in relationship_counts) > 0,
            "rdf_has_triples": len(rdf_graph) > 0,
        },
    }
    console.print(json.dumps(result, indent=2))


def _rdf_type_counts(graph: Graph) -> dict[str, int]:
    counts = Counter(str(object_) for _, _, object_ in graph.triples((None, RDF.type, None)))
    return dict(counts.most_common())


if __name__ == "__main__":
    app()
