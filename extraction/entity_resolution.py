from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

from extraction.ner_pipeline import ExtractedEntity


@dataclass(frozen=True)
class ResolvedEntity:
    mention: str
    label: str
    matched_name: str | None
    ticker: str | None
    cik: str | None
    score: float
    resolution_method: str
    status: str


class CompanyResolver:
    def __init__(self, companies_csv: Path = Path("data/processed/sp500_companies.csv")) -> None:
        self.companies = pd.read_csv(companies_csv)
        self.companies["name_norm"] = self.companies["name"].astype(str)
        self.name_to_row = {
            row.name_norm: row for row in self.companies.itertuples(index=False)
        }
        self.choices = list(self.name_to_row)

    def resolve(self, mention: str, threshold: float = 92.0) -> ResolvedEntity:
        if not mention.strip():
            return self._unlinked(mention, score=0.0)
        ticker_hit = self.companies[self.companies["ticker"].str.casefold() == mention.casefold()]
        if not ticker_hit.empty:
            row = ticker_hit.iloc[0]
            return ResolvedEntity(
                mention=mention,
                label="ORG",
                matched_name=str(row["name"]),
                ticker=str(row["ticker"]),
                cik=str(int(row["cik"])),
                score=100.0,
                resolution_method="ticker_exact",
                status="linked",
            )

        match = process.extractOne(mention, self.choices, scorer=fuzz.token_set_ratio)
        if not match:
            return self._unlinked(mention, score=0.0)
        name, score, _ = match
        if score < threshold:
            return self._unlinked(mention, score=float(score))

        row = self.name_to_row[name]
        return ResolvedEntity(
            mention=mention,
            label="ORG",
            matched_name=str(row.name),
            ticker=str(row.ticker),
            cik=str(int(row.cik)),
            score=float(score),
            resolution_method="rapidfuzz_token_set_ratio",
            status="linked",
        )

    @staticmethod
    def _unlinked(mention: str, score: float) -> ResolvedEntity:
        return ResolvedEntity(
            mention=mention,
            label="ORG",
            matched_name=None,
            ticker=None,
            cik=None,
            score=score,
            resolution_method="rapidfuzz_token_set_ratio",
            status="unlinked",
        )


def resolve_org_mentions(
    entities: list[ExtractedEntity],
    resolver: CompanyResolver,
    limit: int | None = None,
) -> list[ResolvedEntity]:
    org_mentions = [entity.text for entity in entities if entity.label == "ORG"]
    unique_mentions = list(dict.fromkeys(org_mentions))
    if limit:
        unique_mentions = unique_mentions[:limit]
    return [resolver.resolve(mention) for mention in unique_mentions]
