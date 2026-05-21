from __future__ import annotations

import os
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.api_client import ApiError, api_get, normalize_base_url


DEFAULT_API_BASE_URL = os.getenv("KG_API_BASE_URL", "http://127.0.0.1:8000")


st.set_page_config(
    page_title="SEC EDGAR Knowledge Graph",
    page_icon="KG",
    layout="wide",
)


def fetch(path: str, params: dict[str, Any] | None = None) -> Any:
    return api_get(st.session_state["api_base_url"], path, params=params)


def frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def metric_row(summary: dict[str, Any]) -> None:
    labels = {row["label"]: row["count"] for row in summary.get("labels", [])}
    relationships = {row["type"]: row["count"] for row in summary.get("relationships", [])}
    statuses = {row["status"]: row["count"] for row in summary.get("review_statuses", [])}

    cols = st.columns(4)
    cols[0].metric("Companies", labels.get("Company", 0))
    cols[1].metric("Filings", labels.get("Filing", 0))
    cols[2].metric("Relationships", sum(relationships.values()))
    cols[3].metric("Review Edges", statuses.get("review", 0))


def show_connection_error(error: ApiError) -> None:
    st.error(str(error))
    st.code("uv run uvicorn api.main:app --reload --host 127.0.0.1 --port 8000", language="bash")
    st.stop()


if "api_base_url" not in st.session_state:
    st.session_state["api_base_url"] = normalize_base_url(DEFAULT_API_BASE_URL)

with st.sidebar:
    st.header("Connection")
    st.text_input("API base URL", key="api_base_url")
    st.divider()
    st.header("Company")
    selected_ticker = st.text_input("Ticker", value="CAT").upper().strip()
    neighbor_limit = st.slider("Neighbor limit", min_value=5, max_value=100, value=25, step=5)

st.title("SEC EDGAR Financial Knowledge Graph")
st.caption("25-company pilot over SEC filings, Neo4j, RDF, graph algorithms, and review-gated extraction.")

try:
    health = fetch("/health")
    summary = fetch("/summary")
except ApiError as exc:
    show_connection_error(exc)

if health.get("status") == "ok":
    st.success("API connected to Neo4j")
else:
    st.warning("API is reachable, but Neo4j reported a degraded status.")

metric_row(summary)

overview_tab, company_tab, algorithms_tab, data_tab = st.tabs(
    ["Overview", "Company Explorer", "Algorithms", "Raw Tables"]
)

with overview_tab:
    left, right = st.columns(2)
    with left:
        rel_df = frame(summary.get("relationships", []))
        st.subheader("Relationship Mix")
        if not rel_df.empty:
            st.bar_chart(rel_df.set_index("type")["count"])
            st.dataframe(rel_df, use_container_width=True, hide_index=True)
    with right:
        label_df = frame(summary.get("labels", []))
        st.subheader("Node Labels")
        if not label_df.empty:
            st.bar_chart(label_df.set_index("label")["count"])
            st.dataframe(label_df, use_container_width=True, hide_index=True)

with company_tab:
    left, right = st.columns([0.9, 1.1])
    with left:
        st.subheader("Focal Companies")
        try:
            companies_df = frame(fetch("/companies", {"limit": 25}))
        except ApiError as exc:
            show_connection_error(exc)
        if not companies_df.empty:
            st.dataframe(
                companies_df[["ticker", "name", "degree", "cik"]],
                use_container_width=True,
                hide_index=True,
            )
    with right:
        st.subheader(selected_ticker or "Company")
        if selected_ticker:
            try:
                detail = fetch(f"/companies/{selected_ticker}")
                neighbors_df = frame(
                    fetch(f"/companies/{selected_ticker}/neighbors", {"limit": neighbor_limit})
                )
            except ApiError as exc:
                st.error(str(exc))
            else:
                st.metric("Graph Degree", detail.get("degree", 0))
                filings = frame([row for row in detail.get("filings", []) if row.get("accession_number")])
                if not filings.empty:
                    st.dataframe(filings, use_container_width=True, hide_index=True)
                st.markdown("#### Neighbors")
                if neighbors_df.empty:
                    st.info("No neighbors returned for this company.")
                else:
                    st.dataframe(
                        neighbors_df[
                            [
                                "relationship",
                                "label",
                                "key",
                                "name",
                                "confidence",
                                "review_status",
                                "source_text",
                            ]
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )

with algorithms_tab:
    try:
        pagerank_df = frame(fetch("/algorithms/pagerank", {"limit": 15}))
        communities_df = frame(fetch("/algorithms/communities", {"limit": 60}))
        similarity_df = frame(fetch("/algorithms/similarity", {"limit": 60}))
    except ApiError as exc:
        show_connection_error(exc)

    rank_col, community_col = st.columns(2)
    with rank_col:
        st.subheader("PageRank")
        if not pagerank_df.empty:
            st.bar_chart(pagerank_df.set_index("ticker")["score"])
            st.dataframe(pagerank_df, use_container_width=True, hide_index=True)
    with community_col:
        st.subheader("Largest Focal Communities")
        if not communities_df.empty:
            focal_communities = communities_df[communities_df["is_focal"] == True]  # noqa: E712
            st.dataframe(
                focal_communities[
                    ["ticker", "name", "communityId", "community_size", "is_focal"]
                ],
                use_container_width=True,
                hide_index=True,
            )

    st.subheader("Explainable Similarity")
    if similarity_df.empty:
        st.info("No similarity pairs found in the current pilot graph.")
    else:
        st.dataframe(similarity_df, use_container_width=True, hide_index=True)

with data_tab:
    st.subheader("API Payloads")
    st.json({"health": health, "summary": summary})
