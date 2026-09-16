"""Query Router Agent.

Given a natural-language question it:
  1. classifies the best route  (sql | vector | ml | hybrid) with an LLM
  2. executes the chosen tool(s) over the warehouse / vectors / ML table
  3. synthesizes a natural-language answer grounded in the retrieved context
  4. logs question -> route -> answer to raw.router_log for observability

Usage:
  python -m agents.router.router "How fast did NVIDIA revenue grow in 2018?"
"""
from __future__ import annotations

import json
import sys
import time

from fdp.db import cursor
from fdp.llm import chat, chat_json

from . import tools

ROUTES = ("sql", "vector", "ml", "hybrid")

CLASSIFY_SYS = """You route a user's question about 8 tech companies (2016-2020)
to the right data source. Choose exactly one route:

- "sql":    quantitative facts from the financial warehouse — revenue, margins,
            growth rates, EPS, rankings, comparisons, anything numeric/aggregated.
- "vector": qualitative content from earnings-call transcripts — what management
            SAID, themes, explanations, commentary, reasons, tone-in-words.
- "ml":     model sentiment/tone scores per call (our LM tone model).
- "hybrid": needs BOTH numbers and transcript commentary (or sentiment + numbers),
            e.g. "did management's tone match the revenue trend?".

Return ONLY JSON: {"route": "...", "rationale": "one short sentence"}."""

SYNTH_SYS = """You are a financial analyst assistant. Answer the user's question
using ONLY the provided context (SQL rows, transcript passages, and/or sentiment
scores). Be concise and specific. ALWAYS name each company explicitly by its
ticker and/or name (e.g. "Amazon (AMZN)") when you discuss it, and cite the
relevant quarters and numbers. If the context is insufficient, say so plainly.
Do not invent figures."""


class QueryRouter:
    def classify(self, question: str) -> dict:
        try:
            out = chat_json([
                {"role": "system", "content": CLASSIFY_SYS},
                {"role": "user", "content": question},
            ], temperature=0.0)
            route = str(out.get("route", "")).lower().strip()
            if route not in ROUTES:
                route = "hybrid"
            return {"route": route, "rationale": out.get("rationale", "")}
        except Exception as exc:
            return {"route": "hybrid", "rationale": f"classifier fallback ({exc})"}

    def _gather(self, route: str, question: str) -> tuple[dict, list[str]]:
        ctx: dict = {}
        used: list[str] = []
        if route in ("sql", "hybrid"):
            try:
                ctx["sql"] = tools.run_sql(question)
                used.append("sql")
            except Exception as exc:
                ctx["sql_error"] = str(exc)
        if route in ("vector", "hybrid"):
            ctx["vector"] = tools.run_vector(question)
            used.append("vector")
        if route in ("ml", "hybrid"):
            ctx["ml"] = tools.run_ml(question)
            used.append("ml")
        # if a pure-sql route produced nothing useful, add vector as a backstop
        if route == "sql" and ctx.get("sql", {}).get("n", 0) == 0 and "sql_error" not in ctx:
            ctx["vector"] = tools.run_vector(question)
            used.append("vector")
        return ctx, used

    def _context_str(self, ctx: dict) -> str:
        parts = []
        if "sql" in ctx:
            s = ctx["sql"]
            parts.append(f"[SQL] query:\n{s['sql']}\nrows ({s['n']}):\n"
                         + json.dumps(s["rows"][:30], default=str))
        if "sql_error" in ctx:
            parts.append(f"[SQL] failed: {ctx['sql_error']}")
        if "vector" in ctx:
            v = ctx["vector"]
            passages = [
                f"({p['ticker']} {p['call_date']} {p.get('quarter') or ''} "
                f"sim={round(p['similarity'],3)}) {p['content'][:600]}"
                for p in v["passages"]
            ]
            parts.append(f"[TRANSCRIPTS] filters={v['filters']}\n" + "\n---\n".join(passages))
        if "ml" in ctx:
            ml = ctx["ml"]
            block = f"[SENTIMENT] per-call: {json.dumps(ml['rows'][:40], default=str)}"
            if ml.get("quarter_avg"):
                block += ("\n[SENTIMENT] avg-by-quarter across all companies "
                          "(ascending, lowest first): "
                          + json.dumps(ml["quarter_avg"][:6], default=str))
            parts.append(block)
        return "\n\n".join(parts)

    def synthesize(self, question: str, ctx: dict) -> str:
        context = self._context_str(ctx)
        return chat([
            {"role": "system", "content": SYNTH_SYS},
            {"role": "user", "content": f"Question: {question}\n\nContext:\n{context}\n\nAnswer:"},
        ], temperature=0.2, max_tokens=1200)

    def answer(self, question: str, log: bool = True) -> dict:
        t0 = time.time()
        cls = self.classify(question)
        route = cls["route"]
        ctx, used = self._gather(route, question)
        try:
            answer = self.synthesize(question, ctx)
            ok = True
        except Exception as exc:
            answer = f"Failed to synthesize an answer: {exc}"
            ok = False
        latency = int((time.time() - t0) * 1000)
        result = {"question": question, "route": route,
                  "rationale": cls["rationale"], "tools_used": used,
                  "context": ctx, "answer": answer, "latency_ms": latency, "ok": ok}
        if log:
            self._log(result)
        return result

    def _log(self, r: dict) -> None:
        try:
            with cursor() as cur:
                cur.execute(
                    """INSERT INTO raw.router_log
                       (question, route, rationale, tools_used, answer, latency_ms, ok)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (r["question"], r["route"], r["rationale"],
                     ",".join(r["tools_used"]), r["answer"], r["latency_ms"], r["ok"]),
                )
        except Exception:
            pass  # logging must never break answering


def main() -> int:
    if len(sys.argv) < 2:
        print('usage: python -m agents.router.router "your question"')
        return 1
    q = " ".join(sys.argv[1:])
    r = QueryRouter().answer(q)
    print(f"\nQ: {q}")
    print(f"route={r['route']}  tools={r['tools_used']}  {r['latency_ms']}ms")
    print(f"rationale: {r['rationale']}\n")
    print(r["answer"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
