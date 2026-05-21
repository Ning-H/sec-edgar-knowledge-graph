# Ontology Design

The project ontology is a compact OWL model for SEC EDGAR-derived financial knowledge. It is FIBO-aligned by using FIBO IRIs for close matches and superclass anchors where the mapping is clear, while keeping project-specific extraction concepts in the local `fkg:` namespace.

Primary ontology file: [`financial_kg.ttl`](financial_kg.ttl)

## Design Principles

- Keep the schema small enough for extraction quality review.
- Separate filing evidence from business entities and relationships.
- Preserve SEC identifiers such as CIK and accession number as first-class properties.
- Use FIBO alignment for financial semantics without importing the entire FIBO module set in Phase 2.
- Leave confidence, source text, and extraction method available for downstream quality filters.

## Classes

| Class | Purpose | FIBO alignment |
| --- | --- | --- |
| `fkg:Company` | SEC registrant or public company in the graph. | Subclass of FIBO `Corporation`; close match to FIBO `LegalEntity`. |
| `fkg:Person` | Officer, director, executive, or named person extracted from filings. | Custom for now; can align to FIBO people/agents in a later import pass. |
| `fkg:Filing` | SEC 10-K, 10-Q, 8-K, DEF 14A, or other filing document. | Custom SEC document concept. |
| `fkg:Industry` | GICS sector, GICS sub-industry, SIC bucket, or algorithmic cluster label. | Custom classification concept. |
| `fkg:GeographicRegion` | Region, country, state, city, or market exposure. | Close match to FIBO `Location`. |
| `fkg:ProductLine` | Product, service, platform, business segment, or line of business. | Close match to FIBO `Product`. |
| `fkg:Event` | Acquisition, litigation, restructuring, disruption, or other material event. | Custom extraction-oriented event concept. |

## Object Properties

| Property | Domain | Range | Enables |
| --- | --- | --- | --- |
| `fkg:employs` | `Company` | `Person` | Officer/director lookup and governance neighborhoods. |
| `fkg:competesWith` | `Company` | `Company` | Peer discovery and competition networks. |
| `fkg:supplies` | `Company` | `owl:Thing` | Supply-chain and customer/vendor exposure. |
| `fkg:customerOf` | `Company` | `Company` | Inverse customer-to-supplier traversal. |
| `fkg:subsidiaryOf` | `Company` | `Company` | Corporate hierarchy and control chains. |
| `fkg:filed` | `Company` | `Filing` | Evidence lineage from company to source filing. |
| `fkg:exposedTo` | `Company` | `owl:Thing` | Geographic, product, industry, and event risk exposure. |
| `fkg:inIndustry` | `Company` | `Industry` | GICS/SIC filters and sector comparisons. |
| `fkg:locatedIn` | `owl:Thing` | `GeographicRegion` | Headquarters and exposure geography. |
| `fkg:mentions` | `Filing` | `owl:Thing` | Filing-to-extracted-entity evidence tracing. |

## Data Properties

| Property | Domain | Range |
| --- | --- | --- |
| `fkg:cik` | `Company` | `xsd:string` |
| `fkg:ticker` | `Company` | `xsd:string` |
| `fkg:name` | Any entity | `xsd:string` |
| `fkg:accessionNumber` | `Filing` | `xsd:string` |
| `fkg:formType` | `Filing` | `xsd:string` |
| `fkg:filingDate` | `Filing` | `xsd:date` |
| `fkg:sicCode` | `Company` | `xsd:string` |
| `fkg:reportedRevenue` | `Company` | `xsd:decimal` |
| `fkg:sourceText` | Any extracted entity or relationship node | `xsd:string` |
| `fkg:confidence` | Any extracted entity or relationship node | `xsd:decimal` |
| `fkg:extractionMethod` | Any extracted entity or relationship node | `xsd:string` |

## Example SPARQL Queries

Find a company's latest filings:

```sparql
PREFIX fkg: <https://github.com/Ning-H/sec-edgar-knowledge-graph/ontology#>

SELECT ?filing ?formType ?filingDate ?accession
WHERE {
  ?company a fkg:Company ;
           fkg:ticker "AAPL" ;
           fkg:filed ?filing .
  ?filing fkg:formType ?formType ;
          fkg:filingDate ?filingDate ;
          fkg:accessionNumber ?accession .
}
ORDER BY DESC(?filingDate)
```

Find competitors mentioned for a company:

```sparql
PREFIX fkg: <https://github.com/Ning-H/sec-edgar-knowledge-graph/ontology#>

SELECT ?peer ?peerName
WHERE {
  ?company a fkg:Company ;
           fkg:ticker "NVDA" ;
           fkg:competesWith ?peer .
  ?peer fkg:name ?peerName .
}
ORDER BY ?peerName
```

Find geographic exposures by industry:

```sparql
PREFIX fkg: <https://github.com/Ning-H/sec-edgar-knowledge-graph/ontology#>

SELECT ?companyName ?ticker ?regionName
WHERE {
  ?company a fkg:Company ;
           fkg:name ?companyName ;
           fkg:ticker ?ticker ;
           fkg:inIndustry ?industry ;
           fkg:exposedTo ?region .
  ?industry fkg:name "Semiconductors" .
  ?region a fkg:GeographicRegion ;
          fkg:name ?regionName .
}
ORDER BY ?companyName ?regionName
```

## Extraction Risks

LLM extraction will likely struggle with ambiguous competitive language, unnamed customer relationships, subsidiary names that are not public-company registrants, and geographic exposure that is material but not quantified. The ontology preserves source text and confidence so those cases can be filtered and audited instead of silently treated as facts.
