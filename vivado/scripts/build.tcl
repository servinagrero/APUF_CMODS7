# Build script to automatically generate the bitstream for a pair of SLICE and STAGES
# The final bitstream is generated in build/${placement_id}/${slice_name}_${stages}/top.bit
#
# Run the script using
#   vivado -mode batch -source scripts/build.tcl -tclargs 64 LEFT-UPPER rl_dcba 1 8

set stages [lindex $argv 0]
set slice_name [lindex $argv 1]
set placement_variant [lindex $argv 2]
set placement_gap [lindex $argv 3]
set placement_offset [lindex $argv 4]

if {$placement_variant eq ""} {
    set placement_variant "lr_abcd"
}
if {$placement_gap eq ""} {
    set placement_gap 1
}
if {$placement_offset eq ""} {
    set placement_offset 0
}

set placement_id ${placement_variant}_g${placement_gap}_o${placement_offset}

set baud_rate 1000000

# Setup build directory
set build_dir ../build/${placement_id}/${slice_name}_${stages}
file mkdir $build_dir

read_verilog [glob APUF_CMODS7.srcs/sources_1/new/uart_*.v]
read_verilog [glob APUF_CMODS7.srcs/sources_1/without_PDL/*.v]

read_xdc APUF_CMODS7.srcs/constrs_1/new/top.xdc
read_xdc constraints/placement_${slice_name}_${stages}_${placement_id}.xdc

# set_property CLOCK_DEDICATED_ROUTE FALSE [get_nets puf0/upper*]

# Use -generic to override top-level parameters.
synth_design -top top -part xc7s25csga225-1 -generic "STAGES=$stages" -generic "BAUD=$baud_rate"

opt_design
place_design
route_design
# place_design -directive Quick
# route_design -directive Quick

write_checkpoint -force ${build_dir}/top_routed.dcp
write_bitstream -force ${build_dir}/top.bit

source scripts/report_puf_routes.tcl
write_puf_route_report ${build_dir}/puf_routes.csv
