#!/bin/bash
PROJ="/mnt/c/Users/Chun_yu/Desktop/Github project/Advanced-Logic-Synthesis/Final_Project_AI-Based_AIG_Optimization"
MT="$PROJ/student/mockturtle_opt/mockturtle_opt"
ABC="$PROJ/student/abc"

for case in ex286 ex252 ex240; do
    TRUTH="$PROJ/benchmarks/${case}.truth"
    AIG="$PROJ/output/${case}.aig"
    echo "=== $case ==="
    base=$("$ABC" -c "read_aiger \"$AIG\"; ps" 2>/dev/null | grep -oP 'and\s*=\s*\K\d+')
    lev=$("$ABC" -c "read_aiger \"$AIG\"; ps" 2>/dev/null | grep -oP 'lev\s*=\s*\K\d+')
    echo "  baseline: and=$base lev=$lev ADP=$(echo "$base * $lev" | bc)"

    for mode in aig_resub functional_reduction xag_xor_heavy mig_majority dc_aig_rewrite cut4_aig_xag_npn xag_area_minmc mig_akers_cut4; do
        OUT="/tmp/${case}_${mode}.aig"
        "$MT" --input-truth "$TRUTH" --input-aig "$AIG" --output-aig "$OUT" --mode "$mode" 2>/dev/null
        if [ -f "$OUT" ]; then
            stats=$("$ABC" -c "read_aiger \"$OUT\"; ps" 2>/dev/null | grep 'and')
            echo "  $mode: $stats"
        else
            echo "  $mode: no output"
        fi
    done
done
