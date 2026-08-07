"""Testbench cocotb para o modulo rtl/multicycle/kernel_rom.sv.

Modulo puramente combinacional (sem clk) - mesmo padrao de
test_abs_saturate.py (Timer em vez de RisingEdge/ReadOnly).

As tabelas de referencia (GX_COEFFS/GY_COEFFS e seus indices na
janela) sao as MESMAS usadas em test_mac_unit.py - qualquer
divergencia entre os dois arquivos pegaria um erro de consistencia
entre kernel_rom e o que a FSM realmente vai precisar.
"""

import os

import cocotb
from cocotb.triggers import Timer

from _cocotb_helpers import capture_errors, run_isolated

COEFF_WIDTH = 3

# indices (posicao 0..8 na janela, linha-major) e coeficientes dos 6
# taps nao-nulos de cada kernel - ver docs/ARQUITETURA_MULTICICLO.md,
# secao 6.2.
GX_WIN_POS = [0, 2, 3, 5, 6, 8]
GX_COEFFS = [-1, 1, -2, 2, -1, 1]
GY_WIN_POS = [0, 1, 2, 6, 7, 8]
GY_COEFFS = [-1, -2, -1, 1, 2, 1]


async def _check(dut, gy: int, tap_idx: int, exp_win_pos: int, exp_coeff: int):
    dut.i_gy.value = gy
    dut.i_tap_idx.value = tap_idx
    await Timer(1, unit="ns")
    got_win_pos = int(dut.o_win_pos.value)
    got_coeff = dut.o_coeff.value.signed_integer
    got_addr_valid = int(dut.o_addr_valid.value)
    assert got_win_pos == exp_win_pos, (
        f"gy={gy} tap_idx={tap_idx}: win_pos esperado={exp_win_pos} obtido={got_win_pos}"
    )
    assert got_coeff == exp_coeff, (
        f"gy={gy} tap_idx={tap_idx}: coeff esperado={exp_coeff} obtido={got_coeff}"
    )
    assert got_addr_valid == 1, (
        f"gy={gy} tap_idx={tap_idx}: o_addr_valid deveria ser 1 (tap real), obtido={got_addr_valid}"
    )


@cocotb.test()
async def test_gx_table(dut):
    for tap_idx in range(6):
        await _check(dut, gy=0, tap_idx=tap_idx, exp_win_pos=GX_WIN_POS[tap_idx], exp_coeff=GX_COEFFS[tap_idx])


@cocotb.test()
async def test_gy_table(dut):
    for tap_idx in range(6):
        await _check(dut, gy=1, tap_idx=tap_idx, exp_win_pos=GY_WIN_POS[tap_idx], exp_coeff=GY_COEFFS[tap_idx])


@cocotb.test()
async def test_all_win_positions_covered_exactly_once_per_kernel(dut):
    """Confirma que os 6 win_pos de cada kernel sao todos DIFERENTES
    entre si (nenhum tap lendo a mesma posicao duas vezes por engano)."""
    for gy, expected_positions in [(0, GX_WIN_POS), (1, GY_WIN_POS)]:
        seen = set()
        for tap_idx in range(6):
            dut.i_gy.value = gy
            dut.i_tap_idx.value = tap_idx
            await Timer(1, unit="ns")
            pos = int(dut.o_win_pos.value)
            assert pos not in seen, f"gy={gy}: posicao {pos} repetida em mais de 1 tap"
            seen.add(pos)
        assert seen == set(expected_positions), f"gy={gy}: posicoes obtidas {seen} != esperado {set(expected_positions)}"


def test_kernel_rom_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_kernel_rom")

    # Fica de fora daqui, de proposito, test_invalid_tap_idx_safe_and_error
    # (executor dedicado abaixo) - mesmo padrao de test_window_3x3.py.
    run_isolated(
        "test_gx_table,test_gy_table,test_all_win_positions_covered_exactly_once_per_kernel",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "multicycle", "kernel_rom.sv"),
        ],
        includes=[os.path.join(proj_root, "include")],
        toplevel="kernel_rom",
        module="test_kernel_rom",
        parameters={"COEFF_WIDTH": COEFF_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


@cocotb.test()
async def test_invalid_tap_idx_safe_and_error(dut):
    """CAMINHO ERRADO (Ponto #3 da sessao, com trava ativa adicionada
    depois): i_tap_idx fora de 0..5 - so existem 6 taps por kernel, mas
    i_tap_idx tem 3 bits (permite ate 7). o_win_pos deve continuar
    dentro de 0..8 (trava ativa - nunca causa acesso fora dos limites
    de um array de 9 posicoes, mesmo que o consumidor nao cheque nada)
    e o_addr_valid deve cair para 0 (unico jeito, sintetizavel, de
    DISTINGUIR esse caso de um pedido legitimo do tap 0, que tambem usa
    win_pos=0). A checagem do $error acontece no executor dedicado, do
    lado de fora desta corrotina."""
    for gy in (0, 1):
        for bad_tap_idx in (6, 7):
            dut.i_gy.value = gy
            dut.i_tap_idx.value = bad_tap_idx
            await Timer(1, unit="ns")
            got_win_pos = int(dut.o_win_pos.value)
            got_coeff = dut.o_coeff.value.signed_integer
            got_addr_valid = int(dut.o_addr_valid.value)
            assert 0 <= got_win_pos <= 8, (
                f"gy={gy} tap_idx={bad_tap_idx}: o_win_pos deveria ficar dentro de 0..8 "
                f"(trava ativa), obtido={got_win_pos}"
            )
            assert got_coeff == 0, (
                f"gy={gy} tap_idx={bad_tap_idx}: o_coeff deveria ser 0, obtido={got_coeff}"
            )
            assert got_addr_valid == 0, (
                f"gy={gy} tap_idx={bad_tap_idx}: o_addr_valid deveria ser 0 (endereco invalido), "
                f"obtido={got_addr_valid}"
            )


def test_kernel_rom_invalid_tap_idx_runner():
    """Executor dedicado - mesma razao de
    test_window_3x3_contract_violation_runner: roda separado para nao
    poluir o log de execucao normal com linhas 'ERROR:' esperadas."""
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_kernel_rom_invalid_tap_idx")

    with capture_errors() as capture:
        run_isolated(
            "test_invalid_tap_idx_safe_and_error",
            verilog_sources=[
                os.path.join(proj_root, "rtl", "multicycle", "kernel_rom.sv"),
            ],
            includes=[os.path.join(proj_root, "include")],
            toplevel="kernel_rom",
            module="test_kernel_rom",
            parameters={"COEFF_WIDTH": COEFF_WIDTH},
            compile_args=["-g2012", "-Wall"],
            sim_build=sim_build,
        )

    # 2 enderecos invalidos (6,7) x 2 kernels (Gx,Gy) = 4 disparos esperados.
    expected_violations = 4
    assert capture.count == expected_violations, (
        f"esperava {expected_violations} disparos de $error, mas contei {capture.count}"
    )


if __name__ == "__main__":
    test_kernel_rom_runner()
    test_kernel_rom_invalid_tap_idx_runner()
