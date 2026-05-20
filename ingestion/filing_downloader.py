from __future__ import annotations

from pathlib import Path

import pandas as pd
import typer
from rich.console import Console

from ingestion.edgar_client import SEC_SUBMISSIONS_URL, EdgarClient


DEFAULT_COMPANIES = Path("data/processed/sp500_companies.csv")
DEFAULT_RAW_DIR = Path("data/raw")

app = typer.Typer(help="Download latest SEC filings for companies in the processed company index.")
console = Console()


def latest_filing_metadata(client: EdgarClient, cik: int, form_type: str = "10-K") -> dict[str, str] | None:
    submissions = client.get_json(SEC_SUBMISSIONS_URL.format(cik=cik))
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accession_numbers = recent.get("accessionNumber", [])
    primary_documents = recent.get("primaryDocument", [])
    filing_dates = recent.get("filingDate", [])

    for idx, form in enumerate(forms):
        if form == form_type:
            return {
                "accession_number": accession_numbers[idx],
                "primary_document": primary_documents[idx],
                "filing_date": filing_dates[idx],
            }
    return None


def filing_document_url(cik: int, accession_number: str, primary_document: str) -> str:
    accession_compact = accession_number.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_compact}/{primary_document}"


def filing_output_path(raw_dir: Path, ticker: str, cik: int, accession_number: str, form_type: str) -> Path:
    safe_accession = accession_number.replace("-", "")
    return raw_dir / form_type.replace("/", "-") / f"{ticker}_{cik:010d}_{safe_accession}.html"


def download_latest_filings(
    companies_csv: Path = DEFAULT_COMPANIES,
    raw_dir: Path = DEFAULT_RAW_DIR,
    form_type: str = "10-K",
    limit: int | None = None,
) -> pd.DataFrame:
    client = EdgarClient()
    companies = pd.read_csv(companies_csv)
    if limit:
        companies = companies.head(limit)

    results: list[dict[str, str]] = []
    for row in companies.itertuples(index=False):
        if pd.isna(row.cik):
            results.append({"ticker": row.ticker, "status": "missing_cik"})
            continue

        cik = int(row.cik)
        metadata = latest_filing_metadata(client, cik, form_type=form_type)
        if metadata is None:
            results.append({"ticker": row.ticker, "cik": str(cik), "status": "not_found"})
            continue

        destination = filing_output_path(
            raw_dir=raw_dir,
            ticker=row.ticker,
            cik=cik,
            accession_number=metadata["accession_number"],
            form_type=form_type,
        )
        url = filing_document_url(cik, metadata["accession_number"], metadata["primary_document"])
        client.download_text(url, destination)
        results.append(
            {
                "ticker": row.ticker,
                "cik": str(cik),
                "form": form_type,
                "filing_date": metadata["filing_date"],
                "accession_number": metadata["accession_number"],
                "path": str(destination),
                "status": "downloaded",
            }
        )
        console.print(f"Downloaded {row.ticker} {form_type} -> {destination}")

    return pd.DataFrame(results)


@app.command()
def main(
    companies_csv: Path = typer.Option(DEFAULT_COMPANIES),
    raw_dir: Path = typer.Option(DEFAULT_RAW_DIR),
    form_type: str = typer.Option("10-K"),
    limit: int | None = typer.Option(None, help="Optional row limit for smoke tests."),
    manifest: Path = typer.Option(Path("data/processed/filing_manifest.csv")),
) -> None:
    result = download_latest_filings(companies_csv, raw_dir, form_type, limit)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(manifest, index=False)
    console.print(f"Wrote filing manifest to {manifest}")


if __name__ == "__main__":
    app()
