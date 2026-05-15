#!/bin/bash
mkdir -p logs

BENCHMARK_DIR="./benchmarks" 
CSV_FILE="abc_comparison.csv"

# Trap Ctrl+C (SIGINT) to terminate the entire script immediately
trap "echo -e '\nProcess interrupted by user. Exiting...'; exit 1" INT

# Original header without PI and PO
echo "Benchmark,Category,Base_Nodes,Base_Lev,Base_Time(s),Trad_Nodes,Trad_Lev,Trad_Time(s),Orch_Nodes,Orch_Lev,Orch_Time(s),PureSyn4_Nodes,PureSyn4_Lev,PureSyn4_Time(s),DchSyn4_Nodes,DchSyn4_Lev,DchSyn4_Time(s),DeepSyn_Nodes,DeepSyn_Lev,DeepSyn_Time(s)" > $CSV_FILE
echo "Start running FULL comparison with native ABC parameters..."

if ls $BENCHMARK_DIR/*/*.aig 1> /dev/null 2>&1; then
    for filepath in $BENCHMARK_DIR/*/*.aig; do
        
        filename=$(basename -- "$filepath")
        category=$(basename $(dirname "$filepath"))

        echo "----------------------------------------"
        echo "Processing: [$category] $filename"

        # ==========================================
        # 0. Baseline (Initial AIG conversion)
        # ==========================================
        start=$(date +%s.%N)
        ./abc/abc -c "read $filepath; strash; print_stats" > logs/${filename}_baseline.log
        end=$(date +%s.%N)
        b_time=$(awk "BEGIN {printf \"%.2f\", ${end} - ${start}}")
        
        b_nodes=$(grep "and =" logs/${filename}_baseline.log | tail -n 1 | sed 's/\x1b\[[0-9;]*m//g' | awk -F'and =' '{print $2}' | awk '{print $1}')
        b_levels=$(grep "lev =" logs/${filename}_baseline.log | tail -n 1 | sed 's/\x1b\[[0-9;]*m//g' | awk -F'lev =' '{print $2}' | awk '{print $1}')
        echo "  -> Baseline:    Time=${b_time}s, Nodes=$b_nodes, Levels=$b_levels"

        # ==========================================
        # 1. Traditional AIG Flow (Classic example)
        # ==========================================
        start=$(date +%s.%N)
        ./abc/abc -c "read $filepath; strash; rewrite; refactor; balance; rewrite; print_stats" > logs/${filename}_trad.log
        end=$(date +%s.%N)
        a_time=$(awk "BEGIN {printf \"%.2f\", ${end} - ${start}}")
        
        a_nodes=$(grep "and =" logs/${filename}_trad.log | tail -n 1 | sed 's/\x1b\[[0-9;]*m//g' | awk -F'and =' '{print $2}' | awk '{print $1}')
        a_levels=$(grep "lev =" logs/${filename}_trad.log | tail -n 1 | sed 's/\x1b\[[0-9;]*m//g' | awk -F'lev =' '{print $2}' | awk '{print $1}')
        echo "  -> Trad_AIG:    Time=${a_time}s, Nodes=$a_nodes, Levels=$a_levels"

        # ==========================================
        # 2. Orchestrate (Greedy algorithm)
        # ==========================================
        start=$(date +%s.%N)
        ./abc/abc -c "read $filepath; strash; orchestrate; print_stats" > logs/${filename}_orch.log
        end=$(date +%s.%N)
        o_time=$(awk "BEGIN {printf \"%.2f\", ${end} - ${start}}")
        
        o_nodes=$(grep "and =" logs/${filename}_orch.log | tail -n 1 | sed 's/\x1b\[[0-9;]*m//g' | awk -F'and =' '{print $2}' | awk '{print $1}')
        o_levels=$(grep "lev =" logs/${filename}_orch.log | tail -n 1 | sed 's/\x1b\[[0-9;]*m//g' | awk -F'lev =' '{print $2}' | awk '{print $1}')
        echo "  -> Orchestrate: Time=${o_time}s, Nodes=$o_nodes, Levels=$o_levels"

        # ==========================================
        # 3. ABC9 GIA Flow (Pure syn4 without dch)
        # ==========================================
        start=$(date +%s.%N)
        ./abc/abc -c "read $filepath; strash; &get; &syn4; &ps" > logs/${filename}_puresyn4.log
        end=$(date +%s.%N)
        ps_time=$(awk "BEGIN {printf \"%.2f\", ${end} - ${start}}")
        
        ps_nodes=$(grep "and =" logs/${filename}_puresyn4.log | tail -n 1 | sed 's/\x1b\[[0-9;]*m//g' | awk -F'and =' '{print $2}' | awk '{print $1}')
        ps_levels=$(grep "lev =" logs/${filename}_puresyn4.log | tail -n 1 | sed 's/\x1b\[[0-9;]*m//g' | awk -F'lev =' '{print $2}' | awk '{print $1}')
        echo "  -> Pure_Syn4:   Time=${ps_time}s, Nodes=$ps_nodes, Levels=$ps_levels"

        # ==========================================
        # 4. ABC9 GIA Flow (dch + syn4)
        # ==========================================
        start=$(date +%s.%N)
        ./abc/abc -c "read $filepath; strash; &get; &dch; &syn4; &ps" > logs/${filename}_dchsyn4.log
        end=$(date +%s.%N)
        ds_time=$(awk "BEGIN {printf \"%.2f\", ${end} - ${start}}")
        
        ds_nodes=$(grep "and =" logs/${filename}_dchsyn4.log | tail -n 1 | sed 's/\x1b\[[0-9;]*m//g' | awk -F'and =' '{print $2}' | awk '{print $1}')
        ds_levels=$(grep "lev =" logs/${filename}_dchsyn4.log | tail -n 1 | sed 's/\x1b\[[0-9;]*m//g' | awk -F'lev =' '{print $2}' | awk '{print $1}')
        echo "  -> Dch_Syn4:    Time=${ds_time}s, Nodes=$ds_nodes, Levels=$ds_levels"

        # ==========================================
        # 5. ABC9 GIA Flow (deepsyn) - Using native -J and -T parameters
        # ==========================================
        start=$(date +%s.%N)
        # -J 300: Stop if 300 iterations pass without improvement
        # -T 300: Stop after 300 seconds and keep the best result
        ./abc/abc -c "read $filepath; strash; &get; &deepsyn -J 300 -T 300; &ps" > logs/${filename}_deepsyn.log
        
        end=$(date +%s.%N)
        d_time=$(awk "BEGIN {printf \"%.2f\", ${end} - ${start}}")
        d_nodes=$(grep "and =" logs/${filename}_deepsyn.log | tail -n 1 | sed 's/\x1b\[[0-9;]*m//g' | awk -F'and =' '{print $2}' | awk '{print $1}')
        d_levels=$(grep "lev =" logs/${filename}_deepsyn.log | tail -n 1 | sed 's/\x1b\[[0-9;]*m//g' | awk -F'lev =' '{print $2}' | awk '{print $1}')
        echo "  -> DeepSyn:     Time=${d_time}s, Nodes=$d_nodes, Levels=$d_levels"

        # Write all variables to a single CSV row (exactly 20 columns)
        echo "$filename,$category,$b_nodes,$b_levels,$b_time,$a_nodes,$a_levels,$a_time,$o_nodes,$o_levels,$o_time,$ps_nodes,$ps_levels,$ps_time,$ds_nodes,$ds_levels,$ds_time,$d_nodes,$d_levels,$d_time" >> $CSV_FILE
        echo "   $filename saved."

    done
    echo "----------------------------------------"
    echo "All tests completed. Open $CSV_FILE in Excel."
else
    echo "Error: Cannot find any .aig files in subdirectories of $BENCHMARK_DIR"
fi