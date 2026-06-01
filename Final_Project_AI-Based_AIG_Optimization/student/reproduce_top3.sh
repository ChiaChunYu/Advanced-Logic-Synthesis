#!/usr/bin/env bash
# Reproduce ex272, ex276, ex280 (the 3 cases that beat the reference ADP).
# Results go to output_top3/  -- original output/ is never touched.
# Usage: bash student/reproduce_top3.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ABC="$ROOT/student/abc"
BENCHMARKS="$ROOT/benchmarks"
OUTDIR="$ROOT/output_top3"

# Use /tmp to avoid space-in-path issues with ABC's internal command parser
TMPDIR="/tmp/reproduce_top3"
mkdir -p "$OUTDIR" "$TMPDIR"

# ── helpers ────────────────────────────────────────────────────────────────────

abc_ps() {        # abc_ps <aig>  → "area delay" on stdout
    local f="$1"
    local out
    out=$("$ABC" -c "read_aiger $f; ps" 2>&1)
    local area delay
    area=$(printf '%s' "$out" | grep -oP 'and\s*=\s*\K[0-9]+' | head -1)
    delay=$(printf '%s' "$out" | grep -oP 'lev\s*=\s*\K[0-9]+' | head -1)
    printf '%s %s' "$area" "$delay"
}

abc_verify() {    # abc_verify <truth> <aig>  → 0 if equivalent
    local truth="$1" aig="$2"
    "$ABC" -c "read_truth -xf $truth; st; &get; &cec -t $aig" 2>&1 | grep -q "Networks are equivalent"
}

abc_run() {       # abc_run <commands> <in_aig> <out_aig>
    local cmds="$1" in_f="$2" out_f="$3"
    "$ABC" -c "read_aiger $in_f; $cmds; write_aiger -s $out_f" >/dev/null 2>&1
}

# ── per-case reproduction ──────────────────────────────────────────────────────

reproduce_case() {
    local CASE="$1"
    local SEED_AIG="$ROOT/output/${CASE}.aig"   # never modified
    local OUT_AIG="$OUTDIR/${CASE}.aig"
    local TMP="$TMPDIR/${CASE}"
    mkdir -p "$TMP"
    # Copy truth to /tmp so ABC never sees a space in the path
    local TRUTH="$TMP/${CASE}.truth"
    cp "$BENCHMARKS/${CASE}.truth" "$TRUTH"

    echo ""
    echo "═══════════════════════════════════════════"
    echo "  Reproducing $CASE"
    echo "═══════════════════════════════════════════"

    # Work copy in /tmp (no spaces)
    local WORK="$TMP/work.aig"
    cp "$SEED_AIG" "$WORK"

    local seed_info
    seed_info=$(abc_ps "$WORK")
    local best_area best_delay
    best_area="${seed_info% *}"
    best_delay="${seed_info#* }"
    local best_adp=$(( best_area * best_delay ))
    echo "  Seed:  area=$best_area  delay=$best_delay  adp=$best_adp"

    # ── candidate list ─────────────────────────────────────────────────────────
    # Format: "label|abc_commands"
    # Each flow is applied to the current work AIG.
    # Accepted only if equivalent AND strictly lower ADP.

    declare -a CANDIDATES=()

    if [[ "$CASE" == "ex272" ]]; then
        # Key method: micro_resub4  (resub -K 4 + standard cleanup, iterated)
        # Logs showed two consecutive improvements: 11875→10545→10526
        # We run progressively more iterations and let the best-tracking select.
        local R="resub -K 4; balance; rewrite -z; refactor -z; balance"
        CANDIDATES=(
            "r4x1|$R"
            "r4x2|$R; $R"
            "r4x3|$R; $R; $R"
            "r4x4|$R; $R; $R; $R"
            "r4x5|$R; $R; $R; $R; $R"
            "r4x6|$R; $R; $R; $R; $R; $R"
            "r4x8|$R; $R; $R; $R; $R; $R; $R; $R"
        )

    elif [[ "$CASE" == "ex276" ]]; then
        # Key method: GIA canonical normalisation  (&get; &put; strash; dc2; balance)
        # Drove area 115→74, delay 10→8, adp 1150→592
        CANDIDATES=(
            "gia_can|&get; &put; strash; dc2; balance"
            "gia_can_x2|&get; &put; strash; dc2; balance; &get; &put; strash; dc2; balance"
            "gia_can_rw|&get; &put; strash; dc2; rewrite -z; refactor -z; balance"
            "gia_can_micro|&get; &put; strash; dc2; balance; resub -K 4; balance; rewrite -z; refactor -z; balance"
            "strash_dc2|strash; dc2; balance"
        )

    elif [[ "$CASE" == "ex280" ]]; then
        # Key method: mockturtle cut4_aig_xag_npn reduced the network to
        # area=167, delay=14, adp=2338.  The seed AIG already holds that result.
        # These ABC flows attempt further refinement from the seed.
        CANDIDATES=(
            "rw_rf_dc2|rewrite -z; refactor -z; dc2; balance"
            "dc2_rw_rf|dc2; rewrite -z; refactor -z; balance"
            "strash_dc2|strash; dc2; balance"
            "bal_rw_rf|balance; rewrite -z; refactor -z; dc2; balance"
            "resub4|resub -K 4; balance; rewrite -z; refactor -z; balance"
            "gia_can|&get; &put; strash; dc2; balance"
        )
    fi

    # ── try each candidate ─────────────────────────────────────────────────────
    for entry in "${CANDIDATES[@]}"; do
        local label="${entry%%|*}"
        local cmds="${entry#*|}"
        local CAND="$TMP/${label}.aig"

        abc_run "$cmds" "$WORK" "$CAND" || { echo "  error [$label]: abc failed"; continue; }
        [[ -f "$CAND" ]] || { echo "  error [$label]: no output file"; continue; }

        local info
        info=$(abc_ps "$CAND")
        local c_area c_delay
        c_area="${info% *}"
        c_delay="${info#* }"
        local c_adp=$(( c_area * c_delay ))

        if (( c_adp < best_adp )); then
            if abc_verify "$TRUTH" "$CAND"; then
                echo "  IMPROVED [$label]: area=$c_area  delay=$c_delay  adp=$c_adp  (was $best_adp)"
                cp "$CAND" "$WORK"
                best_area=$c_area
                best_delay=$c_delay
                best_adp=$c_adp
            else
                echo "  skip [$label]: adp=$c_adp but not equivalent"
            fi
        else
            echo "  skip [$label]: adp=$c_adp  (no improvement over $best_adp)"
        fi
    done

    # ── write result ──────────────────────────────────────────────────────────
    cp "$WORK" "$OUT_AIG"

    local REF_ADP
    case "$CASE" in
        ex272) REF_ADP=10880 ;;
        ex276) REF_ADP=632   ;;
        ex280) REF_ADP=2415  ;;
    esac
    local ratio
    ratio=$(awk "BEGIN{printf \"%.4f\", $best_adp/$REF_ADP}")
    local verdict
    verdict=$(awk "BEGIN{print ($best_adp < $REF_ADP) ? \"BEATS reference\" : \"within reference\"}")

    echo ""
    echo "  Final:  area=$best_area  delay=$best_delay  adp=$best_adp"
    echo "  Reference ADP: $REF_ADP   ratio=$ratio   $verdict"
    echo "  Written: $OUT_AIG"
}

# ── main ───────────────────────────────────────────────────────────────────────

echo "output_top3/ will hold reproduced AIGs."
echo "output/      is read-only (seed only, never written)."

for CASE in ex272 ex276 ex280; do
    reproduce_case "$CASE"
done

echo ""
echo "═══════════════════════════════════════════"
echo "  Final verification"
echo "═══════════════════════════════════════════"
echo ""

for CASE in ex272 ex276 ex280; do
    # Copy both files to /tmp to avoid spaces-in-path issues with ABC
    TRUTH_TMP="/tmp/top3_${CASE}.truth"
    AIG_TMP="/tmp/top3_${CASE}.aig"
    cp "$BENCHMARKS/${CASE}.truth" "$TRUTH_TMP"
    cp "$OUTDIR/${CASE}.aig" "$AIG_TMP"
    info=$(abc_ps "$AIG_TMP")
    area="${info% *}"
    delay="${info#* }"
    adp=$(( area * delay ))
    if abc_verify "$TRUTH_TMP" "$AIG_TMP"; then
        equiv="OK"
    else
        equiv="FAIL"
    fi
    rm -f "$AIG_TMP" "$TRUTH_TMP"
    case "$CASE" in
        ex272) ref=10880 ;;
        ex276) ref=632   ;;
        ex280) ref=2415  ;;
    esac
    ratio=$(awk "BEGIN{printf \"%.4f\", $adp/$ref}")
    printf "  %-8s  %-4s  area=%-6s  delay=%-3s  adp=%-7s  ratio=%s\n" \
        "$CASE" "$equiv" "$area" "$delay" "$adp" "$ratio"
done

echo ""
echo "Done.  output/ unchanged."
