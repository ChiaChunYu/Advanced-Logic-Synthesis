#!/usr/bin/env python3
"""Pipeline bookend utilities: verification and per-case recipe management.

Two subcommands:
  verify  -- check every output AIG against its truth table (ABC CEC),
             compare ADP to recorded best, report regressions.
  recipe  -- maintain student/case_recipes/<case>.json with classification,
             best ADP, winning synthesis method, and append-only history.

Usage:
  python3 student/pipeline_bookend.py verify
  python3 student/pipeline_bookend.py verify --update
  python3 student/pipeline_bookend.py recipe --refresh
  python3 student/pipeline_bookend.py recipe --summary
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import shutil
import sys
from pathlib import Path

ROOT        = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "student"))

from abc_core import is_equivalent, measure_adp

ABC         = ROOT / "student" / "abc"
BENCHMARKS  = ROOT / "benchmarks"
OUTPUT      = ROOT / "output"
BEST_OUTPUT = ROOT / "best_output"
LOGS        = ROOT / "student" / "logs"
RECIPES     = ROOT / "student" / "case_recipes"
ALL_CASES   = [f"ex{i}" for i in range(200, 300)]


# =============================================================================
# Section 1: Verify Reproduce
# =============================================================================
def _load_ref() -> dict[str, int]:
    ref: dict[str, int] = {}
    path = ROOT / "reference_result.csv"
    if path.exists():
        with open(path) as f:
            for row in csv.DictReader(f):
                ref[row["case"]] = int(row["adp"])
    return ref


def _cmd_verify(args: argparse.Namespace) -> int:

    ref = _load_ref()
    BEST_OUTPUT.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    improved: list[str] = []
    total_out = 0
    total_best = 0

    print(f"{'case':<7} {'output ADP':>12} {'best ADP':>12} {'ref ADP':>12}  status")
    print("-" * 60)
    for case in ALL_CASES:
        truth = BENCHMARKS / f"{case}.truth"
        out_aig = OUTPUT / f"{case}.aig"
        best_aig = BEST_OUTPUT / f"{case}.aig"

        if not truth.is_file():
            continue
        if not out_aig.is_file():
            failures.append(f"{case}: missing output AIG")
            print(f"{case:<7} {'MISSING':>12}")
            continue

        if not is_equivalent(ABC, truth, out_aig, 180, ROOT):
            failures.append(f"{case}: output AIG NOT equivalent")
            print(f"{case:<7} {'NOT_EQUIV':>12}")
            continue

        _, _, out_adp = measure_adp(ABC, out_aig, 120, ROOT)
        best_adp = None
        if best_aig.is_file():
            try:
                _, _, best_adp = measure_adp(ABC, best_aig, 120, ROOT)
            except Exception:
                best_adp = None

        status = "ok"
        if best_adp is None:
            status = "new"
            if args.update:
                shutil.copyfile(out_aig, best_aig)
                improved.append(case)
        elif out_adp > best_adp:
            status = f"REGRESSION (+{out_adp - best_adp})"
            failures.append(f"{case}: output ADP {out_adp} > best {best_adp}")
        elif out_adp < best_adp:
            status = f"improved (-{best_adp - out_adp})"
            if args.update:
                shutil.copyfile(out_aig, best_aig)
                improved.append(case)

        total_out += out_adp
        total_best += best_adp if best_adp is not None else out_adp
        ref_str = f"{ref.get(case, 0):>12,}" if case in ref else f"{'-':>12}"
        print(f"{case:<7} {out_adp:>12,} {(best_adp or 0):>12,} {ref_str}  {status}")

    print("-" * 60)
    print(f"Total output ADP: {total_out:,}   total best ADP: {total_best:,}")
    if improved:
        print(f"Updated best_output for {len(improved)} cases: {', '.join(improved)}")
    if failures:
        print(f"\nFAILURES ({len(failures)}):")
        for f in failures:
            print(f"  {f}")
        return 1
    print("\nAll cases reproduced at or better than best_output.")
    return 0



# =============================================================================
# Section 2: Recipe Store
# =============================================================================
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


def _cmd_recipe(args: argparse.Namespace) -> int:
    if args.refresh:
        refresh()
    if args.summary:
        summary()
    if not args.refresh and not args.summary:
        refresh()
        summary()
    return 0



# =============================================================================
# Combined CLI
# =============================================================================

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_v = sub.add_parser("verify", help="verify output/ AIGs against truth tables")
    p_v.add_argument("--update", action="store_true",
                     help="copy strict improvements into best_output/")

    p_r = sub.add_parser("recipe", help="manage per-case JSON recipes")
    p_r.add_argument("--refresh", action="store_true", help="update recipes from output/ + logs")
    p_r.add_argument("--summary", action="store_true", help="print per-case table sorted by ratio")

    args = ap.parse_args()
    if args.cmd == "verify":
        return _cmd_verify(args)
    return _cmd_recipe(args)


if __name__ == "__main__":
    raise SystemExit(main())
