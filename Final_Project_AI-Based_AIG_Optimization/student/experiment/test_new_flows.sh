#!/bin/bash
# Probe new ABC restructuring commands on a few lagging cases to see which
# produce a valid, smaller AIG before adding them to optimize.py's flow list.
cd "/mnt/c/Users/Chun_yu/Desktop/Github project/Advanced-Logic-Synthesis/Final_Project_AI-Based_AIG_Optimization"
ABC=./student/abc

andcount() { "$ABC" -c "read_aiger $1; ps" 2>/dev/null | grep -oiP 'and =\s*\K[0-9]+' | tail -1; }

for c in ex289 ex248 ex205 ex251; do
  A="output/${c}.aig"
  cur=$(andcount "$A")
  echo "================ $c (current and=$cur) ================"
  i=0
  for flow in \
    "dc2; &get; &mfs; &put; balance" \
    "&get; &rrr; &put; dc2; balance" \
    "&get; &dch; &mfs -W 4; &put; balance" \
    "&get; &deepsyn -I 4; &put; dc2; balance" \
    "&get; &sopb -C 16; &put; dc2; balance" \
    "resub -K 12 -N 3; dc2; balance" \
    "&get; &b -d; &put; dc2; balance" ; do
    i=$((i+1))
    out="/tmp/${c}_nf${i}.aig"
    "$ABC" -c "read_aiger $A; $flow; write_aiger -s $out" >/dev/null 2>&1
    if [ -f "$out" ]; then
      a=$(andcount "$out")
      echo "  flow$i ($flow): and=$a"
      rm -f "$out"
    else
      echo "  flow$i ($flow): FAILED"
    fi
  done
done
