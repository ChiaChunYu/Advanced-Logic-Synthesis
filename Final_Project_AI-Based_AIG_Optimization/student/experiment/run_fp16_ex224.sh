#!/bin/bash
# One-shot: build the ex224 fp16-log2 RTL AIG and run a long deepsyn search.
set -e
cd "/mnt/c/Users/Chun_yu/Desktop/Github project/Advanced-Logic-Synthesis/Final_Project_AI-Based_AIG_Optimization"
D=/tmp/fp16work
rm -rf "$D"
mkdir -p "$D/pareto"

python3 -c 'import sys; sys.path.insert(0,"student"); sys.path.insert(0,"student/experiment"); from fp16_synth import verilog_fp16_log2; open("/tmp/fp16work/ex224.v","w").write(verilog_fp16_log2())'

yosys -q -p "read_verilog $D/ex224.v; hierarchy -top top; proc; memory; flatten; opt; techmap; opt; write_blif $D/ex224.blif"
./student/abc -c "read_blif $D/ex224.blif; strash; dc2; dc2; balance; write_aiger -s $D/ex224.aig" >/dev/null
echo "AIG ready"

timeout 350 ./student/abc -c "read_aiger $D/ex224.aig; &get; &my_deepsyn -T 300 -S 0 -O $D/pareto -C adp; &put" 2>&1 | tail -1

python3 -c '
import sys; from pathlib import Path; sys.path.insert(0,"student")
from abc_core import measure_adp, is_equivalent
R=Path(".").resolve()
best=10**18; bestf=None
for f in sorted(Path("/tmp/fp16work/pareto").glob("*.aig")):
    a,d,adp=measure_adp(R/"student"/"abc",f,60,R)
    if adp<best: best=adp; bestf=f
if bestf:
    eq=is_equivalent(R/"student"/"abc", R/"benchmarks"/"ex224.truth", bestf, 240, R)
    print(f"BEST deepsyn ADP={best} equivalent={eq} (current 103598)")
    if eq and best<103598:
        import shutil; shutil.copyfile(bestf, R/"output"/"ex224.aig")
        print("ADOPTED into output/ex224.aig")
'
