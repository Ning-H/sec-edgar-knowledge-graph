from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import typer
from anthropic import Anthropic
from dotenv import load_dotenv
from rich.console import Console

from extraction.filing_text import load_filing_sections
from extraction.ner_pipeline import ExtractedEntity, extract_entities_from_text, load_nlp


RelationType = Literal[
    "competes_with",
    "supplies",
    "customer_of",
    "subsidiary_of",
    "exposed_to",
]

RELATION_EXTRACTION_PROMPT = """You extract financial knowledge graph relationships from SEC filing text.

Return ONLY valid JSON with this shape:
{
  "relationships": [
    {
      "subject": "company or entity name",
      "predicate": "competes_with | supplies | customer_of | subsidiary_of | exposed_to",
      "object": "company, product line, region, industry, or event name",
      "object_type": "Company | ProductLine | GeographicRegion | Industry | Event",
      "confidence": 0.0,
      "source_text": "short exact evidence span from the filing",
      "rationale": "brief reason this relation is supported"
    }
  ]
}

Rules:
- Extract only relationships directly supported by the text.
- Prefer explicit competitors, suppliers, customers, subsidiaries, and geographic/product exposure.
- Do not infer a relationship from generic market wording unless the entities are named.
- Use lower confidence for vague or broad disclosures.
- Keep source_text under 300 characters.
"""

RELATION_TOOL = {
    "name": "record_relationships",
    "description": "Record SEC filing relationships for a financial knowledge graph.",
    "input_schema": {
        "type": "object",
        "properties": {
            "relationships": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string"},
                        "predicate": {
                            "type": "string",
                            "enum": [
                                "competes_with",
                                "supplies",
                                "customer_of",
                                "subsidiary_of",
                                "exposed_to",
                            ],
                        },
                        "object": {"type": "string"},
                        "object_type": {
                            "type": "string",
                            "enum": [
                                "Company",
                                "ProductLine",
                                "GeographicRegion",
                                "Industry",
                                "Event",
                            ],
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        },
                        "source_text": {"type": "string", "maxLength": 300},
                        "rationale": {"type": "string"},
                    },
                    "required": [
                        "subject",
                        "predicate",
                        "object",
                        "object_type",
                        "confidence",
                        "source_text",
                        "rationale",
                    ],
                },
            }
        },
        "required": ["relationships"],
    },
}

app = typer.Typer(help="Extract relationships from SEC filing text.")
console = Console()


@dataclass(frozen=True)
class ExtractedRelationship:
    subject: str
    predicate: RelationType
    object: str
    object_type: str
    confidence: float
    source_text: str
    rationale: str
    extraction_method: str


class ClaudeRelationExtractor:
    def __init__(self, model: str = "claude-haiku-4-5-20251001") -> None:
        load_dotenv()
        self.model = os.getenv("ANTHROPIC_MODEL", model)
        api_key = os.getenv("ANTHROPIC_API_KEY")
        self.client = Anthropic(api_key=api_key) if api_key else None

    @property
    def available(self) -> bool:
        return self.client is not None

    def extract(
        self,
        text: str,
        focal_company: str,
        max_chars: int = 18_000,
    ) -> list[ExtractedRelationship]:
        if not self.client:
            raise RuntimeError("ANTHROPIC_API_KEY is not set; use heuristic_extract_relations instead.")
        excerpt = _relationship_excerpt(text, max_chars=max_chars)
        message = self.client.messages.create(
            model=self.model,
            max_tokens=1800,
            temperature=0,
            system=RELATION_EXTRACTION_PROMPT,
            tools=[RELATION_TOOL],
            tool_choice={"type": "tool", "name": "record_relationships"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Focal company: {focal_company}\n\n"
                        f"SEC filing excerpt:\n{excerpt}"
                    ),
                }
            ],
        )
        payload = _payload_from_message(message)
        return [
            ExtractedRelationship(
                subject=item["subject"],
                predicate=item["predicate"],
                object=item["object"],
                object_type=item["object_type"],
                confidence=float(item["confidence"]),
                source_text=item["source_text"],
                rationale=item.get("rationale", ""),
                extraction_method=f"claude:{self.model}",
            )
            for item in payload.get("relationships", [])
        ]


def heuristic_extract_relations(
    text: str,
    focal_company: str,
    entities: list[ExtractedEntity],
    max_sentences: int = 80,
) -> list[ExtractedRelationship]:
    """Cheap fallback for checkpoint samples when no Claude key is configured."""

    orgs = [entity.text for entity in entities if entity.label == "ORG"]
    gpes = [entity.text for entity in entities if entity.label in {"GPE", "LOC"}]
    org_pattern = _alternation(orgs[:150])
    region_pattern = _alternation(gpes[:100])
    relationships: list[ExtractedRelationship] = []
    for sentence in _sentences(text)[:max_sentences]:
        lower = sentence.lower()
        if org_pattern and any(term in lower for term in ["compet", "rival", "peer"]):
            for org in re.findall(org_pattern, sentence, flags=re.IGNORECASE)[:4]:
                if _is_useful_org(org, focal_company):
                    relationships.append(
                        _relationship(
                            focal_company,
                            "competes_with",
                            org,
                            "Company",
                            0.55,
                            sentence,
                            "Competition keyword with named organization.",
                            "heuristic:competition_keyword",
                        )
                    )
        if org_pattern and any(term in lower for term in ["supplier", "supply", "vendor"]):
            for org in re.findall(org_pattern, sentence, flags=re.IGNORECASE)[:3]:
                if _is_useful_org(org, focal_company):
                    relationships.append(
                        _relationship(
                            org,
                            "supplies",
                            focal_company,
                            "Company",
                            0.5,
                            sentence,
                            "Supply-chain keyword with named organization.",
                            "heuristic:supply_keyword",
                        )
                    )
        if region_pattern and any(term in lower for term in ["market", "operations", "sales", "revenue"]):
            for region in re.findall(region_pattern, sentence, flags=re.IGNORECASE)[:3]:
                relationships.append(
                    _relationship(
                        focal_company,
                        "exposed_to",
                        region,
                        "GeographicRegion",
                        0.48,
                        sentence,
                        "Geographic mention in business-exposure context.",
                        "heuristic:geographic_exposure",
                    )
                )
    return _dedupe_relationships(relationships)[:40]


def heuristic_extract_business_profile(
    text: str,
    focal_company: str,
    max_sentences: int = 80,
) -> list[ExtractedRelationship]:
    """Extract product/market relationships from Item 1 Business language.

    This is deliberately conservative and records a separate extraction method so these
    relationships can be reviewed or filtered independently from Claude output.
    """

    relationships: list[ExtractedRelationship] = []
    product_patterns = [
        re.compile(
            r"(?:designs,\s+manufactures\s+and\s+markets|manufactures?\s+and\s+sells?|"
            r"markets,\s+sells?\s+and\s+distributes?|market,\s+sell\s+and\s+distribute|"
            r"manufacture,\s+marketing,\s+sale\s+and\s+distribution\s+of|"
            r"revenues\s+come\s+from\s+the\s+manufacture\s+and\s+sale\s+of)"
            r"\s+(?P<items>[^.;:]{8,260})",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:providing|provides|offers?)\s+(?P<items>[^.;:]{8,120}?"
            r"(?:merchandise\s+and\s+services|products\s+and\s+services|software|platforms|solutions))",
            re.IGNORECASE,
        ),
    ]
    market_patterns = [
        re.compile(r"(?:work\s+across)\s+(?P<items>[^.;:]{8,160})", re.IGNORECASE)
    ]

    product_profile_found = False
    for sentence in _sentences(text)[:max_sentences]:
        if not product_profile_found:
            for pattern in product_patterns:
                match = pattern.search(sentence)
                if not match:
                    continue
                items = _split_business_items(match.group("items"))
                for item in items:
                    relationships.append(
                        _relationship(
                            focal_company,
                            "supplies",
                            item,
                            "ProductLine",
                            0.68,
                            sentence,
                            "Business section directly describes products or services sold by the focal company.",
                            "heuristic:business_product_profile",
                        )
                    )
                if items:
                    product_profile_found = True
                    break
        for pattern in market_patterns:
            match = pattern.search(sentence)
            if not match:
                continue
            for item in _split_business_items(match.group("items")):
                relationships.append(
                    _relationship(
                        focal_company,
                        "exposed_to",
                        item,
                        "GeographicRegion",
                        0.62,
                        sentence,
                        "Business section directly describes operating markets or geographic scope.",
                        "heuristic:business_market_profile",
                    )
                )
    return _dedupe_relationships(relationships)[:20]


def _loads_json_object(content: str) -> dict:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, flags=re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))

    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(content[start : end + 1])

    preview = content[:500].replace("\n", " ")
    raise ValueError(f"Claude response did not contain parseable JSON. Preview: {preview}")


def _payload_from_message(message) -> dict:
    for block in message.content:
        if block.type == "tool_use" and block.name == "record_relationships":
            return block.input
    content = "".join(block.text for block in message.content if block.type == "text")
    return _loads_json_object(content)


def _relationship_excerpt(text: str, max_chars: int = 18_000) -> str:
    keywords = [
        "compet",
        "supplier",
        "supply",
        "customer",
        "subsidiar",
        "geographic",
        "international",
        "china",
        "europe",
        "japan",
        "canada",
        "market",
        "revenue",
        "product",
    ]
    parts = [text[:5_000]]
    seen: set[str] = set()
    for sentence in _sentences(text):
        lower = sentence.casefold()
        if not any(keyword in lower for keyword in keywords):
            continue
        normalized = re.sub(r"\s+", " ", sentence[:500]).strip()
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        parts.append(normalized)
        if sum(len(part) + 2 for part in parts) >= max_chars:
            break
    excerpt = "\n\n".join(parts)
    return excerpt[:max_chars]


def _relationship(
    subject: str,
    predicate: RelationType,
    object_: str,
    object_type: str,
    confidence: float,
    source_text: str,
    rationale: str,
    method: str,
) -> ExtractedRelationship:
    return ExtractedRelationship(
        subject=subject,
        predicate=predicate,
        object=object_,
        object_type=object_type,
        confidence=confidence,
        source_text=source_text[:300],
        rationale=rationale,
        extraction_method=method,
    )


def _split_business_items(raw: str) -> list[str]:
    if re.search(r"developed\s+and\s+emerging\s+markets", raw, flags=re.I):
        return ["Developed and emerging markets"]
    cleaned = re.sub(r"\([^)]*\)", "", raw)
    cleaned = re.sub(r"\b[A-Z][A-Za-z .,&-]+Form\s+10-K\s+\d+\b", "", cleaned)
    cleaned = re.sub(r"\b(?:worldwide|globally|principally|primarily|including|includes)\b", "", cleaned, flags=re.I)
    cleaned = cleaned.replace(" and ", ", ")
    cleaned = cleaned.replace(" or ", ", ")
    pieces = [piece.strip(" ,.-") for piece in cleaned.split(",")]
    stop_prefixes = (
        "sells a variety of ",
        "a variety of ",
        "broad assortment of ",
        "the ",
        "our ",
        "a ",
        "an ",
        "sells ",
        "sale of ",
    )
    items: list[str] = []
    for piece in pieces:
        piece = re.sub(r"\s+", " ", piece).strip()
        for prefix in stop_prefixes:
            if piece.casefold().startswith(prefix):
                piece = piece[len(prefix) :].strip()
        if not (3 <= len(piece) <= 80):
            continue
        if re.search(
            r"\b(form 10-k|customers?|pickup|following|stores|ecommerce|convenient|"
            r"strategic guidance|pfizer inc|similar|new products?|competitive environments?|"
            r"solely through the internet|non-financial companies|we develop|produce media content)\b",
            piece,
            flags=re.I,
        ):
            continue
        if piece.casefold() in {"products", "services", "business", "customers", "markets"}:
            continue
        items.append(piece[:1].upper() + piece[1:])
    return list(dict.fromkeys(items))


def _alternation(values: list[str]) -> str:
    cleaned = [value.strip() for value in values if _is_useful_org(value)]
    if not cleaned:
        return ""
    return r"\b(" + "|".join(re.escape(value) for value in sorted(set(cleaned), key=len, reverse=True)) + r")\b"


def _is_useful_org(value: str, focal_company: str | None = None) -> bool:
    cleaned = value.strip()
    if len(cleaned) <= 2:
        return False
    generic = {
        "the company",
        "company",
        "the corporation",
        "corporation",
        "the group",
        "group",
        "the nasdaq stock market llc",
        "new york stock exchange",
    }
    if cleaned.casefold() in generic:
        return False
    if focal_company and cleaned.casefold() == focal_company.casefold():
        return False
    return True


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;])\s+", text)
    return [part.strip() for part in parts if 80 <= len(part.strip()) <= 800]


def _dedupe_relationships(
    relationships: list[ExtractedRelationship],
) -> list[ExtractedRelationship]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[ExtractedRelationship] = []
    for rel in relationships:
        key = (rel.subject.casefold(), rel.predicate, rel.object.casefold())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(rel)
    return deduped


@app.command()
def file(
    filing_path: Path,
    output: Path = typer.Option(Path("data/extracted/relationships.jsonl")),
    focal_company: str | None = typer.Option(None),
) -> None:
    filing = load_filing_sections(filing_path)
    focal = focal_company or filing.metadata.ticker
    nlp = load_nlp()
    entities = extract_entities_from_text(filing.extraction_text, filing.metadata.accession_number, nlp)
    extractor = ClaudeRelationExtractor()
    relationships = (
        extractor.extract(filing.extraction_text, focal)
        if extractor.available
        else heuristic_extract_relations(filing.extraction_text, focal, entities)
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for relationship in relationships:
            handle.write(json.dumps(asdict(relationship)) + "\n")
    console.print(f"Wrote {len(relationships)} relationships to {output}")


if __name__ == "__main__":
    app()
