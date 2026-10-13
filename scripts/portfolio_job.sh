#!/usr/bin/env bash
#SBATCH --partition=C64M256G
#SBATCH --cpus-per-task=16
#SBATCH --time=01:10:00
#SBATCH --job-name=cfd_portfolio
set -eu
CODE=$1
EXPERIMENT=$2
CASE=$3
PYTHON=$4
export PYTHONPATH="$CODE"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
exec "$PYTHON" "$CODE/scripts/portfolio_episode.py" "$EXPERIMENT" "$CASE"
