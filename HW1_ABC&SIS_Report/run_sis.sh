#!/bin/bash
mkdir -p logs

BENCHMARK_DIR="./benchmarks" 
SIS_LIB="sis-1.3.6-bin/share/sis/sis_lib"
CSV_FILE="sis_comparison.csv"

# Trap Ctrl+C (SIGINT) to terminate the entire script immediately
trap "echo -e '\nProcess interrupted by user. Exiting...'; exit 1" INT

# Initialize CSV Header
echo "Benchmark,Category,Base_SIS_Nodes,Base_AIG_Nodes,Base_AIG_Lev,Alg_SIS_Nodes,Alg_AIG_Nodes,Alg_AIG_Lev,Alg_Time(s),Bool_SIS_Nodes,Bool_AIG_Nodes,Bool_AIG_Lev,Bool_Time(s),Rug_SIS_Nodes,Rug_AIG_Nodes,Rug_AIG_Lev,Rug_Time(s)" > $CSV_FILE
echo "Start running FULL SIS comparison with robust data extraction..."

if ls $BENCHMARK_DIR/*/*.blif 1> /dev/null 2>&1; then
    for filepath in $BENCHMARK_DIR/*/*.blif; do

# if ls $BENCHMARK_DIR/random_control/*.blif 1> /dev/null 2>&1; then
#   for filepath in $BENCHMARK_DIR/random_control/*.blif; do
        
        filename=$(basename -- "$filepath")
        base="${filename%.blif}"
        category=$(basename $(dirname "$filepath"))

        echo "----------------------------------------"
        echo "Processing: [$category] $filename"

        # ==========================================
        # 0. Baseline (Initial SIS and AIG stats)
        # ==========================================
        base_sis_log="logs/${base}_base_sis.log"
        ./sis-1.3.6-bin/bin/sis -x -c "read_blif $filepath; print_stats; quit" > $base_sis_log 2>/dev/null
        base_sis_n=$(sed 's/ //g' $base_sis_log | grep -o "nodes=[0-9]*" | cut -d'=' -f2 | tail -n 1)
        
        quick_check_log="logs/${base}_quick_check.log"
        ./abc/abc -c "read_blif $filepath; strash; print_stats" > $quick_check_log 2>/dev/null
        base_aig=$(sed 's/\x1b\[[0-9;]*m//g' $quick_check_log | grep -o 'and *= *[0-9]*' | cut -d'=' -f2 | tr -d ' ' | tail -n 1)
        base_lev=$(sed 's/\x1b\[[0-9;]*m//g' $quick_check_log | grep -o 'lev *= *[0-9]*' | cut -d'=' -f2 | tr -d ' ' | tail -n 1)
        
        # if [ -n "$base_aig" ] && [ "$base_aig" -ge 5000 ]; then
        #     echo "  -> Skipping:    $filename (AIG Nodes=$base_aig >= 5000)"
        #     continue 
        # fi
        
        [ -z "$base_sis_n" ] && base_sis_n="N/A"
        [ -z "$base_aig" ] && base_aig="N/A"
        [ -z "$base_lev" ] && base_lev="N/A"
        
        echo "  -> Baseline:    SIS_Nodes=$base_sis_n, AIG_Nodes=$base_aig, Lev=$base_lev"

        # ==========================================
        # 1. Algebraic Flow (script.algebraic)
        # ==========================================
        start_alg=$(date +%s.%N)
        ./sis-1.3.6-bin/bin/sis -x -c "read_blif $filepath; source $SIS_LIB/script.algebraic; print_stats; write_blif logs/${base}_alg.blif; quit" > logs/${base}_alg.log
        end_alg=$(date +%s.%N)
        alg_time=$(awk "BEGIN {printf \"%.2f\", ${end_alg} - ${start_alg}}")
        alg_n=$(sed 's/ //g' logs/${base}_alg.log | grep -o "nodes=[0-9]*" | cut -d'=' -f2 | tail -n 1)
        
        ./abc/abc -c "read_blif logs/${base}_alg.blif; strash; print_stats" > logs/${base}_alg_abc.log 2>/dev/null
        alg_aig=$(sed 's/\x1b\[[0-9;]*m//g' logs/${base}_alg_abc.log | grep -o 'and *= *[0-9]*' | cut -d'=' -f2 | tr -d ' ' | tail -n 1)
        alg_lev=$(sed 's/\x1b\[[0-9;]*m//g' logs/${base}_alg_abc.log | grep -o 'lev *= *[0-9]*' | cut -d'=' -f2 | tr -d ' ' | tail -n 1)

        [ -z "$alg_n" ] && alg_n="N/A"
        [ -z "$alg_aig" ] && alg_aig="N/A"
        [ -z "$alg_lev" ] && alg_lev="N/A"
        
        echo "  -> Algebraic:   Time=${alg_time}s, SIS_Nodes=$alg_n, AIG_Nodes=$alg_aig, Lev=$alg_lev"

        # ==========================================
        # 2. Boolean Flow (script.boolean)
        # ==========================================
        start_bool=$(date +%s.%N)
        ./sis-1.3.6-bin/bin/sis -x -c "read_blif $filepath; source $SIS_LIB/script.boolean; print_stats; write_blif logs/${base}_bool.blif; quit" > logs/${base}_bool.log
        end_bool=$(date +%s.%N)
        bool_time=$(awk "BEGIN {printf \"%.2f\", ${end_bool} - ${start_bool}}")
        bool_n=$(sed 's/ //g' logs/${base}_bool.log | grep -o "nodes=[0-9]*" | cut -d'=' -f2 | tail -n 1)
        
        ./abc/abc -c "read_blif logs/${base}_bool.blif; strash; print_stats" > logs/${base}_bool_abc.log 2>/dev/null
        bool_aig=$(sed 's/\x1b\[[0-9;]*m//g' logs/${base}_bool_abc.log | grep -o 'and *= *[0-9]*' | cut -d'=' -f2 | tr -d ' ' | tail -n 1)
        bool_lev=$(sed 's/\x1b\[[0-9;]*m//g' logs/${base}_bool_abc.log | grep -o 'lev *= *[0-9]*' | cut -d'=' -f2 | tr -d ' ' | tail -n 1)
        
        [ -z "$bool_n" ] && bool_n="N/A"
        [ -z "$bool_aig" ] && bool_aig="N/A"
        [ -z "$bool_lev" ] && bool_lev="N/A"
        
        echo "  -> Boolean:     Time=${bool_time}s, SIS_Nodes=$bool_n, AIG_Nodes=$bool_aig, Lev=$bool_lev"

        # ==========================================
        # 3. Rugged Flow (script.rugged)
        # ==========================================
        start_rug=$(date +%s.%N)
        ./sis-1.3.6-bin/bin/sis -x -c "read_blif $filepath; source $SIS_LIB/script.rugged; print_stats; write_blif logs/${base}_rug.blif; quit" > logs/${base}_rug.log
        end_rug=$(date +%s.%N)
        rug_time=$(awk "BEGIN {printf \"%.2f\", ${end_rug} - ${start_rug}}")
        rug_n=$(sed 's/ //g' logs/${base}_rug.log | grep -o "nodes=[0-9]*" | cut -d'=' -f2 | tail -n 1)
        
        ./abc/abc -c "read_blif logs/${base}_rug.blif; strash; print_stats" > logs/${base}_rug_abc.log 2>/dev/null
        rug_aig=$(sed 's/\x1b\[[0-9;]*m//g' logs/${base}_rug_abc.log | grep -o 'and *= *[0-9]*' | cut -d'=' -f2 | tr -d ' ' | tail -n 1)
        rug_lev=$(sed 's/\x1b\[[0-9;]*m//g' logs/${base}_rug_abc.log | grep -o 'lev *= *[0-9]*' | cut -d'=' -f2 | tr -d ' ' | tail -n 1)
        
        [ -z "$rug_n" ] && rug_n="N/A"
        [ -z "$rug_aig" ] && rug_aig="N/A"
        [ -z "$rug_lev" ] && rug_lev="N/A"
        
        echo "  -> Rugged:      Time=${rug_time}s, SIS_Nodes=$rug_n, AIG_Nodes=$rug_aig, Lev=$rug_lev"

        # Write results to CSV
        echo "$filename,$category,$base_sis_n,$base_aig,$base_lev,$alg_n,$alg_aig,$alg_lev,$alg_time,$bool_n,$bool_aig,$bool_lev,$bool_time,$rug_n,$rug_aig,$rug_lev,$rug_time" >> $CSV_FILE
        echo "   $filename saved."

    done
    echo "----------------------------------------"
    echo "All tests completed. Open $CSV_FILE in Excel."
fi