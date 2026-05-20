from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import pandas as pd
import typer
from bs4 import BeautifulSoup
from rich.console import Console

from ingestion.edgar_client import SEC_COMPANY_TICKERS_URL, EdgarClient


SP500_WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
DEFAULT_OUTPUT = Path("data/processed/sp500_companies.csv")

app = typer.Typer(help="Load S&P 500 constituents and attach SEC CIKs.")
console = Console()


@dataclass(frozen=True)
class Company:
    ticker: str
    name: str
    sector: str
    industry: str
    cik: int | None


def load_sec_ticker_map(client: EdgarClient) -> dict[str, int]:
    payload = client.get_json(SEC_COMPANY_TICKERS_URL)
    return {row["ticker"].upper(): int(row["cik_str"]) for row in payload.values()}


def load_sp500_table(client: EdgarClient) -> pd.DataFrame:
    html = client.get_text(SP500_WIKIPEDIA_URL)
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table#constituents")
    if table is None:
        raise RuntimeError("Could not find S&P 500 constituents table on Wikipedia.")

    rows = pd.read_html(StringIO(str(table)))[0]
    return rows.rename(
        columns={
            "Symbol": "ticker",
            "Security": "name",
            "GICS Sector": "sector",
            "GICS Sub-Industry": "industry",
        }
    )[["ticker", "name", "sector", "industry"]]


def build_sp500_company_frame(client: EdgarClient, limit: int | None = None) -> pd.DataFrame:
    sp500 = load_sp500_table(client)
    ticker_to_cik = load_sec_ticker_map(client)
    sp500["ticker"] = sp500["ticker"].str.replace(".", "-", regex=False).str.upper()
    sp500["cik"] = sp500["ticker"].map(ticker_to_cik)
    sp500 = sp500.sort_values("ticker").reset_index(drop=True)
    if limit:
        sp500 = sp500.head(limit)
    return sp500


@app.command()
def main(
    output: Path = typer.Option(DEFAULT_OUTPUT, help="CSV destination."),
    limit: int | None = typer.Option(None, help="Optional row limit for smoke tests."),
) -> None:
    client = EdgarClient()
    companies = build_sp500_company_frame(client, limit=limit)
    output.parent.mkdir(parents=True, exist_ok=True)
    companies.to_csv(output, index=False)
    missing = int(companies["cik"].isna().sum())
    console.print(f"Wrote {len(companies)} companies to {output} ({missing} missing CIKs).")


if __name__ == "__main__":
    app()
