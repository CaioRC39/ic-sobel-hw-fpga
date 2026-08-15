"""Testbench cocotb para rtl/common/window_3x3.sv, incluindo a
Alternativa 3-B (i_curr_tag/i_line1_tag/i_line2_tag -> o_tag +
o_window_valid_geom).

Regressao: os testes de geometria/gap/o_ready ja existentes antes da
3-B sao repetidos aqui com as 3 tags de entrada fixas em 0 (1 unico
frame o tempo todo), confirmando que a adicao nao alterou nenhum
comportamento existente (mudanca estritamente aditiva) - inclusive
confirmando que o_window_valid_geom fica 1 em TODO ciclo o_valid=1
nesse cenario de frame unico (nenhuma contaminacao possivel).

Testes novos (3-B): a razao de existir do mecanismo - detectar quando
a janela contem amostras de mais de 1 frame (o_window_valid_geom=0), e
confirmar que o_tag reflete a tag da linha central (i_line1), conforme
a convencao de centralizacao ja documentada no cabecalho do RTL.
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
    h, w = image.shape
    padded = np.pad(image, 1, mode="constant", constant_values=0)
    windows = []
    for out_row in range(h - 1):
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
    dut.i_curr_tag.value = 0
    dut.i_line1_tag.value = 0
    dut.i_line2_tag.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


def _unpack_window(raw: int):
    mask = (1 << DATA_WIDTH) - 1
    window = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
    for r in range(3):
        for c in range(3):
            k = 3 * r + c
            shift = (8 - k) * DATA_WIDTH
            window[r][c] = (raw >> shift) & mask
    return window


async def _step(dut, valid: int, curr: int, line1: int, line2: int,
                 curr_tag: int = 0, line1_tag: int = 0, line2_tag: int = 0):
    dut.i_valid.value = valid
    dut.i_curr.value = curr
    dut.i_line1.value = line1
    dut.i_line2.value = line2
    dut.i_curr_tag.value = curr_tag
    dut.i_line1_tag.value = line1_tag
    dut.i_line2_tag.value = line2_tag
    await RisingEdge(dut.clk)
    await ReadOnly()
    out_valid = int(dut.o_valid.value)
    out_window = _unpack_window(int(dut.o_window.value)) if out_valid else None
    out_tag = int(dut.o_tag.value) if out_valid else None
    out_valid_geom = int(dut.o_window_valid_geom.value) if out_valid else None
    await NextTimeStep()
    return out_valid, out_window, out_tag, out_valid_geom


@cocotb.test()
async def test_reset_state(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    await ReadOnly()
    assert dut.o_valid.value == 0
    await NextTimeStep()


@cocotb.test()
async def test_geometry_with_zero_padding(dut):
    """Regressao: geometria identica ao comportamento pre-3B (tags=0
    fixas, 1 unico frame) - alem disso, confirma o_window_valid_geom=1
    em TODO ciclo capturado (nenhuma fronteira de frame no cenario)."""
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
            out_valid, out_window, out_tag, out_vg = await _step(
                dut, 1, curr, line1, line2, curr_tag=0, line1_tag=0, line2_tag=0
            )
            if out_valid:
                captured.append(out_window)
                assert out_vg == 1, "1 unico frame (tags=0) - janela nunca deveria ser impura"
                assert out_tag == 0

        out_valid, out_window, out_tag, out_vg = await _step(dut, 0, 0, 0, 0)
        if out_valid:
            captured.append(out_window)
            assert out_vg == 1

    captured = captured[IMG_WIDTH:]

    assert len(captured) == len(expected)
    for idx, (got, exp) in enumerate(zip(captured, expected)):
        assert got == exp, f"idx={idx}: obtido={got} esperado={exp}"


@cocotb.test()
async def test_contract_violation_detected(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    for row in range(2):
        for col in range(IMG_WIDTH):
            await _step(dut, 1, curr=row * 10 + col, line1=0, line2=0)


# -----------------------------------------------------------------------
# Testes novos - Alternativa 3-B (o_window_valid_geom / o_tag)
# -----------------------------------------------------------------------

@cocotb.test()
async def test_o_tag_reflects_center_row(dut):
    """o_tag deve refletir a tag da linha CENTRAL da janela (i_line1),
    nunca i_curr nem i_line2 - mesma convencao de centralizacao ja
    documentada no cabecalho do modulo ('a janela emitida ... esta
    CENTRADA na linha de i_line1'). Usa 3 tags DIFERENTES entre si
    simultaneamente (curr=1, line1=0, line2=1) para garantir que o
    teste falharia se o_tag acidentalmente refletisse curr ou line2 em
    vez de line1."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    for col in range(IMG_WIDTH):  # 1 linha inteira, sem violar o contrato de gap
        out_valid, _, out_tag, _ = await _step(
            dut, 1, curr=col, line1=col, line2=col,
            curr_tag=1, line1_tag=0, line2_tag=1,
        )
        if out_valid:
            assert out_tag == 0, (
                f"col={col}: o_tag deveria refletir i_line1_tag (0), "
                f"nao i_curr_tag/i_line2_tag (1); obtido={out_tag}"
            )


@cocotb.test()
async def test_window_valid_geom_detects_vertical_frame_boundary(dut):
    """Cenario central da Alternativa 3-B: line_buffer_2line entrega,
    num dado ciclo, 3 linhas que NAO pertencem todas ao mesmo frame
    (ex: i_curr/i_line1 ja do frame novo, mas i_line2 ainda contem o
    residuo do frame anterior - exatamente a causa raiz do Achado F-02,
    contaminacao de fronteira vertical entre frames). Alimenta uma
    janela onde curr_tag=line1_tag=1 (frame novo) mas line2_tag=0
    (frame antigo, ainda "preso" na memoria) - o_window_valid_geom deve
    cair para 0 assim que essa amostra contaminada entra na janela, e
    voltar a 1 assim que ela sai (desliza para fora do shift-register)."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    # Preenche 1a linha inteira com tag=1 uniforme (janela ainda nao
    # "fechada" - primeiras IMG_WIDTH amostras, sem historico vertical).
    for col in range(IMG_WIDTH):
        await _step(dut, 1, curr=100 + col, line1=0, line2=0,
                    curr_tag=1, line1_tag=1, line2_tag=1)
    await _step(dut, 0, 0, 0, 0)  # gap obrigatorio entre linhas

    # 2a linha: 1 UNICA coluna contaminada (line2_tag=0, "residuo" do
    # frame anterior) no meio da linha - todas as outras colunas dessa
    # linha sao puras (tag=1 em todas as 3 posicoes).
    contaminated_col = 3
    results = []
    for col in range(IMG_WIDTH):
        line2_tag = 0 if col == contaminated_col else 1
        out_valid, _, _, out_vg = await _step(
            dut, 1, curr=200 + col, line1=100 + col, line2=0,
            curr_tag=1, line1_tag=1, line2_tag=line2_tag,
        )
        if out_valid:
            results.append(out_vg)

    # A amostra contaminada entra na janela em sr_row0_r[0] no ciclo em
    # que col==contaminated_col, e so sai do shift-register (posicao 2,
    # a mais antiga) 2 colunas depois - portanto o_window_valid_geom
    # deve cair para 0 em EXATAMENTE 3 janelas consecutivas (a
    # contaminada entrando na posicao mais nova, ficando 1 ciclo no
    # meio, e saindo pela posicao mais antiga), nao em nenhuma outra.
    zeros = [i for i, v in enumerate(results) if v == 0]
    assert len(zeros) == 3, (
        f"esperava exatamente 3 janelas com o_window_valid_geom=0 "
        f"(a amostra contaminada atravessando as 3 posicoes do shift "
        f"register da linha 0), obtido {len(zeros)}: indices {zeros} "
        f"(resultados completos: {results})"
    )
    # As 3 janelas contaminadas devem ser consecutivas (a amostra
    # atravessa o shift register em 3 ciclos seguidos, nao espalhados).
    assert zeros == list(range(zeros[0], zeros[0] + 3)), (
        f"as janelas invalidas deveriam ser consecutivas, obtido {zeros}"
    )


@cocotb.test()
async def test_phantom_cycle_does_not_spuriously_invalidate_geom(dut):
    """O ciclo fantasma da borda direita (zero de padding) NUNCA
    deveria, por si so, derrubar o_window_valid_geom - ele representa
    borda DENTRO do mesmo frame (ver cabecalho do RTL). Alimenta 1
    linha inteira com tag=1 uniforme e confirma que a janela do ciclo
    fantasma (a ultima capturada nesta linha) continua com
    o_window_valid_geom=1."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    results = []
    for col in range(IMG_WIDTH):
        out_valid, _, _, out_vg = await _step(
            dut, 1, curr=col, line1=col, line2=col,
            curr_tag=1, line1_tag=1, line2_tag=1,
        )
        if out_valid:
            results.append(out_vg)
    # ciclo fantasma: i_valid=0, mas ainda produz 1 o_valid (ver phantom_pending_r)
    out_valid, _, _, out_vg = await _step(dut, 0, 0, 0, 0)
    assert out_valid == 1, "ciclo fantasma deveria produzir o_valid=1 (comportamento pre-existente)"
    results.append(out_vg)

    assert all(v == 1 for v in results), (
        f"nenhuma janela deveria ser invalida (1 unico frame, tag=1 uniforme, "
        f"incluindo o ciclo fantasma) - resultados: {results}"
    )


def test_window_3x3_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_window_3x3")

    run_isolated(
        "test_reset_state,test_geometry_with_zero_padding,"
        "test_o_tag_reflects_center_row,"
        "test_window_valid_geom_detects_vertical_frame_boundary,"
        "test_phantom_cycle_does_not_spuriously_invalidate_geom",
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
        "esperava que o $error de violacao de contrato disparasse, mas nao disparou"
    )


if __name__ == "__main__":
    test_window_3x3_runner()
    test_window_3x3_contract_violation_runner()
