# setup_proj.tcl — cria o projeto do zero (sobrescreve se existir)
project_new sobel_multicycle -overwrite

# --- Dispositivo alvo ---
set_global_assignment -name FAMILY "Cyclone V"
set_global_assignment -name DEVICE 5CSEMA5F31C6
set_global_assignment -name TOP_LEVEL_ENTITY sobel_multicycle

# --- Caminho de busca para arquivos de inclusão ---
set_global_assignment -name SEARCH_PATH "include"

# --- Arquivos RTL (comuns) ---
set_global_assignment -name SYSTEMVERILOG_FILE rtl/common/line_buffer_2line.sv
set_global_assignment -name SYSTEMVERILOG_FILE rtl/common/window_3x3.sv
set_global_assignment -name SYSTEMVERILOG_FILE rtl/common/abs_saturate.sv
set_global_assignment -name SYSTEMVERILOG_FILE rtl/common/magnitude_l1.sv
set_global_assignment -name SYSTEMVERILOG_FILE rtl/common/line_window_skid.sv

# --- Arquivos RTL (multiciclo) ---
set_global_assignment -name SYSTEMVERILOG_FILE rtl/multicycle/mac_unit.sv
set_global_assignment -name SYSTEMVERILOG_FILE rtl/multicycle/kernel_rom.sv
set_global_assignment -name SYSTEMVERILOG_FILE rtl/multicycle/mac_control_fsm.sv
set_global_assignment -name SYSTEMVERILOG_FILE rtl/multicycle/skid_fifo2.sv
set_global_assignment -name SYSTEMVERILOG_FILE rtl/multicycle/sobel_multicycle.sv

# --- Restrições de timing ---
set_global_assignment -name SDC_FILE constraints/multicycle.sdc

# --- Configurações de simulação ---
set_global_assignment -name EDA_SIMULATION_TOOL "Questa Intel FPGA (Verilog)"
#set_global_assignment -name EDA_SIMULATION_TOOL "ModelSim (Verilog)"
# Habilita a geração da netlist funcional
set_global_assignment -name EDA_GENERATE_FUNCTIONAL_NETLIST ON -section_id eda_simulation
# Diretório de saída da netlist (simulation/)
set_global_assignment -name EDA_NETLIST_WRITER_OUTPUT_DIR simulation -section_id eda_simulation
# Formato de saída Verilog
set_global_assignment -name EDA_OUTPUT_DATA_FORMAT "VERILOG HDL" -section_id eda_simulation

# --- Diretório de saída ---
set_global_assignment -name PROJECT_OUTPUT_DIRECTORY output_files

project_close