"""Eval Agent — runs the Q&A set against the Query Router Agent and reports
pass/fail as proof-of-correctness.

Checks per question:
  * route_ok    : classifier picked an acceptable route
  * grounded    : at least one tool returned context (rows/passages)
  * include_ok  : all required substrings present in the answer
  * any_ok      : at least one of the optional substrings present (if given)
A question PASSES when all applicable checks pass.

Usage:  python -m agents.eval.eval            # run + print report
        python -m agents.eval.eval --json     # also write results.json
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import yaml

from agents.router.router import QueryRouter

HERE = Path(__file__).parent

# free-tier gateways cap requests/minute; pace questions so a burst of hybrid
# calls doesn't trip the limit mid-run
THROTTLE_SECONDS = 4


def _grounded(ctx: dict) -> bool:
    if ctx.get("sql", {}).get("n", 0) > 0:
        return True
    if ctx.get("vector", {}).get("n", 0) > 0:
        return True
    if ctx.get("ml", {}).get("n", 0) > 0:
        return True
    return False


def evaluate() -> dict:
    pairs = yaml.safe_load((HERE / "qa_pairs.yml").read_text())["pairs"]
    router = QueryRouter()
    results = []
    for i, p in enumerate(pairs):
        if i:
            time.sleep(THROTTLE_SECONDS)
        r = router.answer(p["q"], log=False)
        ans = (r["answer"] or "").lower()

        route_ok = r["route"] in p["route"]
        grounded = _grounded(r["context"])
        include_ok = all(s.lower() in ans for s in p.get("include", []))
        any_list = p.get("any", [])
        any_ok = (not any_list) or any(s.lower() in ans for s in any_list)
        passed = route_ok and grounded and include_ok and any_ok

        results.append({
            "id": p["id"], "question": p["q"],
            "expected_route": p["route"], "got_route": r["route"],
            "route_ok": route_ok, "grounded": grounded,
            "include_ok": include_ok, "any_ok": any_ok,
            "passed": passed, "latency_ms": r["latency_ms"],
            "answer": r["answer"],
        })

    n = len(results)
    n_pass = sum(x["passed"] for x in results)
    by_route: dict[str, list] = {}
    for x, p in zip(results, pairs):
        cat = p["route"][0]
        by_route.setdefault(cat, []).append(x["passed"])
    summary = {
        "total": n, "passed": n_pass, "failed": n - n_pass,
        "pass_rate": round(n_pass / n, 3),
        "route_accuracy": round(sum(x["route_ok"] for x in results) / n, 3),
        "by_route": {k: f"{sum(v)}/{len(v)}" for k, v in by_route.items()},
        "avg_latency_ms": round(sum(x["latency_ms"] for x in results) / n),
    }
    return {"summary": summary, "results": results}


def print_report(report: dict) -> None:
    s = report["summary"]
    print("\n" + "=" * 74)
    print("QUERY ROUTER — EVAL REPORT")
    print("=" * 74)
    print(f"{'id':26} {'exp→got route':22} {'checks':14} result")
    print("-" * 74)
    for x in report["results"]:
        checks = "".join([
            "R" if x["route_ok"] else "r",
            "G" if x["grounded"] else "g",
            "I" if x["include_ok"] else "i",
            "A" if x["any_ok"] else "a",
        ])
        route = f"{'/'.join(x['expected_route'])}→{x['got_route']}"
        mark = "PASS" if x["passed"] else "FAIL"
        print(f"{x['id']:26} {route:22} {checks:14} {mark}")
    print("-" * 74)
    print(f"PASS {s['passed']}/{s['total']}  ({s['pass_rate']*100:.0f}%)   "
          f"route-accuracy {s['route_accuracy']*100:.0f}%   "
          f"avg {s['avg_latency_ms']}ms")
    print(f"by route: {s['by_route']}")
    print("=" * 74)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = evaluate()
    print_report(report)
    if args.json:
        out = HERE / "results.json"
        out.write_text(json.dumps(report, indent=2, default=str))
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
