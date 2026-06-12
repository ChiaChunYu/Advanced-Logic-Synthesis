#!/usr/bin/env python3
"""Per-case optimization recipe store.

Maintains student/case_recipes/<case>.json — one JSON per case recording:
  - circuit classification (family labels, recommended strategy)
  - current best result (area / delay / ADP) and reference comparison
  - the winning synthesis method when known (mined from pipeline logs)
  - an append-only history of measured improvements over time
  - free-text notes (hand-editable; preserved across refreshes)

Usage (from project root, inside WSL):
  python3 student/recipe_store.py --refresh    # update recipes from output/ + logs
  python3 student/recipe_store.py --summary    # print per-case table sorted by ratio
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "student"))

from abc_core import measure_adp

ABC         = ROOT / "student" / "abc"
BENCHMARKS  = ROOT / "benchmarks"
OUTPUT      = ROOT / "output"
LOGS        = ROOT / "student" / "logs"
RECIPES     = ROOT / "student" / "case_recipes"
ALL_CASES   = [f"ex{i}" for i in range(200, 300)]


def _load_reference() -> dict[str, int]:
    ref: dict[str, int] = {}
    path = ROOT / "reference_result.csv"
    if path.exists():
        with open(path) as f:
            for row in csv.DictReader(f):
                ref[row["case"]] = int(row["adp"])
    return ref


def _load_classification() -> dict[str, dict]:
    """Family labels and recommended strategy from boolean fingerprinting."""
    info: dict[str, dict] = {}
    path = LOGS / "classification.csv"
    if path.exists():
        with open(path) as f:
            for row in csv.DictReader(f):
                info[row["case"]] = {
                    "labels": row.get("labels", ""),
                    "effective_support": row.get("effective_support", ""),
                    "recommended_strategy": row.get("recommended_strategy", ""),
                }
    return info


def _load_winning_methods() -> dict[str, dict]:
    """Selected initial method + flow per case from the last pipeline run."""
    methods: dict[str, dict] = {}
    path = LOGS / "reproduce_candidates.csv"
    if path.exists():
        with open(path) as f:
            for row in csv.DictReader(f):
                if row.get("selected") == "1":
                    methods[row["case"]] = {
                        "initial_method": row.get("initial_method", ""),
                        "flow_name": row.get("flow_name", ""),
                        "flow_commands": row.get("flow_commands", ""),
                    }
    return methods


def _recipe_path(case: str) -> Path:
    return RECIPES / f"{case}.json"


def _load_recipe(case: str) -> dict:
    path = _recipe_path(case)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {"case": case, "history": [], "notes": ""}


def refresh() -> None:
    RECIPES.mkdir(parents=True, exist_ok=True)
    ref = _load_reference()
    classification = _load_classification()
    methods = _load_winning_methods()
    today = _dt.date.today().isoformat()

    for case in ALL_CASES:
        aig = OUTPUT / f"{case}.aig"
        if not aig.is_file():
            continue
        try:
            area, delay, adp = measure_adp(ABC, aig, 60, ROOT)
        except Exception as exc:
            print(f"[{case}] measure failed: {exc}")
            continue

        recipe = _load_recipe(case)
        recipe["case"] = case
        if case in classification:
            recipe["classification"] = classification[case]
        if case in methods:
            recipe["initial_synthesis"] = methods[case]
        if case in ref:
            recipe["reference_adp"] = ref[case]
            recipe["ratio_vs_reference"] = round(adp / ref[case], 4)

        prev = recipe.get("best")
        if prev is None or adp != prev.get("adp"):
            recipe["history"].append({
                "date": today,
                "area": area, "delay": delay, "adp": adp,
                "prev_adp": prev.get("adp") if prev else None,
            })
        recipe["best"] = {"area": area, "delay": delay, "adp": adp, "date": today}

        _recipe_path(case).write_text(json.dumps(recipe, indent=2, ensure_ascii=False) + "\n")
    print(f"Refreshed recipes in {RECIPES}")


def summary() -> None:
    rows = []
    for case in ALL_CASES:
        path = _recipe_path(case)
        if not path.exists():
            continue
        r = json.loads(path.read_text())
        best = r.get("best", {})
        rows.append({
            "case": case,
            "adp": best.get("adp", 0),
            "area": best.get("area", 0),
            "delay": best.get("delay", 0),
            "ref": r.get("reference_adp", 0),
            "ratio": r.get("ratio_vs_reference", 0.0),
            "labels": r.get("classification", {}).get("labels", "")[:38],
            "method": r.get("initial_synthesis", {}).get("initial_method", ""),
        })
    rows.sort(key=lambda x: -(x["ratio"] or 0))
    total_adp = sum(x["adp"] for x in rows)
    total_ref = sum(x["ref"] for x in rows)
    beating = sum(1 for x in rows if x["ratio"] and x["ratio"] < 1.0)

    print(f"{'case':<7}{'ADP':>11}{'ref':>11}{'ratio':>8}  {'init method':<24} labels")
    print("-" * 100)
    for x in rows:
        print(f"{x['case']:<7}{x['adp']:>11,}{x['ref']:>11,}{x['ratio']:>8.3f}  "
              f"{x['method']:<24} {x['labels']}")
    print("-" * 100)
    print(f"Total ADP: {total_adp:,}   reference total: {total_ref:,}   "
          f"overall ratio: {total_adp / total_ref:.4f}   beating reference: {beating}/{len(rows)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    if args.refresh:
        refresh()
    if args.summary:
        summary()
    if not args.refresh and not args.summary:
        refresh()
        summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
