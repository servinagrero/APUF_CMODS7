# APUF CMOD S7

This repository implements and acquires responses from non-PDL, 64-stage
Arbiter PUFs on the Digilent Cmod S7 (`xc7s25csga225-1`).

The supported `decor_left2_g1_o0` design contains four logical chains:
`LEFT-LOWER-0`, `LEFT-LOWER-1`, `LEFT-UPPER-0`, and `LEFT-UPPER-1`.
All chains receive the same challenge without permutation.

See [FPGA workflow](fpga-workflow.md) to build bitstreams and collect CRPs.
See [Design exploration](design-space.md) for the experimental decisions
that led to the supported placement.
