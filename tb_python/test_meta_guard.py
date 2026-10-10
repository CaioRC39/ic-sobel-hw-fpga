"""Testes da PROPRIA guarda contra $error escondido (P15, Opcao B).

A guarda mora em _cocotb_helpers.run_isolated (expect_errors, padrao 0).
Duas coisas podem fazer ela virar decoracao, e estes testes fecham as duas:

1. Um teste novo/antigo chamar cocotb_test.simulator.run() direto e fugir
   da guarda -> o meta-teste estatico abaixo falha.
2. A guarda deixar de enxergar o $error (mudanca de formato de log ou de
   versao do cocotb-test) -> o canario abaixo falha, porque ele PROVA que
   um $error inesperado derruba o teste (e que contagem MENOR que a
   declarada tambem derruba - a contagem e exata).
"""

import glob
import os
import re

import pytest

from _cocotb_helpers import run_isolated

TB_DIR = os.path.dirname(os.path.abspath(__file__))
PROJ_ROOT = os.path.dirname(TB_DIR)

# `run` do cocotb_test usado direto (qualquer forma de import) = fora da guarda.
_BYPASS = re.compile(r"^\s*(from\s+cocotb_test(\.simulator)?\s+import|import\s+cocotb_test)", re.M)


def test_no_test_file_bypasses_the_error_guard():
    offenders = []
    for path in sorted(glob.glob(os.path.join(TB_DIR, "test_*.py"))):
        with open(path, encoding="utf-8") as f:
            if _BYPASS.search(f.read()):
                offenders.append(os.path.basename(path))
    assert not offenders, (
        f"estes arquivos importam cocotb_test direto e escapam da guarda de $error: {offenders}. "
        f"Use `from _cocotb_helpers import run_isolated`."
    )


def _run_kernel_rom_invalid_tap(expect_errors):
    """kernel_rom com tap invalido emite exatamente 4 $error (2 enderecos x 2 kernels)."""
    run_isolated(
        "test_invalid_tap_idx_safe_and_error",
        verilog_sources=[os.path.join(PROJ_ROOT, "rtl", "multicycle", "kernel_rom.sv")],
        includes=[os.path.join(PROJ_ROOT, "include")],
        toplevel="kernel_rom",
        module="test_kernel_rom",
        parameters={"COEFF_WIDTH": 3},
        compile_args=["-g2012", "-Wall"],
        sim_build=os.path.join(PROJ_ROOT, "sim", "sim_build_guard_canary"),
        expect_errors=expect_errors,
    )


def test_guard_canary_unexpected_error_fails():
    """$error nao declarado (expect_errors=0 padrao) DEVE derrubar o teste."""
    with pytest.raises(AssertionError, match="Guarda de \\$error"):
        _run_kernel_rom_invalid_tap(0)


def test_guard_canary_count_is_exact():
    """Esperar MAIS erros do que o RTL emite tambem DEVE falhar (contagem exata)."""
    with pytest.raises(AssertionError, match="Guarda de \\$error"):
        _run_kernel_rom_invalid_tap(5)
