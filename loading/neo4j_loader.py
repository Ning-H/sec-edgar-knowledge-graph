from __future__ import annotations

import os
from pathlib import Path

import typer
from dotenv import load_dotenv
from neo4j import GraphDatabase
from rich.console import Console

from loading.sample_reader import SampleGraph, load_sample_graph


app = typer.Typer(help="Load extracted sample graph into Neo4j.")
console = Console()


class Neo4jGraphLoader:
    def __init__(self) -> None:
        load_dotenv()
        self.uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = os.getenv("NEO4J_USER", "neo4j")
        self.password = os.getenv("NEO4J_PASSWORD", "financial-kg-local")
        self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))

    def close(self) -> None:
        self.driver.close()

    def reset(self) -> None:
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n").consume()

    def create_indexes(self) -> None:
        statements = [
            "CREATE CONSTRAINT company_ticker IF NOT EXISTS FOR (c:Company) REQUIRE c.ticker IS UNIQUE",
            "CREATE INDEX company_cik IF NOT EXISTS FOR (c:Company) ON (c.cik)",
            "CREATE CONSTRAINT filing_accession IF NOT EXISTS FOR (f:Filing) REQUIRE f.accession_number IS UNIQUE",
            "CREATE INDEX person_name IF NOT EXISTS FOR (p:Person) ON (p.name)",
            "CREATE INDEX industry_name IF NOT EXISTS FOR (i:Industry) ON (i.name)",
            "CREATE INDEX region_name IF NOT EXISTS FOR (g:GeographicRegion) ON (g.name)",
            "CREATE INDEX product_line_name IF NOT EXISTS FOR (p:ProductLine) ON (p.name)",
            "CREATE INDEX event_name IF NOT EXISTS FOR (e:Event) ON (e.name)",
        ]
        with self.driver.session() as session:
            for statement in statements:
                session.run(statement).consume()

    def load(self, graph: SampleGraph) -> None:
        with self.driver.session() as session:
            session.execute_write(self._merge_companies, graph.companies)
            session.execute_write(self._merge_filings, graph.filings)
            session.execute_write(self._merge_entities, graph.entities)
            session.execute_write(self._merge_relationships, graph.relationships)

    @staticmethod
    def _merge_companies(tx, companies: list[dict]) -> None:
        tx.run(
            """
            UNWIND $companies AS row
            MERGE (c:Company {ticker: row.ticker})
            SET c.name = row.name,
                c.cik = row.cik
            """,
            companies=companies,
        ).consume()

    @staticmethod
    def _merge_filings(tx, filings: list[dict]) -> None:
        tx.run(
            """
            UNWIND $filings AS row
            MERGE (f:Filing {accession_number: row.accession_number})
            SET f.path = row.path,
                f.form_type = row.form_type,
                f.ticker = row.ticker,
                f.cik = row.cik
            """,
            filings=filings,
        ).consume()

    @staticmethod
    def _merge_entities(tx, entities: list[dict]) -> None:
        for label in ["Person", "Industry", "GeographicRegion", "ProductLine", "Event", "Company"]:
            rows = [entity for entity in entities if entity["label"] == label]
            if not rows:
                continue
            key_property = "ticker" if label == "Company" else "key"
            tx.run(
                f"""
                UNWIND $rows AS row
                MERGE (n:{label} {{{key_property}: row.key}})
                SET n.name = row.name,
                    n.source = row.source,
                    n.confidence = row.confidence,
                    n.extraction_method = row.extraction_method
                """,
                rows=rows,
            ).consume()

    @staticmethod
    def _merge_relationships(tx, relationships: list[dict]) -> None:
        for rel_type in sorted({relationship["type"] for relationship in relationships}):
            rows = [relationship for relationship in relationships if relationship["type"] == rel_type]
            for source_label in sorted({row["source_label"] for row in rows}):
                for target_label in sorted({row["target_label"] for row in rows}):
                    scoped = [
                        row
                        for row in rows
                        if row["source_label"] == source_label and row["target_label"] == target_label
                    ]
                    if not scoped:
                        continue
                    source_key = key_property(source_label)
                    target_key = key_property(target_label)
                    tx.run(
                        f"""
                        UNWIND $rows AS row
                        MATCH (source:{source_label})
                        WHERE source.{source_key} = row.source_key
                        MATCH (target:{target_label})
                        WHERE target.{target_key} = row.target_key
                        MERGE (source)-[r:{rel_type}]->(target)
                        SET r.predicate = row.predicate,
                            r.confidence = row.confidence,
                            r.source_text = row.source_text,
                            r.rationale = row.rationale,
                            r.extraction_method = row.extraction_method
                        """,
                        rows=scoped,
                    ).consume()


@app.command()
def main(
    sample_path: Path = typer.Option(Path("data/extracted/phase3_sample_extraction.jsonl")),
    reset: bool = typer.Option(False, help="Delete existing Neo4j data before loading."),
) -> None:
    graph = load_sample_graph(sample_path)
    loader = Neo4jGraphLoader()
    try:
        if reset:
            loader.reset()
        loader.create_indexes()
        loader.load(graph)
    finally:
        loader.close()
    console.print(
        f"Loaded {len(graph.companies)} companies, {len(graph.filings)} filings, "
        f"{len(graph.entities)} entities, {len(graph.relationships)} relationships into Neo4j."
    )


def key_property(label: str) -> str:
    if label == "Company":
        return "ticker"
    if label == "Filing":
        return "accession_number"
    return "key"


if __name__ == "__main__":
    app()
