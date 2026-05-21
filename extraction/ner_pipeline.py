from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import spacy
import typer
from rich.console import Console
from spacy.language import Language

from extraction.filing_text import load_filing_sections


DEFAULT_SPACY_MODEL = "en_core_web_lg"
SUPPORTED_LABELS = {"ORG", "PERSON", "GPE", "LOC", "MONEY", "PRODUCT"}
KNOWN_ENTITY_PATTERNS = [
    ("Apple", "ORG"),
    ("Microsoft", "ORG"),
    ("Amazon", "ORG"),
    ("Google", "ORG"),
    ("Alphabet", "ORG"),
    ("Meta", "ORG"),
    ("NVIDIA", "ORG"),
    ("JPMorgan Chase", "ORG"),
    ("Walmart", "ORG"),
    ("Pfizer", "ORG"),
    ("Caterpillar", "ORG"),
    ("United States", "GPE"),
    ("China", "GPE"),
    ("Europe", "LOC"),
    ("Asia", "LOC"),
]

app = typer.Typer(help="Run baseline NER over SEC filing text.")
console = Console()


@dataclass(frozen=True)
class ExtractedEntity:
    text: str
    label: str
    start_char: int
    end_char: int
    source: str
    confidence: float
    extraction_method: str


def load_nlp(model_name: str | None = None) -> Language:
    model_name = model_name or os.getenv("SPACY_MODEL", DEFAULT_SPACY_MODEL)
    try:
        nlp = spacy.load(model_name)
    except OSError:
        nlp = spacy.blank("en")
        nlp.add_pipe("sentencizer")
        ruler = nlp.add_pipe("entity_ruler")
        ruler.add_patterns(
            [{"label": label, "pattern": text} for text, label in KNOWN_ENTITY_PATTERNS]
        )
    if "sentencizer" not in nlp.pipe_names and "parser" not in nlp.pipe_names:
        nlp.add_pipe("sentencizer")
    return nlp


def extract_entities_from_text(
    text: str,
    source: str,
    nlp: Language | None = None,
    max_chars: int = 250_000,
) -> list[ExtractedEntity]:
    nlp = nlp or load_nlp()
    doc = nlp(text[:max_chars])
    entities = [
        ExtractedEntity(
            text=ent.text.strip(),
            label=ent.label_,
            start_char=ent.start_char,
            end_char=ent.end_char,
            source=source,
            confidence=0.72 if ent.label_ in {"ORG", "PERSON", "GPE"} else 0.62,
            extraction_method=f"spacy:{nlp.meta.get('name', 'blank')}",
        )
        for ent in doc.ents
        if ent.label_ in SUPPORTED_LABELS and ent.text.strip()
    ]
    entities.extend(_regex_money_entities(text[:max_chars], source))
    entities.extend(_regex_org_entities(text[:max_chars], source))
    entities.extend(_regex_region_entities(text[:max_chars], source))
    return dedupe_entities(entities)


def _regex_money_entities(text: str, source: str) -> list[ExtractedEntity]:
    pattern = re.compile(r"\$[0-9][0-9,]*(?:\.[0-9]+)?\s?(?:billion|million|thousand)?", re.I)
    return [
        ExtractedEntity(
            text=match.group(0),
            label="MONEY",
            start_char=match.start(),
            end_char=match.end(),
            source=source,
            confidence=0.8,
            extraction_method="regex:money",
        )
        for match in pattern.finditer(text)
    ][:200]


def _regex_org_entities(text: str, source: str) -> list[ExtractedEntity]:
    pattern = re.compile(
        r"\b([A-Z][A-Za-z&.\-]+(?:\s+[A-Z][A-Za-z&.\-]+){0,5}\s+"
        r"(?:Inc\.?|Corporation|Corp\.?|Company|Co\.?|Holdings|Group|PLC|LLC))\b"
    )
    return [
        ExtractedEntity(
            text=match.group(1),
            label="ORG",
            start_char=match.start(1),
            end_char=match.end(1),
            source=source,
            confidence=0.58,
            extraction_method="regex:org_suffix",
        )
        for match in pattern.finditer(text)
    ][:200]


def _regex_region_entities(text: str, source: str) -> list[ExtractedEntity]:
    regions = [
        "United States",
        "China",
        "Europe",
        "European Union",
        "Asia",
        "Japan",
        "Canada",
        "Mexico",
        "India",
        "United Kingdom",
    ]
    pattern = re.compile(r"\b(" + "|".join(re.escape(region) for region in regions) + r")\b")
    return [
        ExtractedEntity(
            text=match.group(1),
            label="GPE",
            start_char=match.start(1),
            end_char=match.end(1),
            source=source,
            confidence=0.65,
            extraction_method="regex:region_seed",
        )
        for match in pattern.finditer(text)
    ][:100]


def dedupe_entities(entities: Iterable[ExtractedEntity]) -> list[ExtractedEntity]:
    seen: set[tuple[str, str]] = set()
    deduped: list[ExtractedEntity] = []
    for entity in entities:
        key = (entity.text.casefold(), entity.label)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entity)
    return deduped


def summarize_entities(entities: list[ExtractedEntity]) -> dict[str, int]:
    return dict(Counter(entity.label for entity in entities))


@app.command()
def file(
    filing_path: Path,
    output: Path = typer.Option(Path("data/extracted/entities.jsonl")),
    model: str = typer.Option(DEFAULT_SPACY_MODEL),
) -> None:
    filing = load_filing_sections(filing_path)
    entities = extract_entities_from_text(
        filing.extraction_text, source=filing.metadata.accession_number, nlp=load_nlp(model)
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for entity in entities:
            handle.write(json.dumps(asdict(entity)) + "\n")
    console.print(f"Wrote {len(entities)} entities to {output}")


if __name__ == "__main__":
    app()
