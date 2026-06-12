#!/bin/bash
# Try ABC structural decompositions (DSD, satclp/collapse, &if -y) on the hard
# cases to expose a decomposition the manual function-guessing missed.
cd "/mnt/c/Users/Chun_yu/Desktop/Github project/Advanced-Logic-Synthesis/Final_Project_AI-Based_AIG_Optimization"
ABC=./student/abc

for c in ex286 ex252 ex250 ex297 ex299; do
  T="benchmarks/${c}.truth"
  A="output/${c}.aig"
  echo "================ $c ================"
  echo "-- current AIG stats --"
  "$ABC" -c "read_aiger $A; ps" 2>/dev/null | grep -i and | tail -1

  echo "-- &dsd (disjoint support decomposition) --"
  "$ABC" -c "read_aiger $A; &get; &dsd -v" 2>&1 | tail -4

  echo "-- collapse to BDD then ps (shared structure size) --"
  "$ABC" -c "read_aiger $A; collapse; ps" 2>&1 | tail -2

  echo "-- &if -y (LUT structure probe, K=6) --"
  "$ABC" -c "read_aiger $A; &get; &if -K 6 -y; &put; ps" 2>&1 | grep -i "nd =" | tail -1
done
