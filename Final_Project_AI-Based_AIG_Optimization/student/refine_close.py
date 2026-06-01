#!/usr/bin/env python3
"""
Parallel ABC flow search for cases above the reference ADP.
Runs all flows in parallel per case, iterates until convergence,
then writes improved AIGs to output/ (only if verified & strictly better).

Usage:
  python3 student/refine_close.py [--max-ratio 1.20] [--workers 8] [--timeout 60]
"""
import argparse, csv, re, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT      = Path(__file__).resolve().parent.parent
ABC       = ROOT / "student" / "abc"
BENCHMARKS= ROOT / "benchmarks"
OUTPUT    = ROOT / "output"
TMP       = Path("/tmp/refine_close")
TMP.mkdir(exist_ok=True)

REF_CSV   = ROOT / "reference_result.csv"

FLOWS = [
    ("resub4",          "resub -K 4; balance; rewrite -z; refactor -z; balance"),
    ("resub6",          "resub -K 6; balance; rewrite -z; refactor -z; balance"),
    ("resub8",          "resub -K 8; balance; rewrite -z; refactor -z; balance"),
    ("resub4x3",        "; ".join(["resub -K 4; balance; rewrite -z; refactor -z; balance"]*3)),
    ("resub6x2",        "; ".join(["resub -K 6; balance; rewrite -z; refactor -z; balance"]*2)),
    ("resub8_n2",       "resub -K 8 -N 2; balance; rewrite -z; refactor -z; balance"),
    ("resub6_f1",       "resub -K 6 -F 1; balance; rewrite -z; refactor -z; balance"),
    ("gia_can",         "&get; &put; strash; dc2; balance"),
    ("gia_can_x2",      "&get; &put; strash; dc2; balance; &get; &put; strash; dc2; balance"),
    ("gia_resyn2",      "&get; &resyn2; &put; balance; rewrite -z; refactor -z; balance"),
    ("gia_resyn3",      "&get; &resyn3; &put; balance; rewrite -z; refactor -z; balance"),
    ("gia_compress2rs", "&get; &compress2rs; &put; balance; rewrite -z; refactor -z; balance"),
    ("gia_resyn3rs",    "&get; &resyn3rs; &put; balance; rewrite -z; refactor -z; balance"),
    ("dc2_loop",        "dc2; rewrite -z; refactor -z; dc2; rewrite -z; refactor -z; balance"),
    ("fraig_dc2",       "fraig; dc2; rewrite -z; refactor -z; balance"),
    ("dch_if4",         "dch; if -K 4; strash; dc2; balance; rewrite -z; refactor -z; balance"),
    ("dch_if6",         "dch; if -K 6; strash; dc2; balance; rewrite -z; refactor -z; balance"),
    ("dch_if8",         "dch; if -K 8; strash; dc2; balance; rewrite -z; refactor -z; balance"),
    ("sopb_c8",         "&get; &sopb -C 8 -R 1; &put; balance; rewrite -z; refactor -z; balance"),
    ("sopb_c16",        "&get; &sopb -C 16 -R 1; &put; balance; rewrite -z; refactor -z; balance"),
    ("b_ds",            "&get; &b -d -s; &put; balance; rewrite -z; refactor -z; balance"),
    ("mfs2",            "mfs2; dc2; balance; rewrite -z; refactor -z; balance"),
    ("resub4_gia",      "resub -K 4; balance; rewrite -z; refactor -z; balance; &get; &put; strash; dc2; balance"),
    ("gia_resub4",      "&get; &put; strash; dc2; balance; resub -K 4; balance; rewrite -z; refactor -z; balance"),
    ("dch_if6_resub4",  "dch; if -K 6; strash; dc2; balance; resub -K 4; balance; rewrite -z; refactor -z; balance"),
    ("dch_if6_resub6",  "dch; if -K 6; strash; dc2; balance; resub -K 6; balance; rewrite -z; refactor -z; balance"),
    ("compress2rs_lp",  "&get; &compress2rs; &put; dch; if -K 6; strash; dc2; balance"),
    ("resub4_compress", "resub -K 4; balance; &get; &compress2rs; &put; balance; rewrite -z; refactor -z; balance"),
    ("gia_resyn3_dch",  "&get; &resyn3; &put; dch; if -K 6; strash; dc2; balance"),
    ("resyn3rs_resub4", "&get; &resyn3rs; &put; balance; resub -K 4; balance; rewrite -z; refactor -z; balance"),
]

# ── helpers ────────────────────────────────────────────────────────────────────

def measure(p: str):
    r = subprocess.run([str(ABC), "-c", f"read_aiger {p}; ps"],
                       capture_output=True, text=True)
    o = r.stdout + r.stderr
    ma = re.search(r'and\s*=\s*(\d+)', o)
    md = re.search(r'lev\s*=\s*(\d+)', o)
    if ma and md:
        return int(ma.group(1)), int(md.group(1))
    return None, None

def verify(truth: str, aig: str):
    r = subprocess.run([str(ABC), "-c",
                        f"read_truth -xf {truth}; st; &get; &cec -t {aig}"],
                       capture_output=True, text=True)
    return "Networks are equivalent" in (r.stdout + r.stderr)

def try_one_flow(case, fname, fflow, seed: str, truth: str, cur_adp: int, tid: int):
    """Run one flow against seed. Returns (fname, area, delay, adp, cand_path) or None."""
    cand = str(TMP / case / f"{fname}_{tid}.aig")
    try:
        r = subprocess.run([str(ABC), "-c",
                            f"read_aiger {seed}; {fflow}; write_aiger -s {cand}"],
                           capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return None
    if not Path(cand).exists():
        return None
    ca, cd = measure(cand)
    if ca is None:
        return None
    cadp = ca * cd
    if cadp >= cur_adp:
        return None
    return (fname, ca, cd, cadp, cand)

def optimize_case(case: str, ref_adp: int, workers: int, timeout: int) -> dict:
    case_tmp = TMP / case
    case_tmp.mkdir(exist_ok=True)

    truth = str(case_tmp / f"{case}.truth")
    shutil.copy(str(BENCHMARKS / f"{case}.truth"), truth)

    work = str(case_tmp / "work.aig")
    shutil.copy(str(OUTPUT / f"{case}.aig"), work)

    sa, sd = measure(work)
    start_adp  = sa * sd
    best_adp   = start_adp
    best_area  = sa
    best_delay = sd
    improved_flows = []

    round_n = 0
    improved = True
    while improved:
        improved = False
        round_n += 1
        candidates = []   # (adp, fname, area, delay, cand_path)

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {
                ex.submit(try_one_flow, case, fn, ff, work, truth, best_adp, round_n * 1000 + i): (fn, ff)
                for i, (fn, ff) in enumerate(FLOWS)
            }
            for fut in as_completed(futs):
                res = fut.result()
                if res is None:
                    continue
                fn, ca, cd, cadp, cand_path = res
                candidates.append((cadp, fn, ca, cd, cand_path))

        # sort by ADP, verify best-first
        candidates.sort(key=lambda x: x[0])
        for cadp, fn, ca, cd, cand_path in candidates:
            if cadp >= best_adp:
                break
            if verify(truth, cand_path):
                best_adp   = cadp
                best_area  = ca
                best_delay = cd
                shutil.copy(cand_path, work)
                improved_flows.append(f"[r{round_n}] {fn}: area={ca} delay={cd} adp={cadp}")
                improved = True
                break   # restart with new best as seed

    return {
        "case":         case,
        "start_adp":    start_adp,
        "best_adp":     best_adp,
        "best_area":    best_area,
        "best_delay":   best_delay,
        "ref_adp":      ref_adp,
        "ratio":        best_adp / ref_adp,
        "flows":        improved_flows,
        "work":         work,
        "improved":     best_adp < start_adp,
        "beats_ref":    best_adp < ref_adp,
    }

# ── main ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-ratio", type=float, default=1.20,
                    help="Only target cases with ratio <= this value (default 1.20)")
    ap.add_argument("--workers",   type=int,   default=4,
                    help="Parallel ABC processes per case (default 4)")
    ap.add_argument("--case-workers", type=int, default=8,
                    help="How many cases to run in parallel (default 8)")
    ap.add_argument("--timeout",   type=int,   default=60,
                    help="(reserved) per-flow timeout seconds")
    ap.add_argument("--cases",     nargs="*",
                    help="Explicit list of cases to run (e.g. ex231 ex227)")
    args = ap.parse_args()

    # Load reference
    ref = {}
    with open(str(REF_CSV)) as f:
        for row in csv.DictReader(f):
            ref[row["case"]] = int(row["adp"])

    # Measure current output ADP — copy each AIG to /tmp first to avoid space-in-path
    current = {}
    for case in sorted(ref):
        aig = OUTPUT / f"{case}.aig"
        if not aig.exists():
            continue
        tmp_aig = str(TMP / f"measure_{case}.aig")
        shutil.copy(str(aig), tmp_aig)
        a, d = measure(tmp_aig)
        if a:
            current[case] = a * d

    # Select targets
    if args.cases:
        targets = {c: ref[c] for c in args.cases if c in ref and c in current}
    else:
        targets = {c: ref[c] for c in sorted(ref)
                   if c in current and 1.0 < current[c] / ref[c] <= args.max_ratio}

    print(f"Targeting {len(targets)} cases (ratio 1.0–{args.max_ratio}x, {args.workers} workers/case)")
    print(f"{'Case':<8} {'Start':>8} {'Best':>8} {'Ref':>8} {'Ratio':>7}  Flows used")
    print("─" * 75)

    results = []
    # Run cases in parallel (case_workers cases at a time, each with args.workers flow threads)
    case_list = sorted(targets.items(), key=lambda x: current[x[0]] / x[1])
    with ThreadPoolExecutor(max_workers=args.case_workers) as ex:
        futs = {ex.submit(optimize_case, case, ref_adp, args.workers, args.timeout): case
                for case, ref_adp in case_list}
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            marker = " ◄ BEATS" if r["beats_ref"] else ("" if not r["improved"] else " ↓")
            print(f"{r['case']:<8} {r['start_adp']:>8} {r['best_adp']:>8} {r['ref_adp']:>8} {r['ratio']:>7.4f}{marker}")
            for fl in r["flows"]:
                print(f"         {fl}")
            sys.stdout.flush()

    # Write improvements to output/
    print()
    written = []
    for r in results:
        if r["improved"]:
            dst = OUTPUT / f"{r['case']}.aig"
            shutil.copy(r["work"], str(dst))
            written.append(r["case"])
            print(f"  Updated output/{r['case']}.aig  adp {r['start_adp']} → {r['best_adp']}"
                  f"  (ref={r['ref_adp']}  ratio={r['ratio']:.4f})")

    if not written:
        print("  No improvements found.")

    print(f"\nDone. {len(written)} case(s) updated in output/")
    beats = [r["case"] for r in results if r["beats_ref"]]
    if beats:
        print(f"Cases now beating reference: {beats}")

if __name__ == "__main__":
    main()
