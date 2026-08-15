"""Testbench cocotb para rtl/common/line_buffer_2line.sv, incluindo a
Alternativa 3-B (tag de proveniencia i_tag -> o_curr_tag/o_line1_tag/
o_line2_tag).

Regressao: os testes de geometria/atraso do pixel (ja existentes antes
da 3-B) sao repetidos aqui com i_tag=0 fixo, confirmando que a adicao
da tag nao alterou nenhum comportamento existente do pixel (mudanca
estritamente aditiva).

Testes novos (3-B): confirmam que a tag sofre EXATAMENTE o mesmo atraso
que o pixel correspondente (lockstep), inclusive atravessando uma
fronteira de frame simulada (tag alternando de valor no meio do
stream) - e a razao de existir da Alternativa 3-B.
"""

import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge
from cocotb_test.simulator import run

DATA_WIDTH = 8
IMG_WIDTH = 6


async def _reset(dut):
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    dut.i_tag.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def _step(dut, valid: int, pixel: int, tag: int = 0, rst_n: int = 1):
    dut.rst_n.value = rst_n
    dut.i_valid.value = valid
    dut.i_pixel.value = pixel
    dut.i_tag.value = tag
    await RisingEdge(dut.clk)
    await ReadOnly()
    out = {
        "valid": int(dut.o_valid.value),
        "curr": int(dut.o_curr.value),
        "line1": int(dut.o_line1.value),
        "line2": int(dut.o_line2.value),
        "curr_tag": int(dut.o_curr_tag.value),
        "line1_tag": int(dut.o_line1_tag.value),
        "line2_tag": int(dut.o_line2_tag.value),
    }
    await NextTimeStep()
    return out


@cocotb.test()
async def test_reset_state(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    await ReadOnly()
    assert dut.o_curr.value == 0
    assert dut.o_line1.value == 0
    assert dut.o_line2.value == 0
    assert dut.o_curr_tag.value == 0
    assert dut.o_line1_tag.value == 0
    assert dut.o_line2_tag.value == 0
    await NextTimeStep()


@cocotb.test()
async def test_delay_and_zero_padding(dut):
    """Regressao (i_tag=0 fixo): geometria/atraso do pixel identicos
    ao comportamento pre-3B."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    n_cycles = 5 * IMG_WIDTH
    pixels = [(i * 7 + 3) % 256 for i in range(n_cycles)]

    history = []
    for t, pix in enumerate(pixels):
        out = await _step(dut, valid=1, pixel=pix, tag=0)
        history.append(pix)

        exp_curr = pix
        exp_line1 = history[t - IMG_WIDTH] if t >= IMG_WIDTH else 0
        exp_line2 = history[t - 2 * IMG_WIDTH] if t >= 2 * IMG_WIDTH else 0

        assert out["valid"] == 1
        assert out["curr"] == exp_curr
        assert out["line1"] == exp_line1
        assert out["line2"] == exp_line2


@cocotb.test()
async def test_ignores_invalid_cycles(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    random.seed(1234)

    n_real_pixels = 4 * IMG_WIDTH
    history = []
    real_t = 0
    for _ in range(n_real_pixels):
        for _ in range(random.randint(0, 2)):
            out = await _step(dut, valid=0, pixel=0xFF, tag=1)  # tag=1 "lixo", nao deveria contaminar
            assert out["valid"] == 0

        pix = (real_t * 13 + 5) % 256
        out = await _step(dut, valid=1, pixel=pix, tag=0)

        history.append(pix)
        exp_line1 = history[real_t - IMG_WIDTH] if real_t >= IMG_WIDTH else 0
        exp_line2 = history[real_t - 2 * IMG_WIDTH] if real_t >= 2 * IMG_WIDTH else 0

        assert out["valid"] == 1
        assert out["curr"] == pix
        assert out["line1"] == exp_line1
        assert out["line2"] == exp_line2
        real_t += 1


@cocotb.test()
async def test_midstream_reset(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    for t in range(10):
        await _step(dut, valid=1, pixel=50 + t, tag=0)

    for _ in range(3):
        out = await _step(dut, valid=0, pixel=0, tag=0, rst_n=0)
        assert out["curr"] == 0
        assert out["line1"] == 0
        assert out["line2"] == 0
        assert out["curr_tag"] == 0
        assert out["line1_tag"] == 0
        assert out["line2_tag"] == 0

    history = []
    for t in range(4 * IMG_WIDTH):
        out = await _step(dut, valid=1, pixel=200 + t, tag=0, rst_n=1)
        history.append(200 + t)
        exp_line1 = history[t - IMG_WIDTH] if t >= IMG_WIDTH else 0
        exp_line2 = history[t - 2 * IMG_WIDTH] if t >= 2 * IMG_WIDTH else 0
        assert out["curr"] == 200 + t
        assert out["line1"] == exp_line1
        assert out["line2"] == exp_line2


# -----------------------------------------------------------------------
# Testes novos - Alternativa 3-B (tag de proveniencia)
# -----------------------------------------------------------------------

@cocotb.test()
async def test_tag_constant_within_frame_always_matches(dut):
    """Uso REALISTA da tag (contrato explicito no cabecalho do modulo:
    o integrador alterna i_tag APENAS a cada inicio de frame, nunca no
    meio de um frame): com i_tag constante do inicio ao fim do teste,
    o_curr_tag/o_line1_tag/o_line2_tag devem refletir esse valor em
    TODO ciclo com o_valid=1, inclusive durante os 2*IMG_WIDTH ciclos
    iniciais de zero-padding (onde o pixel ainda nao e dado real, mas
    a tag - constante - ja e trivialmente correta em qualquer leitura,
    seja do "ramo nao-aquecido" (i_tag da vez) ou do "ramo aquecido"
    (tag empacotada, escrita numa passada anterior AINDA dentro do
    mesmo frame)."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    n_cycles = 6 * IMG_WIDTH
    for t in range(n_cycles):
        out = await _step(dut, valid=1, pixel=(t * 11 + 1) % 256, tag=1)
        assert out["curr_tag"] == 1, f"t={t}"
        assert out["line1_tag"] == 1, f"t={t}"
        assert out["line2_tag"] == 1, f"t={t}"


@cocotb.test()
async def test_tag_lockstep_across_3_frame_boundaries(dut):
    """Extensao de test_tag_survives_frame_boundary_in_memory para 3
    fronteiras de frame consecutivas (tag alternando 0/1/0), provando
    que o mecanismo de empacotamento (mem1/mem2) nao acumula nenhum
    residuo entre trocas repetidas de frame - so a Regra de Processo/
    Alternativa 6 do RESUMO_ESTADO_PROJETO.md (3+ frames consecutivos)
    aplicada aqui no nivel deste modulo, antes de existir um
    sobel_multicycle.sv completo para testar em nivel de sistema."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    frame_len = 3 * IMG_WIDTH
    frame_tags = [0, 1, 0]
    hist_pix, hist_tag = [], []
    gt = 0

    for tag in frame_tags:
        for _ in range(frame_len):
            pix = (gt * 7 + 3) % 256
            out = await _step(dut, valid=1, pixel=pix, tag=tag)
            hist_pix.append(pix)
            hist_tag.append(tag)

            assert out["curr_tag"] == tag, f"gt={gt}"
            if gt >= IMG_WIDTH:
                assert out["line1_tag"] == hist_tag[gt - IMG_WIDTH], f"gt={gt}"
            if gt >= 2 * IMG_WIDTH:
                assert out["line2_tag"] == hist_tag[gt - 2 * IMG_WIDTH], f"gt={gt}"
            gt += 1


@cocotb.test()
async def test_tag_survives_frame_boundary_in_memory(dut):
    """Cenario central da Alternativa 3-B: 2 frames consecutivos, tag=0
    no 1o e tag=1 no 2o. o_line1_tag/o_line2_tag devem continuar
    refletindo a tag do frame de ORIGEM de cada amostra armazenada -
    inclusive logo apos a transicao, quando a memoria ainda contem
    dado do frame anterior (tag=0) mas o stream de entrada ja esta no
    frame novo (tag=1). E exatamente essa discrepancia que
    window_3x3.o_window_valid_geom precisa enxergar a jusante."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    frame1_len = 3 * IMG_WIDTH
    frame2_len = 3 * IMG_WIDTH
    hist_pix, hist_tag = [], []

    for t in range(frame1_len):
        pix = (t * 3 + 1) % 256
        out = await _step(dut, valid=1, pixel=pix, tag=0)
        hist_pix.append(pix)
        hist_tag.append(0)
        assert out["curr_tag"] == 0

    for t in range(frame2_len):
        gt = frame1_len + t
        pix = (t * 5 + 2) % 256
        out = await _step(dut, valid=1, pixel=pix, tag=1)
        hist_pix.append(pix)
        hist_tag.append(1)

        exp_line1_tag = hist_tag[gt - IMG_WIDTH]
        exp_line2_tag = hist_tag[gt - 2 * IMG_WIDTH]

        assert out["curr_tag"] == 1
        assert out["line1_tag"] == exp_line1_tag, (
            f"t(global)={gt}: line1_tag deveria refletir o frame de ORIGEM "
            f"da amostra armazenada ha IMG_WIDTH ciclos (esperado={exp_line1_tag}), "
            f"obtido={out['line1_tag']}"
        )
        assert out["line2_tag"] == exp_line2_tag, f"t(global)={gt}"


def test_line_buffer_2line_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_line_buffer_2line")

    run(
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "line_buffer_2line.sv"),
        ],
        includes=[os.path.join(proj_root, "include")],
        toplevel="line_buffer_2line",
        module="test_line_buffer_2line",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


if __name__ == "__main__":
    test_line_buffer_2line_runner()
