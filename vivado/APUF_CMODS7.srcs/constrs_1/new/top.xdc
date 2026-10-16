# 12 MHz System Clock
set_property -dict {PACKAGE_PIN M9 IOSTANDARD LVCMOS33} [get_ports clk]
create_clock -period 83.330 -name sys_clk_pin -waveform {0.000 41.660} -add [get_ports clk]

set_property CFGBVS VCCO [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]

set_property -dict {PACKAGE_PIN D1 IOSTANDARD LVCMOS33} [get_ports rst]

set_property -dict {PACKAGE_PIN L12 IOSTANDARD LVCMOS33} [get_ports uart_tx_o]
set_property -dict {PACKAGE_PIN K15 IOSTANDARD LVCMOS33} [get_ports uart_rx_i]

set_property -dict { PACKAGE_PIN E2 IOSTANDARD LVCMOS33 } [get_ports { led_control[0] }]
set_property -dict { PACKAGE_PIN K1 IOSTANDARD LVCMOS33 } [get_ports { led_control[1] }]
set_property -dict { PACKAGE_PIN J1 IOSTANDARD LVCMOS33 } [get_ports { led_control[2] }]
set_property -dict { PACKAGE_PIN E1 IOSTANDARD LVCMOS33 } [get_ports { led_control[3] }]

set_property DONT_TOUCH true [get_cells puf0/*]

# Ensure the delay paths use the exact same LUT pins across all stages
# I0 = Path A, I1 = Path B, I2 = Challenge Bit
# set_property LOCK_PINS {I0:A1 I1:A2 I2:A3} [get_cells puf0/STAGE[*].upper_mux]
# set_property LOCK_PINS {I0:A1 I1:A2 I2:A3} [get_cells puf0/STAGE[*].lower_mux]

# Force the UART modules away from the left-side PUF windows.
create_pblock uart_block
add_cells_to_pblock [get_pblocks uart_block] [get_cells rx0]
add_cells_to_pblock [get_pblocks uart_block] [get_cells tx0]
resize_pblock [get_pblocks uart_block] -add {SLICE_X17Y10:SLICE_X20Y45}
