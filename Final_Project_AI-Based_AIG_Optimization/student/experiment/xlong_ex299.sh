#!/bin/bash
# Dedicated multi-hour &my_deepsyn on ex299 (largest case, 60% of total deficit).
# Runs several seeds back-to-back, each for ~2 hours, adopting only CEC-verified
# strict ADP improvements. Mirrors how ex242/ex243 broke through under long search.
cd "/mnt/c/Users/Chun_yu/Desktop/Github project/Advanced-Logic-Synthesis/Final_Project_AI-Based_AIG_Optimization"
ABC=./student/abc
C=ex299
A="output/${C}.aig"

adp() { python3 -c "
import sys; from pathlib import Path; sys.path.insert(0,'student')
from abc_core import measure_adp
print(measure_adp(Path('student/abc'), Path('$1'), 120, Path('.').resolve())[2])
"; }

echo "ex299 start ADP=$(adp "$A")  $(date)"

for seed in 0 42 7 123 777; do
  for cost in adp area; do
    P="/tmp/x299_${seed}_${cost}"; rm -rf "$P"; mkdir -p "$P"
    echo ">>> seed=$seed cost=$cost 7200s  $(date)"
    timeout 7300 "$ABC" -c "read_aiger $A; &get; &my_deepsyn -T 7200 -S $seed -O $P -C $cost; &put" >/dev/null 2>&1
    for f in "$P"/*.aig; do
      [ -f "$f" ] || continue
      python3 -c "
import sys, shutil; from pathlib import Path; sys.path.insert(0,'student')
from abc_core import is_equivalent, measure_adp
R=Path('.').resolve(); ABC=R/'student'/'abc'
cand=Path('$f'); out=R/'output'/'${C}.aig'
ca=measure_adp(ABC,cand,120,R)[2]; oa=measure_adp(ABC,out,120,R)[2]
if ca<oa and is_equivalent(ABC,R/'benchmarks'/'${C}.truth',cand,600,R):
    shutil.copyfile(cand,out); shutil.copyfile(cand,R/'best_output'/'${C}.aig')
    print('  ADOPTED ${C} seed$seed $cost: %d -> %d'%(oa,ca))
"
    done
    rm -rf "$P"
    echo "  ex299 current ADP=$(adp "$A")  $(date)"
  done
done
echo "=== ex299 dedicated run DONE  $(date) ==="
