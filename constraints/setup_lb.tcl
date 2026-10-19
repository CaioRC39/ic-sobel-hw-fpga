project_new line_buffer_2line_isolated -overwrite

set_global_assignment -name FAMILY "Cyclone V"
set_global_assignment -name DEVICE 5CSEMA5F31C6
set_global_assignment -name TOP_LEVEL_ENTITY line_buffer_2line

set_global_assignment -name SEARCH_PATH "include"

set_global_assignment -name SYSTEMVERILOG_FILE rtl/common/line_buffer_2line.sv

set_global_assignment -name EDA_GENERATE_FUNCTIONAL_NETLIST ON -section_id eda_simulation
set_global_assignment -name EDA_SIMULATION_TOOL "Questa Intel FPGA (Verilog)"
set_global_assignment -name EDA_NETLIST_WRITER_OUTPUT_DIR simulation_lb -section_id eda_simulation
set_global_assignment -name EDA_OUTPUT_DATA_FORMAT "VERILOG HDL" -section_id eda_simulation

set_global_assignment -name PROJECT_OUTPUT_DIRECTORY output_files_lb

set_parameter -name IMG_WIDTH 6 -entity line_buffer_2line
set_parameter -name DATA_WIDTH 8 -entity line_buffer_2line

project_close