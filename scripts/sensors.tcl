open_hw_manager
connect_hw_server

foreach target [get_hw_targets] {
    current_hw_target $target
    open_hw_target

    refresh_hw_device [current_hw_device]

    set sysmon [lindex [get_hw_sysmons] 0]

    refresh_hw_sysmon -properties {TEMPERATURE} $sysmon

    puts "$target,[get_property TEMPERATURE $sysmon]"

    close_hw_target
}
