# Cypher Examples

These examples target the Phase 4 sample graph loaded from `data/extracted/phase3_sample_extraction.jsonl`.

```cypher
MATCH (c:Company)
RETURN c.ticker, c.name
ORDER BY c.ticker;
```

```cypher
MATCH (c:Company {ticker: "AAPL"})-[r]->(n)
RETURN c.ticker, type(r), labels(n), n.name, r.confidence, r.extraction_method;
```

```cypher
MATCH (c:Company)-[r:COMPETES_WITH]->(n)
RETURN c.ticker, n.name, r.confidence, r.extraction_method
ORDER BY c.ticker, r.confidence DESC;
```

```cypher
MATCH (c:Company)-[r:SUPPLIES]->(p:ProductLine)
RETURN c.ticker, p.name, r.confidence, r.extraction_method
ORDER BY c.ticker, p.name;
```

```cypher
MATCH (c:Company)-[r:EXPOSED_TO]->(x)
RETURN c.ticker, labels(x), x.name, r.confidence
ORDER BY c.ticker, r.confidence DESC;
```

```cypher
MATCH (c:Company)-[r:SUBSIDIARY_OF]->(parent:Company)
RETURN c.name, parent.name, r.confidence;
```

```cypher
MATCH (c:Company)-[:FILED]->(f:Filing)
RETURN c.ticker, f.form_type, f.accession_number, f.path;
```

```cypher
MATCH (f:Filing)-[r:MENTIONS]->(n)
RETURN f.accession_number, labels(n), n.name, r.confidence
ORDER BY r.confidence DESC
LIMIT 25;
```

```cypher
MATCH (c:Company)-[r]->(n)
WHERE r.extraction_method STARTS WITH "claude:"
RETURN c.ticker, type(r), n.name, r.confidence
ORDER BY r.confidence DESC;
```

```cypher
MATCH (c:Company)-[r]->(n)
WHERE r.confidence < 0.7
RETURN c.ticker, type(r), n.name, r.confidence, r.extraction_method
ORDER BY r.confidence ASC;
```

```cypher
MATCH (c:Company)-[r]->(n)
WITH c, count(r) AS relationship_count
RETURN c.ticker, relationship_count
ORDER BY relationship_count DESC;
```

```cypher
MATCH path = (:Company {ticker: "PFE"})-[*1..2]-()
RETURN path
LIMIT 25;
```
