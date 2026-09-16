"""ML Agent — earnings-call financial-tone model on top of the warehouse.

Model choice (documented in the README): a supervised TF-IDF classifier trained
on this dataset's paragraph labels scores *below* the majority-class baseline
(~0.53 vs 0.56) — the labels are not learnable from text (they track post-call
price moves). So we use the finance-standard Loughran-McDonald sentiment
dictionary, which is deterministic and interpretable, and we VALIDATE it by
showing its tone score correlates with subsequent revenue growth.

Pipeline (reproducible, no notebook):
  1. score every transcript's LM tone (polarity in [-1, 1]) + label
  2. write predictions to ml.ml_outputs (idempotent upsert)
  3. validate: Spearman correlation between tone and the matching quarter's
     revenue YoY growth (from mart_company_kpis) -> models_store/metrics.json

Usage:  python -m agents.ml.train_sentiment
"""
from __future__ import annotations

import json
from datetime import timedelta

import pysentiment2 as ps
from scipy.stats import spearmanr

from fdp.db import cursor, query
from fdp.settings import ROOT

MODEL_NAME = "lm_tone_v1"
STORE = ROOT / "models_store"
STORE.mkdir(exist_ok=True)

POS_THRESH = 0.02
NEG_THRESH = -0.02

_lm = ps.LM()


def score_tone(text: str) -> tuple[float, str, float]:
    tokens = _lm.tokenize(text or "")
    s = _lm.get_score(tokens)
    polarity = float(s["Polarity"])
    subj = float(s["Subjectivity"])
    if polarity >= POS_THRESH:
        label = "positive"
    elif polarity <= NEG_THRESH:
        label = "negative"
    else:
        label = "neutral"
    return polarity, label, subj


UPSERT = """
INSERT INTO ml.ml_outputs
  (model_name, ticker, transcript_id, call_date, fiscal_year, quarter,
   metric, value_num, value_text)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (model_name, ticker, transcript_id, metric) DO UPDATE
  SET value_num = EXCLUDED.value_num, value_text = EXCLUDED.value_text,
      created_at = now()
"""


def score_all() -> list[dict]:
    rows = query(
        """SELECT transcript_id, ticker, call_date, fiscal_year, quarter, content
           FROM raw.transcripts ORDER BY ticker, call_date"""
    )
    out, scored = [], []
    for tid, ticker, call_date, fy, quarter, content in rows:
        polarity, label, subj = score_tone(content)
        scored.append({"transcript_id": tid, "ticker": ticker,
                       "call_date": call_date, "tone": polarity, "label": label})
        out += [
            (MODEL_NAME, ticker, tid, call_date, fy, quarter,
             "sentiment_score", polarity, None),
            (MODEL_NAME, ticker, tid, call_date, fy, quarter,
             "sentiment_label", None, label),
            (MODEL_NAME, ticker, tid, call_date, fy, quarter,
             "sentiment_subjectivity", subj, None),
        ]
    with cursor() as cur:
        cur.executemany(UPSERT, out)
    print(f"  [ml] scored {len(scored)} transcripts -> ml.ml_outputs")
    return scored


def validate(scored: list[dict]) -> dict:
    """Correlate each call's tone with the revenue YoY growth of the fiscal
    quarter that ended just before the call (nearest prior period end <=120d)."""
    kpis = query(
        """SELECT ticker, period_end, revenue_yoy_growth_pct
           FROM marts.mart_company_kpis
           WHERE revenue_yoy_growth_pct IS NOT NULL"""
    )
    by_ticker: dict[str, list] = {}
    for ticker, pend, growth in kpis:
        by_ticker.setdefault(ticker, []).append((pend, float(growth)))

    tones, growths = [], []
    for s in scored:
        cand = by_ticker.get(s["ticker"], [])
        call = s["call_date"]
        best = None
        for pend, growth in cand:
            if pend <= call and (call - pend) <= timedelta(days=120):
                if best is None or pend > best[0]:
                    best = (pend, growth)
        if best:
            tones.append(s["tone"])
            growths.append(best[1])

    # interpretable time-series check: mean tone by calendar quarter. A good
    # tone model should dip in stressed periods (e.g. the 2020-Q2 COVID shock).
    by_q: dict[str, list[float]] = {}
    for s in scored:
        cq = f"{s['call_date'].year}-Q{(s['call_date'].month - 1) // 3 + 1}"
        by_q.setdefault(cq, []).append(s["tone"])
    tone_by_quarter = {q: round(sum(v) / len(v), 3) for q, v in sorted(by_q.items())}
    trough_q = min(tone_by_quarter, key=tone_by_quarter.get)

    metrics = {"model": MODEL_NAME, "n_transcripts": len(scored),
               "n_matched_to_quarter": len(tones),
               "tone_by_quarter": tone_by_quarter,
               "lowest_tone_quarter": trough_q,
               "lowest_tone_value": tone_by_quarter[trough_q]}
    print(f"  [ml] lowest-tone quarter = {trough_q} ({tone_by_quarter[trough_q]}) "
          f"-- expected COVID trough at 2020-Q2")
    if len(tones) >= 10:
        rho, p = spearmanr(tones, growths)
        pos = [g for t, g in zip(tones, growths) if t > 0]
        neg = [g for t, g in zip(tones, growths) if t <= 0]
        metrics.update({
            "spearman_tone_vs_revenue_growth": round(float(rho), 4),
            "p_value": round(float(p), 4),
            "avg_revenue_growth_when_tone_positive": round(sum(pos) / len(pos), 2) if pos else None,
            "avg_revenue_growth_when_tone_negative": round(sum(neg) / len(neg), 2) if neg else None,
        })
        print(f"  [ml] validation: Spearman(tone, rev_growth)={metrics['spearman_tone_vs_revenue_growth']}"
              f" (p={metrics['p_value']}, n={len(tones)})")
    (STORE / "metrics.json").write_text(json.dumps(metrics, indent=2))
    return metrics


def main() -> int:
    print("== ML Agent | Loughran-McDonald earnings-call tone ==")
    scored = score_all()
    validate(scored)
    print("== ML complete ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
