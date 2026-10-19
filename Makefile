# =============================================
# Makefile para projetos SystemVerilog + cocotb
# =============================================

# ===================== CONFIGURAÇÕES =====================
SIMULATOR     ?= icarus          # icarus ou verilator (para simulação tradicional)
SIM           ?= icarus          # usado pelo alvo cocotb (cocotb-test)
TOPLEVEL      ?= top             # Nome do módulo top-level
WAVES         ?= 1               # 1 = gera ondas

# Pastas
RTL_DIR       = rtl
TB_DIR        = tb
TB_PYTHON_DIR = tb_python
INCLUDE_DIR   = include
SIM_DIR       = sim

# ===================== FERRAMENTAS =====================
VERIBLE_FMT   = verible-verilog-format

# ===================== TARGETS GERAIS =====================
.PHONY: all sim format clean help cocotb cov-clean cov-triage cov-report cov

all: sim

format:
	@echo "Formatando arquivos SystemVerilog..."
	$(VERIBLE_FMT) --inplace $(shell find $(RTL_DIR) $(TB_DIR) -name '*.sv' 2>/dev/null) 2>/dev/null || true

clean:
	rm -rf $(SIM_DIR)/*.out $(SIM_DIR)/*.vcd $(SIM_DIR)/*.fst $(SIM_DIR)/obj_dir __pycache__/

help:
	@echo "Comandos disponíveis:"
	@echo "  make sim                  → Simulação tradicional (Icarus/Verilator)"
	@echo "  make sim SIMULATOR=verilator → Usa Verilator"
	@echo "  make cocotb               → Roda todos os testes cocotb (padrão: icarus)"
	@echo "  make cocotb SIM=verilator → Roda cocotb com Verilator (mais rápido)"
	@echo "  make format               → Formata o código RTL"
	@echo "  make clean                → Limpa arquivos gerados"
	@echo ""
	@echo "Para rodar um teste específico com cocotb: pytest tb_python/test_nome.py -q"

# ===================== SIMULAÇÃO TRADICIONAL =====================
sim-icarus:
	mkdir -p $(SIM_DIR)
	iverilog -g2012 -Wall -I$(INCLUDE_DIR) -o $(SIM_DIR)/sim.out \
		$(shell find $(RTL_DIR) -name '*.sv' 2>/dev/null) \
		$(shell find $(TB_DIR) -name '*.sv' 2>/dev/null)
	cd $(SIM_DIR) && vvp sim.out

sim-verilator:
	@echo "Simulação com Verilator ainda em desenvolvimento neste template..."

sim:
ifeq ($(SIMULATOR),verilator)
	$(MAKE) sim-verilator
else
	$(MAKE) sim-icarus
endif

# ===================== COCOTB =====================
# Cada tb_python/test_*.py e autocontido: chama cocotb_test.simulator.run()
# com seus proprios verilog_sources/toplevel/parameters. O pytest apenas
# descobre e roda todos os arquivos test_*.py da pasta - nao ha mais um
# TOPLEVEL/MODULE globais (cada teste define os seus). A env var SIM
# ainda funciona (lida automaticamente por cocotb-test) para trocar de
# simulador, ex: make cocotb SIM=verilator.
cocotb:
	mkdir -p $(SIM_DIR)
	@echo "Rodando testes cocotb (SIM=$(strip $(SIM))) ..."
	cd $(TB_PYTHON_DIR) && SIM=$(strip $(SIM)) python3 -m pytest -q

# Alias para facilitar
test: cocotb

# ===================== COBERTURA (Fase 4, plano D) =====================
# Exige o Verilator novo no PATH (shell com VERILATOR_ROOT/PATH do 5.052).
# Informativo: nao falha o make por causa de testes que falham sob Verilator.
cov-clean:
	rm -rf $(SIM_DIR)/cov_data $(SIM_DIR)/sim_build_*_cov

cov-triage: cov-clean
	@command -v verilator && verilator --version
	mkdir -p $(SIM_DIR)/cov_data
	cd $(TB_PYTHON_DIR) && COV_MODE=1 SIM=verilator python3 -m pytest -q --tb=line -rfEs \
		--ignore=test_meta_guard.py --ignore=test_cov_hook.py --ignore=test_cov_report.py \
		--durations=15 \

cov-report:
	python3 scripts/cov_report.py --data $(SIM_DIR)/cov_data

cov: cov-triage cov-report