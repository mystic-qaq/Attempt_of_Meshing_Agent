#!/usr/bin/env bash
#SBATCH --partition=C64M256G
#SBATCH --cpus-per-task=4
#SBATCH --time=00:15:00
#SBATCH --job-name=cfd_portfolio_report
set -eu
CODE=$1
EXPERIMENT=$2
PYTHON=$3
export PYTHONPATH="$CODE"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
OUT="$EXPERIMENT/portfolio_results"
"$PYTHON" "$CODE/scripts/portfolio_report.py" "$EXPERIMENT" "$OUT"
"$PYTHON" "$CODE/scripts/portfolio_visualize.py" "$OUT/results.json" "$OUT/assets"
if [ -f "$EXPERIMENT/proposal_followup_result.json" ]; then
    "$PYTHON" "$CODE/scripts/portfolio_supplement_report.py" "$EXPERIMENT" "$OUT"
    "$PYTHON" "$CODE/scripts/portfolio_visualize.py" "$OUT/separate_results.json" "$OUT/separate_assets"
fi
"$PYTHON" "$CODE/scripts/portfolio_publish_evidence.py" "$EXPERIMENT" "$OUT" "$OUT/public_benchmarks"
echo 'All evidence and actual native figures finalised.'
