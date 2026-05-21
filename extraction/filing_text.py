from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning


SECTION_STARTS = {
    "business": re.compile(r"\bitem\s+1[.\s:-]+business\b", re.IGNORECASE),
    "risk_factors": re.compile(r"\bitem\s+1a[.\s:-]+risk\s+factors\b", re.IGNORECASE),
    "mda": re.compile(
        r"\bitem\s+7[.\s:-]+management(?:'s|\u2019s)?\s+discussion\s+and\s+analysis\b",
        re.IGNORECASE,
    ),
}
SECTION_ENDS = {
    "business": [
        re.compile(r"\bitem\s+1a[.\s:-]+", re.IGNORECASE),
    ],
    "risk_factors": [
        re.compile(r"\bitem\s+1b[.\s:-]+", re.IGNORECASE),
        re.compile(r"\bitem\s+1c[.\s:-]+", re.IGNORECASE),
        re.compile(r"\bitem\s+2[.\s:-]+", re.IGNORECASE),
    ],
    "mda": [
        re.compile(r"\bitem\s+7a[.\s:-]+", re.IGNORECASE),
        re.compile(r"\bitem\s+8[.\s:-]+", re.IGNORECASE),
    ],
}


@dataclass(frozen=True)
class FilingMetadata:
    ticker: str
    cik: str
    accession_number: str
    path: str


@dataclass(frozen=True)
class FilingSections:
    metadata: FilingMetadata
    full_text: str
    sections: dict[str, str]

    @property
    def extraction_text(self) -> str:
        selected = [text for text in self.sections.values() if len(text) >= 1_000]
        if selected:
            return "\n\n".join(selected)
        return self.full_text[:300_000]


def metadata_from_path(path: Path) -> FilingMetadata:
    stem = path.stem
    parts = stem.split("_")
    if len(parts) < 3:
        raise ValueError(f"Expected '<ticker>_<cik>_<accession>.html' filename, got {path.name}")
    ticker = parts[0]
    cik = parts[1]
    accession = parts[2]
    return FilingMetadata(ticker=ticker, cik=cik, accession_number=accession, path=str(path))


def html_to_text(path: Path) -> str:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "lxml")
    for tag in soup(["script", "style", "ix:header"]):
        tag.decompose()
    text = soup.get_text(" ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    for name, start_pattern in SECTION_STARTS.items():
        sections[name] = _best_section(
            text,
            start_pattern,
            SECTION_ENDS[name],
            prefer_earliest=name == "business",
        )
    return sections


def _best_section(
    text: str,
    start_pattern: re.Pattern[str],
    end_patterns: list[re.Pattern[str]],
    min_chars: int = 5_000,
    max_chars: int = 160_000,
    prefer_earliest: bool = False,
) -> str:
    candidates: list[tuple[bool, str]] = []
    for start in start_pattern.finditer(text):
        preview = text[start.start() : start.start() + 900]
        if _looks_like_table_of_contents(preview) or _looks_like_cross_reference(preview):
            continue
        end_pos = _section_end(text, start.end(), end_patterns)
        has_explicit_end = end_pos is not None
        if end_pos is None:
            end_pos = min(len(text), start.start() + max_chars)
        section = text[start.start() : min(end_pos, start.start() + max_chars)].strip()
        if len(section) >= min_chars:
            if prefer_earliest:
                return section
            candidates.append((has_explicit_end, section))
    if not candidates:
        return ""
    return max(candidates, key=lambda candidate: (candidate[0], len(candidate[1])))[1]


def _section_end(
    text: str,
    start_pos: int,
    end_patterns: list[re.Pattern[str]],
    min_distance: int = 500,
) -> int | None:
    for pattern in end_patterns:
        matches = [
            match.start()
            for match in pattern.finditer(text, start_pos)
            if match.start() - start_pos >= min_distance
        ]
        if matches:
            return matches[0]
    return None


def _looks_like_table_of_contents(text: str) -> bool:
    return bool(
        re.search(r"\bitem\s+1a\b.{0,160}\bitem\s+1b\b", text, flags=re.IGNORECASE)
        or re.search(r"\bitem\s+7\b.{0,180}\bitem\s+7a\b", text, flags=re.IGNORECASE)
        or re.search(r"\bitem\s+7a\b.{0,180}\bitem\s+8\b", text, flags=re.IGNORECASE)
    )


def _looks_like_cross_reference(text: str) -> bool:
    preview = text[:180].casefold()
    if re.search(r"business\s*[—–-].{0,140}section", preview, flags=re.IGNORECASE):
        return True
    if re.search(r"risk factors\s*[—–-].{0,140}section", preview, flags=re.IGNORECASE):
        return True
    return any(
        phrase in preview
        for phrase in [
            "risk factors section",
            "risk factors of the",
            "risk factors in this form",
            "risk factors on pages",
            "risk factors—",
            "risk factors-",
            "business—",
            "business -",
            "business —",
            "business above",
            "business herein",
            "under the sub-caption",
            "management's discussion and analysis of financial condition and results of operations of the",
            "management’s discussion and analysis of financial condition and results of operations of the",
        ]
    )


def load_filing_sections(path: Path) -> FilingSections:
    full_text = html_to_text(path)
    return FilingSections(
        metadata=metadata_from_path(path),
        full_text=full_text,
        sections=extract_sections(full_text),
    )
