from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PREDICATE_TO_RELATIONSHIP = {
    "competes_with": "COMPETES_WITH",
    "supplies": "SUPPLIES",
    "customer_of": "CUSTOMER_OF",
    "subsidiary_of": "SUBSIDIARY_OF",
    "exposed_to": "EXPOSED_TO",
}

OBJECT_TYPE_TO_LABEL = {
    "Company": "Company",
    "ProductLine": "ProductLine",
    "GeographicRegion": "GeographicRegion",
    "Industry": "Industry",
    "Event": "Event",
}


@dataclass(frozen=True)
class SampleGraph:
    companies: list[dict[str, Any]]
    filings: list[dict[str, Any]]
    entities: list[dict[str, Any]]
    relationships: list[dict[str, Any]]


@dataclass(frozen=True)
class LoadPolicy:
    min_confidence: float = 0.0
    heuristic_min_confidence: float = 0.55
    approved_confidence: float = 0.7
    include_reviewable: bool = True


def load_sample_graph(
    sample_path: Path = Path("data/extracted/phase3_sample_extraction.jsonl"),
    policy: LoadPolicy | None = None,
) -> SampleGraph:
    policy = policy or LoadPolicy()
    companies: dict[str, dict[str, Any]] = {}
    filings: dict[str, dict[str, Any]] = {}
    entities: dict[tuple[str, str], dict[str, Any]] = {}
    relationships: list[dict[str, Any]] = []

    with sample_path.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            ticker = record["ticker"]
            filing = record["filing"]
            cik = _zero_pad_cik(filing["cik"])
            company_name = _best_company_name(record, ticker)
            companies[ticker] = {
                "ticker": ticker,
                "cik": cik,
                "name": company_name,
            }
            filings[filing["accession_number"]] = {
                "accession_number": filing["accession_number"],
                "path": filing["path"],
                "form_type": "10-K",
                "ticker": ticker,
                "cik": cik,
            }

            relationships.append(
                {
                    "source_label": "Company",
                    "source_key": ticker,
                    "target_label": "Filing",
                    "target_key": filing["accession_number"],
                    "type": "FILED",
                    "predicate": "filed",
                    "confidence": 1.0,
                    "source_text": "",
                    "rationale": "Filing downloaded from SEC EDGAR submissions metadata.",
                    "extraction_method": "sec_submissions_metadata",
                }
            )

            for entity in record["entities"]:
                label = _entity_label(entity["label"])
                if label is None:
                    continue
                key = (label, _slug(entity["text"]))
                entities[key] = {
                    "label": label,
                    "key": key[1],
                    "name": entity["text"],
                    "source": entity["source"],
                    "confidence": entity["confidence"],
                    "extraction_method": entity["extraction_method"],
                }
                relationships.append(
                    {
                        "source_label": "Filing",
                        "source_key": filing["accession_number"],
                        "target_label": label,
                        "target_key": key[1],
                        "type": "MENTIONS",
                        "predicate": "mentions",
                        "confidence": entity["confidence"],
                        "source_text": entity["text"],
                        "rationale": "Entity mention extracted from filing text.",
                        "extraction_method": entity["extraction_method"],
                    }
                )

            for relationship in record["relationships"]:
                quality = relationship_quality(relationship, policy)
                if quality["load_decision"] == "exclude":
                    continue
                rel_type = PREDICATE_TO_RELATIONSHIP[relationship["predicate"]]
                target_label = OBJECT_TYPE_TO_LABEL[relationship["object_type"]]
                target_key = (
                    _company_key(relationship["object"], companies)
                    if target_label == "Company"
                    else _slug(relationship["object"])
                )
                if target_label != "Company":
                    entities[(target_label, target_key)] = {
                        "label": target_label,
                        "key": target_key,
                        "name": relationship["object"],
                        "source": filing["accession_number"],
                        "confidence": relationship["confidence"],
                        "extraction_method": relationship["extraction_method"],
                    }
                else:
                    companies.setdefault(
                        target_key,
                        {"ticker": target_key, "cik": None, "name": relationship["object"]},
                    )
                relationships.append(
                    {
                        "source_label": "Company",
                        "source_key": ticker,
                        "target_label": target_label,
                        "target_key": target_key,
                        "type": rel_type,
                        "predicate": relationship["predicate"],
                        "confidence": relationship["confidence"],
                        "source_text": relationship["source_text"],
                        "rationale": relationship["rationale"],
                        "extraction_method": relationship["extraction_method"],
                        "review_status": quality["review_status"],
                        "load_decision": quality["load_decision"],
                    }
                )

    return SampleGraph(
        companies=list(companies.values()),
        filings=list(filings.values()),
        entities=list(entities.values()),
        relationships=relationships,
    )


def relationship_quality(relationship: dict[str, Any], policy: LoadPolicy | None = None) -> dict[str, str]:
    policy = policy or LoadPolicy()
    confidence = float(relationship["confidence"])
    method = relationship["extraction_method"]
    is_heuristic = method.startswith("heuristic:")
    is_claude = method.startswith("claude:")

    if confidence < policy.min_confidence:
        return {"review_status": "rejected_low_confidence", "load_decision": "exclude"}
    if is_heuristic and confidence < policy.heuristic_min_confidence:
        return {"review_status": "rejected_heuristic_low_confidence", "load_decision": "exclude"}

    review_status = "approved" if is_claude and confidence >= policy.approved_confidence else "review"
    if not is_claude and not is_heuristic:
        review_status = "approved"
    if review_status == "review" and not policy.include_reviewable:
        return {"review_status": review_status, "load_decision": "exclude"}
    return {"review_status": review_status, "load_decision": "load"}


def _best_company_name(record: dict[str, Any], ticker: str) -> str:
    linked = [
        resolution
        for resolution in record.get("entity_resolution", [])
        if resolution.get("status") == "linked" and resolution.get("ticker") == ticker
    ]
    if linked:
        return linked[0]["matched_name"]
    return ticker


def _entity_label(spacy_label: str) -> str | None:
    return {
        "ORG": "Company",
        "PERSON": "Person",
        "GPE": "GeographicRegion",
        "LOC": "GeographicRegion",
        "PRODUCT": "ProductLine",
    }.get(spacy_label)


def _company_key(name: str, companies: dict[str, dict[str, Any]]) -> str:
    for ticker, company in companies.items():
        if name.casefold() in {ticker.casefold(), company["name"].casefold()}:
            return ticker
    return _slug(name)


def _zero_pad_cik(cik: str | int) -> str:
    return f"{int(cik):010d}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return slug or "unknown"
