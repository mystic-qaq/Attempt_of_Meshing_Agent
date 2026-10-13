#!/usr/bin/env bash
# Run on a network-capable Slurm login node. Secrets stay in a private key file.
set -eu
CODE=$1
EXPERIMENT=$2
PYTHON=$3
KEY_FILE=$4
export PYTHONPATH="$CODE"
for CASE in ahmed_public_25 finite_wing finite_cylinder submerged_spheroid; do
    nohup "$PYTHON" -m cfdmesh.cli serve-advisor "$EXPERIMENT/runs/$CASE" \
        --key-file "$KEY_FILE" --max-calls 24 --usd-limit .5 --case-usd-limit .5 \
        --seconds 4400 --max-turns 4 --max-output 12288 --reasoning-effort high \
        > "$EXPERIMENT/logs/advisor_$CASE.log" 2>&1 < /dev/null &
    echo "$!" > "$EXPERIMENT/logs/advisor_$CASE.pid"
    sbatch --parsable --output="$EXPERIMENT/logs/${CASE}_%j.log" \
        "$CODE/scripts/portfolio_job.sh" "$CODE" "$EXPERIMENT" "$CASE" "$PYTHON"
done
