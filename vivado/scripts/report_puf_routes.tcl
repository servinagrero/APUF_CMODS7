proc csv_quote {value} {
    set text [join $value " "]
    regsub -all {"} $text {""} text
    return "\"$text\""
}

proc write_puf_cell_route {fp stage rail cell} {
    set loc [get_property LOC $cell]
    set bel [get_property BEL $cell]
    set lock_pins [get_property LOCK_PINS $cell]
    set out_pins [get_pins -quiet -of_objects $cell -filter {DIRECTION == OUT}]
    set out_net ""
    set route ""

    if {[llength $out_pins] > 0} {
        set out_net [get_nets -quiet -of_objects [lindex $out_pins 0]]
        if {$out_net ne ""} {
            set route [get_property ROUTE $out_net]
        }
    }

    puts $fp [join [list \
        $stage \
        $rail \
        [csv_quote $cell] \
        $loc \
        $bel \
        [csv_quote $lock_pins] \
        [csv_quote $out_net] \
        [csv_quote $route] \
    ] ","]
}

proc write_puf_route_report {report_path} {
    set fp [open $report_path w]
    puts $fp "stage,rail,cell,loc,bel,lock_pins,out_net,route"

    set stage_cells [get_cells -quiet -hierarchical -regexp {.*puf0/STAGE\[[0-9]+\]\.(upper_mux|lower_mux)$}]
    foreach cell [lsort -dictionary $stage_cells] {
        set cell_name [get_property NAME $cell]
        if {[regexp {STAGE\[([0-9]+)\]\.(upper_mux|lower_mux)$} $cell_name -> stage rail]} {
            write_puf_cell_route $fp $stage $rail $cell
        }
    }

    foreach rail {nand_upper nand_lower} {
        set cells [get_cells -quiet -hierarchical -regexp ".*puf0/${rail}$"]
        foreach cell $cells {
            write_puf_cell_route $fp arbiter $rail $cell
        }
    }

    close $fp
}
