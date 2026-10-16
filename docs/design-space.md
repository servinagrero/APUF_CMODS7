# Design-space exploration

The final implementation keeps the additive-delay structure of a classical
APUF. Each of the 64 stages uses two LUT3 multiplexers. The upper and lower
LUTs use `INIT=8'hCA` and `INIT=8'hAC`; their inputs are locked to `A6`, `A5`,
and `A1`. A cross-coupled LUT2 NAND latch acts as the arbiter.

Early experiments considered longer chains, snake-shaped placements, all four
clock regions, PDL-assisted designs, alternative traversal directions, BEL
orders, column gaps, row offsets, and balanced pin assignments. Chains longer
than 64 stages were dropped because turns complicated the physical structure.
PDLs were not retained because the non-PDL implementation provided adequate
behavior with a simpler HDL and communication protocol. Pin balancing did not
provide a consistent empirical improvement.

The exploration then placed two chains in each left clock region and varied
their physical traversal while preserving logical stage order and the same
challenge for every chain. The right regions were excluded from the final
configuration after region-dependent behavior was observed. These observations
motivate the search but do not establish routing as its cause.

`decor_left2_g1_o0` was selected empirically. It uses offsets 5 and 22 in each
left region. Traversal direction, row direction, and BEL order differ between
the four chains (`dcba`, `abcd`, `badc`, and `cdab`). Pblocks confine each PUF
to its selected two-column window, while the UART is placed separately.

The repository keeps the final generator as the supported implementation.
Generated XDC files, routed checkpoints, and `puf_routes.csv` contain the exact
BEL, pin, and routing details needed to reproduce or inspect a build.
