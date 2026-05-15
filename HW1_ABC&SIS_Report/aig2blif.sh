#!/bin/bash

BENCHMARK_DIR="./benchmarks"

echo "Start converting AIG files to BLIF format..."

if ls $BENCHMARK_DIR/*/*.aig 1> /dev/null 2>&1; then
    for filepath in $BENCHMARK_DIR/*/*.aig; do
        
        # Extract the file path without the .aig extension
        basepath="${filepath%.aig}"
        blifpath="${basepath}.blif"
        
        echo "Converting: $filepath -> $blifpath"
        
        # Use ABC to read the AIG and write it out as a BLIF file
        ./abc/abc -c "read $filepath; write_blif $blifpath"

    done
    echo "----------------------------------------"
    echo "All conversions completed successfully."
else
    echo "Error: Cannot find any .aig files in subdirectories of $BENCHMARK_DIR"
fi