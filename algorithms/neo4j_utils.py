from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from dotenv import load_dotenv
from neo4j import Driver, GraphDatabase


@contextmanager
def neo4j_driver() -> Iterator[Driver]:
    load_dotenv()
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            os.getenv("NEO4J_USER", "neo4j"),
            os.getenv("NEO4J_PASSWORD", "financial-kg-local"),
        ),
    )
    try:
        yield driver
    finally:
        driver.close()
