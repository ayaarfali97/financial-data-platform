"""Financial Data Platform — Streamlit dashboard (4 tabs):
  1. Raw data explorer          (raw schema)
  2. Warehouse / KPI charts      (marts)
  3. ML insights                 (LM tone model)
  4. Ask a question              (Query Router Agent)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fdp.db import query_dicts          # noqa: E402
from fdp.settings import ROOT           # noqa: E402

st.set_page_config(page_title="Financial Data Platform", page_icon="📊", layout="wide")


@st.cache_data(ttl=300)
def q(sql: str, params=None) -> pd.DataFrame:
    return pd.DataFrame(query_dicts(sql, params))


TICKERS = ["AAPL", "AMD", "AMZN", "CSCO", "GOOGL", "INTC", "MSFT", "NVDA"]

st.title("📊 Financial Data Platform")
st.caption("Agentic data engineering — Raw → Warehouse → ML → Agentic query layer. "
           "8 tech companies, earnings-call transcripts + SEC financials, 2016–2020.")

tab_raw, tab_wh, tab_ml, tab_ask = st.tabs(
    ["🗂 Raw data", "🏢 Warehouse / KPIs", "🤖 ML insights", "💬 Ask a question"])

# ── Tab 1: Raw data explorer ────────────────────────────────────────────────
with tab_raw:
    st.subheader("Raw landing zone")
    c1, c2, c3, c4 = st.columns(4)
    counts = q("""
        select
          (select count(*) from raw.company)          as companies,
          (select count(*) from raw.financial_facts)  as financial_facts,
          (select count(*) from raw.transcripts)       as transcripts,
          (select count(*) from vector.transcript_chunks) as chunks
    """).iloc[0]
    c1.metric("Companies", int(counts.companies))
    c2.metric("Financial facts", f"{int(counts.financial_facts):,}")
    c3.metric("Transcripts", int(counts.transcripts))
    c4.metric("Vector chunks", f"{int(counts.chunks):,}")

    st.markdown("**Companies**")
    st.dataframe(q("select ticker, name, cik, sector from raw.company order by ticker"),
                 use_container_width=True, hide_index=True)

    st.markdown("**Raw financial facts** (SEC EDGAR)")
    tk = st.selectbox("Ticker", TICKERS, key="raw_tk")
    st.dataframe(
        q("""select concept, unit, value, fy, fp, form, period_end, filed
             from raw.financial_facts where ticker=%s
             order by period_end desc, concept limit 300""", [tk]),
        use_container_width=True, hide_index=True)

    st.markdown("**Transcripts** (metadata)")
    st.dataframe(
        q("""select ticker, call_date, fiscal_year, quarter, n_chars, source
             from raw.transcripts order by ticker, call_date"""),
        use_container_width=True, hide_index=True, height=240)

# ── Tab 2: Warehouse / KPIs ─────────────────────────────────────────────────
with tab_wh:
    st.subheader("Warehouse KPIs (dbt marts)")

    st.markdown("**Full-year revenue by company** (`mart_company_annual`)")
    annual = q("""select ticker, year, revenue/1e9 as revenue_bn,
                         net_margin_pct, gross_margin_pct, revenue_yoy_growth_pct
                  from marts.mart_company_annual order by ticker, year""")
    sel = st.multiselect("Companies", TICKERS, default=["AAPL", "AMZN", "MSFT", "NVDA"])
    a = annual[annual.ticker.isin(sel)]
    chart = alt.Chart(a).mark_line(point=True).encode(
        x=alt.X("year:O", title="Year"),
        y=alt.Y("revenue_bn:Q", title="Revenue ($B)"),
        color="ticker:N",
        tooltip=["ticker", "year", alt.Tooltip("revenue_bn:Q", format=".1f")],
    ).properties(height=340)
    st.altair_chart(chart, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Net margin % (annual)**")
        m = alt.Chart(a).mark_line(point=True).encode(
            x="year:O", y=alt.Y("net_margin_pct:Q", title="Net margin %"),
            color="ticker:N", tooltip=["ticker", "year", "net_margin_pct"]).properties(height=300)
        st.altair_chart(m, use_container_width=True)
    with col2:
        st.markdown("**Revenue YoY growth % (annual)**")
        g = alt.Chart(a.dropna(subset=["revenue_yoy_growth_pct"])).mark_bar().encode(
            x="year:O", y=alt.Y("revenue_yoy_growth_pct:Q", title="YoY growth %"),
            color="ticker:N", xOffset="ticker:N",
            tooltip=["ticker", "year", "revenue_yoy_growth_pct"]).properties(height=300)
        st.altair_chart(g, use_container_width=True)

    st.markdown("**Quarterly KPI detail** (`mart_company_kpis`)")
    tkq = st.selectbox("Ticker", TICKERS, key="wh_tk")
    st.dataframe(
        q("""select year_quarter, revenue/1e9 as revenue_bn, gross_margin_pct,
                    operating_margin_pct, net_margin_pct, revenue_yoy_growth_pct
             from marts.mart_company_kpis where ticker=%s
             order by period_end""", [tkq]),
        use_container_width=True, hide_index=True)

# ── Tab 3: ML insights ──────────────────────────────────────────────────────
with tab_ml:
    st.subheader("Earnings-call sentiment — Loughran-McDonald tone model")

    metrics_path = ROOT / "models_store" / "metrics.json"
    if metrics_path.exists():
        mj = json.loads(metrics_path.read_text())
        c1, c2, c3 = st.columns(3)
        c1.metric("Transcripts scored", mj.get("n_transcripts"))
        c2.metric("Lowest-tone quarter", mj.get("lowest_tone_quarter"),
                  help="Expected to be the 2020-Q2 COVID shock")
        c3.metric("Tone↔revenue Spearman", mj.get("spearman_tone_vs_revenue_growth"))

    st.markdown("**Average tone by quarter** (watch the 2020-Q2 COVID dip)")
    tone = q("""
        select to_char(call_date,'YYYY-"Q"Q') as quarter,
               avg(value_num) as avg_tone, count(*) as calls
        from ml.ml_outputs
        where model_name='lm_tone_v1' and metric='sentiment_score'
        group by 1 order by 1""")
    line = alt.Chart(tone).mark_line(point=True).encode(
        x=alt.X("quarter:N", title="Calendar quarter"),
        y=alt.Y("avg_tone:Q", title="Avg tone (polarity)"),
        tooltip=["quarter", alt.Tooltip("avg_tone:Q", format=".3f")]).properties(height=320)
    st.altair_chart(line, use_container_width=True)

    st.markdown("**Sentiment score by company over time**")
    bycomp = q("""
        select ticker, call_date, value_num as tone
        from ml.ml_outputs
        where model_name='lm_tone_v1' and metric='sentiment_score'
        order by ticker, call_date""")
    hm = alt.Chart(bycomp).mark_rect().encode(
        x=alt.X("yearquarter(call_date):O", title="Quarter"),
        y=alt.Y("ticker:N", title=""),
        color=alt.Color("tone:Q", scale=alt.Scale(scheme="redyellowgreen", domain=[-0.15, 0.4])),
        tooltip=["ticker", "call_date", alt.Tooltip("tone:Q", format=".3f")]).properties(height=300)
    st.altair_chart(hm, use_container_width=True)

    st.markdown("**Per-call sentiment table**")
    st.dataframe(
        q("""select s.ticker, s.call_date,
                    round(s.value_num::numeric,3) as sentiment_score,
                    l.value_text as label
             from ml.ml_outputs s
             join ml.ml_outputs l
               on l.transcript_id=s.transcript_id and l.metric='sentiment_label'
             where s.metric='sentiment_score'
             order by s.value_num asc"""),
        use_container_width=True, hide_index=True, height=260)

# ── Tab 4: Ask a question (router) ──────────────────────────────────────────
with tab_ask:
    st.subheader("Ask the Query Router Agent")
    st.caption("The agent classifies your question → SQL / vector / ML / hybrid, "
               "runs the tools, and synthesizes an answer.")

    examples = [
        "What was Amazon's full-year 2019 revenue?",
        "What did NVIDIA say about data center demand?",
        "Which earnings call had the most negative tone?",
        "Did Intel's tone match its revenue trend in 2020?",
    ]
    ex = st.selectbox("Example questions", ["—"] + examples)
    default = "" if ex == "—" else ex
    question = st.text_input("Your question", value=default,
                             placeholder="e.g. How did Microsoft's margins trend?")

    if st.button("Ask", type="primary") and question.strip():
        from agents.router.router import QueryRouter
        with st.spinner("Routing and answering…"):
            r = QueryRouter().answer(question)
        cols = st.columns(3)
        cols[0].metric("Route", r["route"])
        cols[1].metric("Tools used", ", ".join(r["tools_used"]) or "—")
        cols[2].metric("Latency", f"{r['latency_ms']} ms")
        st.info(f"**Rationale:** {r['rationale']}")
        st.markdown("### Answer")
        st.write(r["answer"])

        with st.expander("Retrieved context (observability)"):
            ctx = r["context"]
            if "sql" in ctx:
                st.markdown("**SQL**")
                st.code(ctx["sql"]["sql"], language="sql")
                st.dataframe(pd.DataFrame(ctx["sql"]["rows"]), use_container_width=True)
            if "sql_error" in ctx:
                st.warning(f"SQL error: {ctx['sql_error']}")
            if "vector" in ctx:
                st.markdown(f"**Transcript passages** (filters: {ctx['vector']['filters']})")
                for p in ctx["vector"]["passages"]:
                    st.markdown(f"- *{p['ticker']} {p['call_date']} "
                                f"(sim {p['similarity']:.3f})* — {p['content'][:400]}…")
            if "ml" in ctx:
                st.markdown("**Sentiment rows**")
                st.dataframe(pd.DataFrame(ctx["ml"]["rows"]), use_container_width=True)
