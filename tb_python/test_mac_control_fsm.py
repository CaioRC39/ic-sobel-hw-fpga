"""Testbench cocotb para o modulo rtl/multicycle/mac_control_fsm.sv.

Modelo de referencia: convolucao Sobel completa (Gx, Gy, magnitude L1,
saturacao) calculada em numpy a partir da MESMA janela 3x3 apresentada
ao DUT - compara o resultado bit a bit, nao so a "forma" do calculo.
"""

import os

import numpy as np

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge

from _cocotb_helpers import capture_errors, run_isolated

DATA_WIDTH = 8
COEFF_WIDTH = 3
ACC_WIDTH = 11

GX_KERNEL = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]])
GY_KERNEL = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]])

# Numero de ciclos uteis por pixel, ver docs/ARQUITETURA_MULTICICLO.md
# secao "mac_control_fsm": LOAD_WIN(1)+MAC_GX(6)+SAVE_GX(1)+MAC_GY(6)+
# OUTPUT(1) = 15.
EXPECTED_CYCLES_TO_VALID = 15


def _pack_window(window) -> int:
    """window: lista de listas 3x3 (linha, coluna). Retorna o inteiro
    do vetor achatado, MESMO layout de window_3x3.sv/mac_control_fsm.sv
    (MSB->LSB, ordem linha-major k=3*linha+coluna)."""
    val = 0
    mask = (1 << DATA_WIDTH) - 1
    for r in range(3):
        for c in range(3):
            k = 3 * r + c
            shift = (8 - k) * DATA_WIDTH
            val |= (window[r][c] & mask) << shift
    return val


def _reference_magnitude(window) -> int:
    w = np.array(window, dtype=int)
    gx = int(np.sum(w * GX_KERNEL))
    gy = int(np.sum(w * GY_KERNEL))
    return min(abs(gx) + abs(gy), 255)


async def _reset(dut):
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_window.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def _feed_and_wait(dut, window, timeout_cycles=30):
    """Apresenta a janela (pulso de 1 ciclo de i_valid) e avanca ate
    o_valid disparar, contando TODAS as bordas de clock desde a que
    amostra i_valid=1 (inclusive) - retorna (pixel, numero_de_ciclos).

    Depois de capturar pixel/cycles, tambem espera o_ready voltar a 1
    (S_OUTPUT -> S_IDLE, transicao incondicional, 1 borda) antes de
    retornar - garante que uma chamada seguinte em sequencia (ver
    test_various_windows) nunca apresente i_valid=1 enquanto a FSM
    ainda esta em S_OUTPUT (o_ready=0), o que violaria o contrato de
    interface (Bug #3 encontrado nesta sessao)."""
    dut.i_valid.value = 1
    dut.i_window.value = _pack_window(window)
    result = None
    for cycles in range(1, timeout_cycles + 1):
        await RisingEdge(dut.clk)
        await ReadOnly()
        v = int(dut.o_valid.value)
        pixel = int(dut.o_pixel.value) if v else None
        await NextTimeStep()
        if cycles == 1:
            dut.i_valid.value = 0  # solta o pulso logo apos a 1a borda
            dut.i_window.value = 0
        if v:
            result = (pixel, cycles)
            break
    else:
        raise TimeoutError(f"o_valid nao disparou em {timeout_cycles} ciclos")

    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk)
        await ReadOnly()
        ready = int(dut.o_ready.value)
        await NextTimeStep()
        if ready:
            break
    else:
        raise TimeoutError("o_ready nao voltou a 1 apos o_valid")

    return result


@cocotb.test()
async def test_reset_state(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    await ReadOnly()
    assert dut.o_ready.value == 1, "apos reset, o_ready deveria ser 1 (pronto pra receber)"
    assert dut.o_valid.value == 0
    await NextTimeStep()


@cocotb.test()
async def test_cycle_timing(dut):
    """Confirma a contagem EXATA de ciclos entre o pulso de entrada e
    o_valid - nao so 'eventualmente da certo', o numero certo."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    await ReadOnly()
    assert dut.o_ready.value == 1
    await NextTimeStep()

    window = [[10, 20, 30], [40, 50, 60], [70, 80, 90]]
    pixel, cycles = await _feed_and_wait(dut, window)
    assert cycles == EXPECTED_CYCLES_TO_VALID, (
        f"esperava o_valid exatamente {EXPECTED_CYCLES_TO_VALID} ciclos depois do pulso, "
        f"disparou em {cycles}"
    )
    assert pixel == _reference_magnitude(window), (
        f"janela {window}: esperado={_reference_magnitude(window)} obtido={pixel}"
    )


@cocotb.test()
async def test_o_ready_low_while_busy(dut):
    """o_ready deve cair para 0 assim que o processamento comeca
    (durante os 15 ciclos, inclusive o proprio ciclo de o_valid, ja que
    o estado so volta a S_IDLE no ciclo SEGUINTE), e so entao voltar a
    1."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    window = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
    dut.i_valid.value = 1
    dut.i_window.value = _pack_window(window)

    for cycle in range(1, EXPECTED_CYCLES_TO_VALID + 1):
        await RisingEdge(dut.clk)
        await ReadOnly()
        assert dut.o_ready.value == 0, f"o_ready deveria ser 0 no ciclo {cycle} (ainda processando)"
        if cycle == EXPECTED_CYCLES_TO_VALID:
            assert dut.o_valid.value == 1, f"o_valid deveria disparar exatamente no ciclo {cycle}"
        await NextTimeStep()
        if cycle == 1:
            dut.i_valid.value = 0
            dut.i_window.value = 0

    # 1 ciclo a mais: a FSM volta a S_IDLE, o_ready deve voltar a 1
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert dut.o_ready.value == 1, "o_ready deveria voltar a 1 no ciclo seguinte ao o_valid"
    await NextTimeStep()


@cocotb.test()
async def test_various_windows(dut):
    """Varias janelas com valores diferentes (incluindo casos de
    saturacao e uma janela toda zero), cada uma validada contra a
    referencia numpy."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    windows = [
        [[0, 0, 0], [0, 0, 0], [0, 0, 0]],  # tudo zero
        [[255, 255, 255], [255, 255, 255], [255, 255, 255]],  # tudo maximo (gradiente=0)
        [[0, 0, 0], [0, 0, 0], [255, 255, 255]],  # borda forte (satura)
        [[255, 255, 255], [0, 0, 0], [0, 0, 0]],  # borda forte, direcao oposta
        [[0, 255, 0], [255, 0, 255], [0, 255, 0]],  # xadrez
        [[12, 200, 45], [78, 3, 250], [99, 150, 6]],  # valores arbitrarios
    ]
    for window in windows:
        pixel, cycles = await _feed_and_wait(dut, window)
        expected = _reference_magnitude(window)
        assert cycles == EXPECTED_CYCLES_TO_VALID
        assert pixel == expected, f"janela {window}: esperado={expected} obtido={pixel}"


@cocotb.test()
async def test_contract_violation_detected(dut):
    """CAMINHO ERRADO: apresenta i_valid enquanto a FSM ainda esta
    ocupada (o_ready=0) - o $error de simulacao deve disparar. A
    checagem de fato acontece no executor dedicado
    test_mac_control_fsm_contract_violation_runner."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    window = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
    dut.i_valid.value = 1
    dut.i_window.value = _pack_window(window)
    # mantem i_valid=1 por VARIOS ciclos seguidos, violando o contrato
    # assim que a FSM sair de S_IDLE
    for _ in range(5):
        await RisingEdge(dut.clk)
    dut.i_valid.value = 0


def test_mac_control_fsm_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_mac_control_fsm")

    run_isolated(
        "test_reset_state,test_cycle_timing,test_o_ready_low_while_busy,test_various_windows",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "abs_saturate.sv"),
            os.path.join(proj_root, "rtl", "common", "magnitude_l1.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "mac_unit.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "kernel_rom.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "mac_control_fsm.sv"),
        ],
        includes=[os.path.join(proj_root, "include")],
        toplevel="mac_control_fsm",
        module="test_mac_control_fsm",
        parameters={"DATA_WIDTH": DATA_WIDTH, "COEFF_WIDTH": COEFF_WIDTH, "ACC_WIDTH": ACC_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


def test_mac_control_fsm_contract_violation_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_mac_control_fsm_violation")

    with capture_errors() as capture:
        run_isolated(
            "test_contract_violation_detected",
            verilog_sources=[
                os.path.join(proj_root, "rtl", "common", "abs_saturate.sv"),
                os.path.join(proj_root, "rtl", "common", "magnitude_l1.sv"),
                os.path.join(proj_root, "rtl", "multicycle", "mac_unit.sv"),
                os.path.join(proj_root, "rtl", "multicycle", "kernel_rom.sv"),
                os.path.join(proj_root, "rtl", "multicycle", "mac_control_fsm.sv"),
            ],
            includes=[os.path.join(proj_root, "include")],
            toplevel="mac_control_fsm",
            module="test_mac_control_fsm",
            parameters={
                "DATA_WIDTH": DATA_WIDTH,
                "COEFF_WIDTH": COEFF_WIDTH,
                "ACC_WIDTH": ACC_WIDTH,
            },
            compile_args=["-g2012", "-Wall"],
            sim_build=sim_build,
        )

    assert capture.found, (
        "esperava que o $error de violacao de contrato (mac_control_fsm.sv) disparasse "
        "ao manter i_valid=1 com a FSM ocupada, mas nenhum ERROR foi detectado"
    )


if __name__ == "__main__":
    test_mac_control_fsm_runner()
    test_mac_control_fsm_contract_violation_runner()
