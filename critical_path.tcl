# critical_path.tcl — extrai os 10 caminhos mais críticos de setup
project_open sobel_multicycle
create_timing_netlist
read_sdc constraints/multicycle.sdc
update_timing_netlist

# Relatório sumário dos 10 piores caminhos
report_timing -setup -npaths 10 -detail summary \
    -file critical_path_summary.rpt

# Relatório detalhado do pior caminho (nó a nó)
report_timing -setup -npaths 1 -detail full_path \
    -file critical_path_full.rpt

project_close