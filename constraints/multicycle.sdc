# constraints/multicycle.sdc — restrição básica de clock
create_clock -name clk -period 10.000 [get_ports {clk}]
derive_clock_uncertainty