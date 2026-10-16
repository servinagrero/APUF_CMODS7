# This script extracts extract the coordinates of all available LUT6 luts
#
# The script can be run with the following command and likning the design part
#   vivado -mode batch -source scripts/extract_luts.tcl
link_design -part xc7s25csga225-1

# Or it can be loaded alongside the project
#   vivado -mode batch -source extract_luts.tcl -tclargs APUF_CMODS7.xpr
# open_project [lindex $argv 0]

set outfile "valid_A6LUTs_by_clock_region.csv"
set fp [open $outfile w]

puts $fp "clock_region,X,Y"

foreach cr [get_clock_regions] {

    set cr_name [get_property NAME $cr]

    # Get all A6LUT BELs inside this clock region
    foreach bel [get_bels -of_objects $cr \
            -filter {NAME =~ SLICE_X*Y*/A6LUT && TYPE == LUT6}] {

        set bel_name [get_property NAME $bel]

        # Extract X/Y coordinates
        if {[regexp {SLICE_X([0-9]+)Y([0-9]+)/A6LUT} \
                $bel_name -> x y]} {

            puts $fp "$cr_name,$x,$y"
        }
    }
}

close $fp

puts "Results written to $outfile"
