#!/usr/bin/bash
#
# This script generates the bitstreams of the all pairs of SLICES and STAGES
# If a contraint file does not exist (e.g. the design is to big to fit in a slice) that bitstream is skipped

set -eu

VIVADO_DIR="$HOME/opt/Xilinx/Vivado/2019.2"
source "${VIVADO_DIR}/settings64.sh"
VIVADO_BIN="${VIVADO_DIR}/bin/vivado"

SLICES=("LEFT-LOWER-0" "LEFT-LOWER-1" "LEFT-UPPER-0" "LEFT-UPPER-1")
# STAGES=(16 32 48 64)
STAGES=(64)
PLACEMENTS=${PLACEMENTS:-"rl_dcba_left2:1:0 decor_left2:1:0"}

for slice in ${SLICES[@]}; do
  for stage in ${STAGES[@]}; do
    for placement in ${PLACEMENTS}; do
      IFS=: read -r variant gap offset <<< "$placement"
      placement_id="${variant}_g${gap}_o${offset}"
      file="constraints/placement_${slice}_${stage}_${placement_id}.xdc"
      if [[ -f $file ]]; then
        $VIVADO_BIN -mode batch -source scripts/build.tcl -tclargs $stage $slice $variant $gap $offset
      else
        echo "**************************************"
        echo "Constraint file ${file} does not exist"
        echo "**************************************"
      fi
    done
  done
done
