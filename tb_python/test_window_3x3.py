"""Testbench cocotb para o modulo rtl/common/window_3x3.sv.

Modelo de referencia: constroi uma pequena imagem sintetica H x W,
aplica zero-padding de 1 pixel em numpy, e extrai a vizinhanca 3x3 de
cada posicao real da imagem. O DUT e alimentado linha a linha, com
i_curr/i_line1/i_line2 calculados manualmente a partir da mesma imagem
(simulando o que line_buffer_2line entregaria), respeitando o contrato
de 1 ciclo de gap entre linhas.

Nota de metodologia: usamos o padrao RisingEdge -> ReadOnly() ->
(captura) -> NextTimeStep() para amostrar as saidas - ver nota
equivalente em test_line_buffer_2line.py para o porque.

Nota de escopo: este teste NAO cobre a borda inferior do frame (ultima
linha da imagem), pois isso exige uma "linha fantasma" de zeros extra
ao final do frame - responsabilidade de um controlador de nivel
superior que ainda nao existe (ver item 5 do plano). Cobrimos aqui a
borda superior (zero-padding automatico das 2 primeiras linhas) e as
bordas esquerda/direita (dentro de cada linha).
"""

import os

import numpy as np

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge

from _cocotb_helpers import capture_errors, run_isolated

DATA_WIDTH = 8
IMG_WIDTH = 6
IMG_HEIGHT = 5


def _build_reference_windows(image: np.ndarray):
    """Retorna a lista de janelas 3x3 esperadas (zero-padded), em ordem
    raster-scan, para as linhas de SAIDA 0..H-2 (ver nota de escopo)."""
    h, w = image.shape
    padded = np.pad(image, 1, mode="constant", constant_values=0)
    windows = []
    for out_row in range(h - 1):  # linha de saida H-1 fora de escopo aqui
        for col in range(w):
            win = padded[out_row:out_row + 3, col:col + 3]
            windows.append(win.astype(int).tolist())
    return windows


async def _reset(dut):
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_curr.value = 0
    dut.i_line1.value = 0
    dut.i_line2.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


def _unpack_window(raw: int):
    """o_window e um vetor packed achatado (ver comentario de layout no
    cabecalho de rtl/common/window_3x3.sv): 9 fatias de DATA_WIDTH bits,
    MSB->LSB, ordem linha-major k=3*linha+coluna."""
    mask = (1 << DATA_WIDTH) - 1
    window = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
    for r in range(3):
        for c in range(3):
            k = 3 * r + c
            shift = (8 - k) * DATA_WIDTH
            window[r][c] = (raw >> shift) & mask
    return window


async def _step(dut, valid: int, curr: int, line1: int, line2: int):
    """Aplica as entradas, avanca 1 ciclo e retorna as saidas
    assentadas (ver nota de metodologia no cabecalho do arquivo)."""
    dut.i_valid.value = valid
    dut.i_curr.value = curr
    dut.i_line1.value = line1
    dut.i_line2.value = line2
    await RisingEdge(dut.clk)
    await ReadOnly()
    out_valid = int(dut.o_valid.value)
    out_window = _unpack_window(int(dut.o_window.value)) if out_valid else None
    await NextTimeStep()
    return out_valid, out_window


@cocotb.test()
async def test_reset_state(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    await ReadOnly()
    assert dut.o_valid.value == 0
    await NextTimeStep()


@cocotb.test()
async def test_geometry_with_zero_padding(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    image = (np.arange(1, IMG_HEIGHT * IMG_WIDTH + 1) % 251).reshape(
        IMG_HEIGHT, IMG_WIDTH
    )
    expected = _build_reference_windows(image)

    captured = []
    for row in range(IMG_HEIGHT):
        for col in range(IMG_WIDTH):
            curr = int(image[row, col])
            line1 = int(image[row - 1, col]) if row >= 1 else 0
            line2 = int(image[row - 2, col]) if row >= 2 else 0
            out_valid, out_window = await _step(dut, 1, curr, line1, line2)
            if out_valid:
                captured.append(out_window)

        # Contrato de interface: 1 ciclo de gap entre linhas (permite o
        # ciclo fantasma de borda direita acontecer dentro de window_3x3).
        out_valid, out_window = await _step(dut, 0, 0, 0, 0)
        if out_valid:
            captured.append(out_window)

    # Descarta os eventos produzidos ao processar a linha de entrada 0
    # (correspondem a "linha de saida -1", que nao existe - ver docstring).
    captured = captured[IMG_WIDTH:]

    assert len(captured) == len(expected), (
        f"quantidade de janelas capturadas ({len(captured)}) != esperado "
        f"({len(expected)})"
    )
    for idx, (got, exp) in enumerate(zip(captured, expected)):
        out_row, out_col = divmod(idx, IMG_WIDTH)
        assert got == exp, (
            f"janela errada em (linha_saida={out_row}, col={out_col}): "
            f"obtido={got} esperado={exp}"
        )


@cocotb.test()
async def test_multiple_gap_cycles(dut):
    """O contrato de interface exige >=1 ciclo de gap entre linhas -
    isso NAO significa 'exatamente 1'. Alimenta 3 ciclos de gap em vez
    de 1 e confirma que a geometria continua correta (o modulo deve
    tolerar gaps maiores que o minimo, nao so o caso exato)."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    n_rows = 3
    image = (np.arange(1, n_rows * IMG_WIDTH + 1) % 251).reshape(n_rows, IMG_WIDTH)

    captured = []
    for row in range(n_rows):
        for col in range(IMG_WIDTH):
            curr = int(image[row, col])
            line1 = int(image[row - 1, col]) if row >= 1 else 0
            line2 = int(image[row - 2, col]) if row >= 2 else 0
            out_valid, out_window = await _step(dut, 1, curr, line1, line2)
            if out_valid:
                captured.append(out_window)

        for _ in range(3):  # 3 ciclos de gap em vez de 1
            out_valid, out_window = await _step(dut, 0, 0, 0, 0)
            if out_valid:
                captured.append(out_window)

    captured = captured[IMG_WIDTH:]
    expected = _build_reference_windows(image)

    assert len(captured) == len(expected), (
        f"com 3 ciclos de gap: {len(captured)} janelas capturadas, esperado {len(expected)}"
    )
    for idx, (got, exp) in enumerate(zip(captured, expected)):
        assert got == exp, f"idx={idx}: obtido={got} esperado={exp}"


@cocotb.test()
async def test_contract_violation_detected(dut):
    """Viola de proposito o contrato de gap entre linhas (0 ciclos de
    gap, 2 linhas coladas uma na outra) - a asserção de simulação do
    RTL (`$error` em window_3x3.sv) deve disparar. A checagem de fato
    (capturar e confirmar o $error) acontece no executor dedicado
    `test_window_3x3_contract_violation_runner`, do lado de fora desta
    corrotina - ver nota ali para o porque."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    for row in range(2):
        for col in range(IMG_WIDTH):
            await _step(dut, 1, curr=row * 10 + col, line1=0, line2=0)


@cocotb.test()
async def test_sustained_contract_violation_detected(dut):
    """Viola o contrato de forma SUSTENTADA (varias linhas seguidas,
    nunca 1 ciclo de gap em lugar nenhum) - confirma que o alarme
    dispara repetidamente (nao so na primeira vez e depois "trava"), e
    com a contagem exata esperada. Checagem no executor dedicado
    `test_window_3x3_sustained_violation_runner`."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    n_rows = 5
    for row in range(n_rows):
        for col in range(IMG_WIDTH):
            await _step(dut, 1, curr=(row * IMG_WIDTH + col) % 256, line1=0, line2=0)

@cocotb.test()
async def test_ready_gating_prevents_manual_gap_calculation(dut):
    """Prova da trava ativa (Caminho B, ver docs/ARQUITETURA_MULTICICLO.md
    secao 4.2): alimenta o modulo SEM nenhum calculo manual de quando
    inserir gap - simplesmente respeita o_ready a cada ciclo, do mesmo
    jeito que um consumidor real (ex: sobel_multicycle) vai fazer. Se
    o_ready realmente reflete o contrato interno corretamente, a
    geometria das janelas produzidas deve ser IDENTICA a
    test_geometry_with_zero_padding (que calcula o gap manualmente) -
    E nenhum $error deve disparar."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    image = (np.arange(1, IMG_HEIGHT * IMG_WIDTH + 1) % 251).reshape(
        IMG_HEIGHT, IMG_WIDTH
    )
    expected = _build_reference_windows(image)

    captured = []
    row, col = 0, 0
    total_real_pixels = IMG_HEIGHT * IMG_WIDTH
    fed = 0

    # Nao ha NENHUMA logica de "ultima coluna -> insere gap" aqui -
    # o teste so olha o_ready a cada ciclo, exatamente como um
    # consumidor real deveria fazer.
    while fed < total_real_pixels:
        await ReadOnly()
        ready = int(dut.o_ready.value)
        await NextTimeStep()

        if ready:
            curr = int(image[row, col])
            line1 = int(image[row - 1, col]) if row >= 1 else 0
            line2 = int(image[row - 2, col]) if row >= 2 else 0
            out_valid, out_window = await _step(dut, 1, curr, line1, line2)
            fed += 1
            col += 1
            if col == IMG_WIDTH:
                col = 0
                row += 1
        else:
            # respeita o_ready=0: nao apresenta pixel novo neste ciclo
            out_valid, out_window = await _step(dut, 0, 0, 0, 0)

        if out_valid:
            captured.append(out_window)

    # drena o que ainda estiver "em transito" apos o ultimo pixel real
    for _ in range(5):
        out_valid, out_window = await _step(dut, 0, 0, 0, 0)
        if out_valid:
            captured.append(out_window)

    captured = captured[IMG_WIDTH:]  # mesmo descarte de test_geometry_with_zero_padding

    assert len(captured) == len(expected), (
        f"respeitando so o_ready (sem calculo manual de gap): "
        f"{len(captured)} janelas capturadas, esperado {len(expected)}"
    )
    for idx, (got, exp) in enumerate(zip(captured, expected)):
        assert got == exp, f"idx={idx}: obtido={got} esperado={exp}"


def test_window_3x3_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_window_3x3")

    # Roda so os testes "normais" - test_contract_violation_detected e
    # test_sustained_contract_violation_detected ficam de fora daqui de
    # proposito (ver executores dedicados abaixo), senao toda execucao
    # normal de `make cocotb` imprimiria "ERROR:" no log - esperado/
    # intencional, mas pareceria uma falha real.
    run_isolated(
        "test_reset_state,test_geometry_with_zero_padding,test_multiple_gap_cycles,"
        "test_ready_gating_prevents_manual_gap_calculation",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "window_3x3.sv"),
        ],
        includes=[os.path.join(proj_root, "include")],
        toplevel="window_3x3",
        module="test_window_3x3",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


def test_window_3x3_contract_violation_runner():
    """Executor dedicado para test_contract_violation_detected - ver
    docstring de capture_errors()/run_isolated() em _cocotb_helpers.py
    para o porque de precisar de um executor separado (fora de uma
    corrotina @cocotb.test()) para checar isso automaticamente."""
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_window_3x3_violation")

    with capture_errors() as capture:
        run_isolated(
            "test_contract_violation_detected",
            verilog_sources=[
                os.path.join(proj_root, "rtl", "common", "window_3x3.sv"),
            ],
            includes=[os.path.join(proj_root, "include")],
            toplevel="window_3x3",
            module="test_window_3x3",
            parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH},
            compile_args=["-g2012", "-Wall"],
            sim_build=sim_build,
        )

    assert capture.found, (
        "esperava que o $error de violacao de contrato (window_3x3.sv) disparasse "
        "ao alimentar 2 linhas sem nenhum ciclo de gap entre elas, mas nenhum ERROR "
        "foi detectado no log - a asserção de simulação pode ter parado de funcionar"
    )


def test_window_3x3_sustained_violation_runner():
    """Executor dedicado para test_sustained_contract_violation_detected
    (mesma nota do executor acima)."""
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_window_3x3_sustained")

    n_rows = 5
    expected_violations = n_rows - 1  # 1 violacao por fronteira interna de linha

    with capture_errors() as capture:
        run_isolated(
            "test_sustained_contract_violation_detected",
            verilog_sources=[
                os.path.join(proj_root, "rtl", "common", "window_3x3.sv"),
            ],
            includes=[os.path.join(proj_root, "include")],
            toplevel="window_3x3",
            module="test_window_3x3",
            parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH},
            compile_args=["-g2012", "-Wall"],
            sim_build=sim_build,
        )

    assert capture.count == expected_violations, (
        f"violacao sustentada por {n_rows} linhas continuas deveria disparar exatamente "
        f"{expected_violations} ERROR (1 por fronteira interna de linha), mas contei "
        f"{capture.count} - o modulo pode ter parado de re-sincronizar corretamente "
        f"apos uma violacao"
    )


if __name__ == "__main__":
    test_window_3x3_runner()
    test_window_3x3_contract_violation_runner()
    test_window_3x3_sustained_violation_runner()
