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
RELATIONSHIP_PREDICATES = {
    "COMPETES_WITH": "https://github.com/Ning-H/sec-edgar-knowledge-graph/ontology#competesWith",
    "CUSTOMER_OF": "https://github.com/Ning-H/sec-edgar-knowledge-graph/ontology#customerOf",
    "EXPOSED_TO": "https://github.com/Ning-H/sec-edgar-knowledge-graph/ontology#exposedTo",
    "FILED": "https://github.com/Ning-H/sec-edgar-knowledge-graph/ontology#filed",
    "MENTIONS": "https://github.com/Ning-H/sec-edgar-knowledge-graph/ontology#mentions",
    "SUBSIDIARY_OF": "https://github.com/Ning-H/sec-edgar-knowledge-graph/ontology#subsidiaryOf",
    "SUPPLIES": "https://github.com/Ning-H/sec-edgar-knowledge-graph/ontology#supplies",
}
GENERIC_COMPANY_NAMES = ["Company", "Corporation", "Industry", "Products", "Services", "Group"]


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
            review_status_counts = session.run(
                """
                MATCH ()-[r]->()
                RETURN coalesce(r.review_status, "missing") AS review_status, count(*) AS count
                ORDER BY review_status
                """
            ).data()
            invalid_confidence = session.run(
                """
                MATCH ()-[r]->()
                WHERE r.confidence IS NULL OR r.confidence < 0 OR r.confidence > 1
                RETURN count(*) AS count
                """
            ).single()["count"]
            missing_evidence = session.run(
                """
                MATCH ()-[r]->()
                WHERE type(r) <> "FILED"
                  AND (r.extraction_method IS NULL OR r.extraction_method <> "sec_submissions_metadata")
                  AND (r.source_text IS NULL OR trim(r.source_text) = "")
                RETURN count(*) AS count
                """
            ).single()["count"]
            self_relationships = session.run(
                """
                MATCH (n)-[r]->(n)
                RETURN type(r) AS type, count(*) AS count
                ORDER BY type
                """
            ).data()
            generic_companies = session.run(
                """
                MATCH (c:Company)
                WHERE c.name IN $generic_names OR c.ticker IN $generic_names
                RETURN coalesce(c.ticker, c.key) AS key, c.name AS name
                ORDER BY key
                """,
                generic_names=GENERIC_COMPANY_NAMES,
            ).data()
    finally:
        driver.close()

    rdf_graph = Graph()
    rdf_graph.parse(rdf_path, format="turtle")
    predicate_counts = Counter(str(predicate) for _, predicate, _ in rdf_graph)
    neo4j_relationship_count_map = {
        row["type"]: row["count"] for row in relationship_counts if row["type"] in RELATIONSHIP_PREDICATES
    }
    rdf_relationship_count_map = {
        rel_type: predicate_counts.get(predicate_uri, 0)
        for rel_type, predicate_uri in RELATIONSHIP_PREDICATES.items()
    }
    relationship_count_diffs = {
        rel_type: {
            "neo4j": neo4j_relationship_count_map.get(rel_type, 0),
            "rdf": rdf_relationship_count_map.get(rel_type, 0),
        }
        for rel_type in RELATIONSHIP_PREDICATES
        if neo4j_relationship_count_map.get(rel_type, 0) != rdf_relationship_count_map.get(rel_type, 0)
    }
    checks = {
        "neo4j_has_nodes": sum(row["count"] for row in node_counts) > 0,
        "neo4j_has_relationships": sum(row["count"] for row in relationship_counts) > 0,
        "rdf_has_triples": len(rdf_graph) > 0,
        "no_orphan_nodes": not orphan_counts,
        "relationship_counts_match_rdf": not relationship_count_diffs,
        "relationship_confidence_valid": invalid_confidence == 0,
        "extracted_relationships_have_evidence": missing_evidence == 0,
        "no_self_relationships": not self_relationships,
        "no_generic_company_nodes": not generic_companies,
    }
    result = {
        "neo4j": {
            "node_counts": node_counts,
            "relationship_counts": relationship_counts,
            "orphan_counts": orphan_counts,
            "review_status_counts": review_status_counts,
            "invalid_confidence_relationships": invalid_confidence,
            "missing_evidence_relationships": missing_evidence,
            "self_relationships": self_relationships,
            "generic_companies": generic_companies,
        },
        "rdf": {
            "triple_count": len(rdf_graph),
            "type_counts": _rdf_type_counts(rdf_graph),
            "predicate_counts": dict(predicate_counts.most_common(20)),
            "relationship_count_diffs": relationship_count_diffs,
        },
        "checks": checks,
    }
    console.print(json.dumps(result, indent=2))
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise typer.Exit(code=1)


def _rdf_type_counts(graph: Graph) -> dict[str, int]:
    counts = Counter(str(object_) for _, _, object_ in graph.triples((None, RDF.type, None)))
    return dict(counts.most_common())


if __name__ == "__main__":
    app()
