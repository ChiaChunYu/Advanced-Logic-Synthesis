#!/bin/bash
# Probe additional ABC commands (all bounded — no &rrr) on a few lagging cases.
cd "/mnt/c/Users/Chun_yu/Desktop/Github project/Advanced-Logic-Synthesis/Final_Project_AI-Based_AIG_Optimization"
ABC=./student/abc
andcount() { "$ABC" -c "read_aiger $1; ps" 2>/dev/null | grep -oiP 'and =\s*\K[0-9]+' | tail -1; }

for c in ex289 ex251 ex205 ex243; do
  A="output/${c}.aig"
  cur=$(andcount "$A")
  echo "==== $c (cur=$cur) ===="
  i=0
  for flow in \
    "&get; &mfs -W 6 -M 8000; &put; dc2; balance" \
    "dc2; lutpack -S 1; dc2; balance" \
    "&get; &mfs -L 4 -W 4; &put; balance" \
    "if -K 6; mfs2 -W 4; st; dc2; balance" \
    "&get; &dch -f; &mfs; &put; dc2; balance" \
    "dch; if -g -K 6; st; dc2; balance" ; do
    i=$((i+1)); out="/tmp/${c}_pm${i}.aig"
    timeout 90 "$ABC" -c "read_aiger $A; $flow; write_aiger -s $out" >/dev/null 2>&1
    if [ -f "$out" ]; then echo "  f$i: and=$(andcount "$out")  [$flow]"; rm -f "$out"
    else echo "  f$i: FAILED/timeout  [$flow]"; fi
  done
done
