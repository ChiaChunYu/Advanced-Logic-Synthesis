#!/bin/bash
# Very long &my_deepsyn on the largest cases — 1800s per (seed,cost), adopting
# only CEC-verified strict ADP improvements. Sequential so it does not oversubscribe
# while the xlong mid-ratio lines are running. Mirrors how ex242/ex243 broke
# through under long randomized search.
cd "/mnt/c/Users/Chun_yu/Desktop/Github project/Advanced-Logic-Synthesis/Final_Project_AI-Based_AIG_Optimization"
ABC=./student/abc

adp() { python3 -c "
import sys; from pathlib import Path; sys.path.insert(0,'student')
from abc_core import measure_adp
print(measure_adp(Path('student/abc'), Path('$1'), 60, Path('.').resolve())[2])
"; }

# Largest cases by ADP (the ones where even small ratio gains are big absolute wins)
for c in ex299 ex297 ex227 ex207 ex206 ex226 ex225 ex223 ex298 ex295 ex224 ex230 ex292 ex293 ex294 ex296 ex220 ex221 ex222 ex228; do
  T="benchmarks/${c}.truth"; A="output/${c}.aig"
  cur=$(adp "$A")
  echo "==== $c (cur ADP=$cur) ===="
  for seed in 0 42 7; do
    for cost in adp area; do
      P="/tmp/xlb_${c}_${seed}_${cost}"; rm -rf "$P"; mkdir -p "$P"
      timeout 1900 "$ABC" -c "read_aiger $A; &get; &my_deepsyn -T 1800 -S $seed -O $P -C $cost; &put" >/dev/null 2>&1
      for f in "$P"/*.aig; do
        [ -f "$f" ] || continue
        # equivalence + adp check, adopt if better
        python3 -c "
import sys, shutil; from pathlib import Path; sys.path.insert(0,'student')
from abc_core import is_equivalent, measure_adp
R=Path('.').resolve(); ABC=R/'student'/'abc'
cand=Path('$f'); out=R/'output'/'${c}.aig'
ca=measure_adp(ABC,cand,60,R)[2]; oa=measure_adp(ABC,out,60,R)[2]
if ca<oa and is_equivalent(ABC,R/'benchmarks'/'${c}.truth',cand,300,R):
    shutil.copyfile(cand,out)
    shutil.copyfile(cand,R/'best_output'/'${c}.aig')
    print('  ADOPTED ${c} seed$seed $cost: %d -> %d'%(oa,ca))
"
      done
      rm -rf "$P"
    done
  done
  echo "  $c final ADP=$(adp "$A")"
done
echo "=== xlong_big DONE ==="
