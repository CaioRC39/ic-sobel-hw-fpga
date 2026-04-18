# =============================================
# Makefile para projetos SystemVerilog + cocotb
# =============================================

# ===================== CONFIGURAÇÕES =====================
SIMULATOR     ?= icarus          # icarus ou verilator (para simulação tradicional)
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
.PHONY: all sim format clean help cocotb

all: sim

format:
	@echo "Formatando arquivos SystemVerilog..."
	$(VERIBLE_FMT) --inplace $(RTL_DIR)/*.sv $(TB_DIR)/*.sv 2>/dev/null || true

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
		$(RTL_DIR)/*.sv $(TB_DIR)/*.sv
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
cocotb:
	mkdir -p $(SIM_DIR)
	@echo "Rodando testes cocotb com SIM=$(SIM) ..."
	@cd $(TB_PYTHON_DIR) && \
		SIM=$(SIM) \
		TOPLEVEL_LANG=verilog \
		VERILOG_SOURCES="$(shell pwd)/$(RTL_DIR)/*.sv" \
		TOPLEVEL=$(TOPLEVEL) \
		MODULE=$(shell ls *.py | sed 's/\.py$$//') \
		pytest -q --tb=no

# Alias para facilitar
test: cocotb