"""Teste de profundidade/atraso de rtl/common/line_buffer_2line.sv para varios
IMG_WIDTH (Correcao read-during-write de mem1: profundidade IMG_WIDTH+1 e
leitura em wr_ptr1_next).

Objetivo: provar que a mudanca preservou o atraso de IMG_WIDTH pulsos e que
nenhum X vaza (a leitura do pulso W-1 cai numa posicao ainda nao escrita,
mascarada por warm1). Cobre W potencia de 2 (ponteiro ganha 1 bit:
$clog2(W+1) > $clog2(W)) e W nao potencia de 2.

W=1 NAO e suportado (ja nao era antes: $clog2(1)=0 gera ponteiro de largura 0).

IMG_WIDTH e parametro de COMPILACAO: cada W e uma elaboracao separada. O valor
chega as corrotinas por TEST_IMG_WIDTH (lido DENTRO delas, nunca no import: no
processo do pytest a variavel nao existe).
"""

import os
import random

import pytest

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge

from _cocotb_helpers import run_isolated

DATA_WIDTH = 8
WIDTHS = [2, 3, 4, 5, 8, 16, 640]


def _img_width() -> int:
    return int(os.environ["TEST_IMG_WIDTH"])


def _pix(i: int) -> int:
    """Pixel em 1..255 (nunca 0: distingue dado de zero-padding)."""
    return (i * 19 + 7) % 255 + 1


async def _reset(dut):
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    dut.i_tag.value = 0
    dut.i_rearm.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def _step(dut, valid: int, pixel: int, tag: int = 0, rst_n: int = 1, rearm: int = 0):
    dut.rst_n.value = rst_n
    dut.i_valid.value = valid
    dut.i_pixel.value = pixel
    dut.i_tag.value = tag
    dut.i_rearm.value = rearm
    await RisingEdge(dut.clk)
    await ReadOnly()
    out = {
        "valid": int(dut.o_valid.value),
        "curr": int(dut.o_curr.value),
        "line1": int(dut.o_line1.value),  # int() falha se houver X: detecta vazamento
        "line2": int(dut.o_line2.value),
        "curr_tag": int(dut.o_curr_tag.value),
        "line1_tag": int(dut.o_line1_tag.value),
    }
    await NextTimeStep()
    return out


@cocotb.test()
async def test_delay_continuous_stream(dut):
    """Fluxo continuo cobrindo varias voltas do ponteiro (profundidade W+1)."""
    w = _img_width()
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    n_cycles = 6 * (w + 1) + 3
    hist = []
    for t in range(n_cycles):
        pix = _pix(t)
        out = await _step(dut, valid=1, pixel=pix)
        hist.append(pix)

        exp1 = hist[t - w] if t >= w else 0
        exp2 = hist[t - 2 * w] if t >= 2 * w else 0
        assert out["valid"] == 1, f"W={w} t={t}"
        assert out["curr"] == pix, f"W={w} t={t}: curr={out['curr']} esperado={pix}"
        assert out["line1"] == exp1, f"W={w} t={t}: line1={out['line1']} esperado={exp1}"
        assert out["line2"] == exp2, f"W={w} t={t}: line2={out['line2']} esperado={exp2}"


@cocotb.test()
async def test_delay_with_gaps(dut):
    """Ciclos com i_valid=0 (gap) nao podem alterar o atraso nem o estado."""
    w = _img_width()
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    rnd = random.Random(1234 + w)

    n_real = 4 * (w + 1) + 3
    hist = []
    prev = None
    for real_t in range(n_real):
        for _ in range(rnd.randint(0, 2)):
            out = await _step(dut, valid=0, pixel=0xFF, tag=1)
            assert out["valid"] == 0, f"W={w} real_t={real_t}: o_valid em gap"
            if prev is not None:  # nenhum estado muda em gap sem rearm
                assert out["line1"] == prev["line1"], f"W={w} real_t={real_t}: line1 mudou em gap"
                assert out["line2"] == prev["line2"], f"W={w} real_t={real_t}: line2 mudou em gap"
            prev = out

        pix = _pix(real_t)
        out = await _step(dut, valid=1, pixel=pix)
        hist.append(pix)
        prev = out

        exp1 = hist[real_t - w] if real_t >= w else 0
        exp2 = hist[real_t - 2 * w] if real_t >= 2 * w else 0
        assert out["valid"] == 1
        assert out["line1"] == exp1, f"W={w} real_t={real_t}: line1={out['line1']} esperado={exp1}"
        assert out["line2"] == exp2, f"W={w} real_t={real_t}: line2={out['line2']} esperado={exp2}"


@cocotb.test()
async def test_rearm_zero_padding_each_frame(dut):
    """Com i_rearm no 1o pulso de cada frame: line1 volta a zero-padding nos
    primeiros W pulsos do frame (inclusive k=0) e depois mostra SO o frame
    atual - nunca residuo do anterior, ainda fisicamente na memoria.
    Frames de comprimentos diferentes (inclusive nao multiplo de W) mudam a fase
    do ponteiro (modulo W+1) em relacao ao inicio de cada frame.
    line2 com rearm NAO e modelado aqui (exigiria reimplementar a temporizacao
    do RTL); fica coberto por test_line_buffer_2line.py."""
    w = _img_width()
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    frame_lens = [3 * w, 2 * w + 1, 3 * w]
    offset = 0
    for f, flen in enumerate(frame_lens):
        tag = f & 1
        frame = [_pix(offset + k + 31 * f) for k in range(flen)]
        for k, pix in enumerate(frame):
            out = await _step(dut, valid=1, pixel=pix, tag=tag, rearm=1 if k == 0 else 0)
            exp1 = frame[k - w] if k >= w else 0
            assert out["line1"] == exp1, (
                f"W={w} frame={f} k={k}: line1={out['line1']} esperado={exp1}"
            )
            assert out["line1_tag"] == tag, f"W={w} frame={f} k={k}: line1_tag={out['line1_tag']}"
            assert out["curr_tag"] == tag, f"W={w} frame={f} k={k}: curr_tag={out['curr_tag']}"
        offset += flen


@cocotb.test()
async def test_midstream_reset_restarts_delay(dut):
    """Reset no meio do fluxo (mem1/mem2 NAO sao resetadas): o atraso recomeca
    do zero e nada do fluxo anterior vaza."""
    w = _img_width()
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    for t in range(2 * w + 3):
        await _step(dut, valid=1, pixel=_pix(1000 + t))

    for _ in range(3):
        out = await _step(dut, valid=0, pixel=0, rst_n=0)
        assert out["line1"] == 0 and out["line2"] == 0, f"W={w}: saida nao zerou em reset"

    n_cycles = 4 * (w + 1)
    hist = []
    for t in range(n_cycles):
        pix = _pix(t)
        out = await _step(dut, valid=1, pixel=pix, rst_n=1)
        hist.append(pix)
        exp1 = hist[t - w] if t >= w else 0
        exp2 = hist[t - 2 * w] if t >= 2 * w else 0
        assert out["line1"] == exp1, f"W={w} t={t} (pos-reset): line1={out['line1']} esperado={exp1}"
        assert out["line2"] == exp2, f"W={w} t={t} (pos-reset): line2={out['line2']} esperado={exp2}"


@pytest.mark.parametrize("w", WIDTHS, ids=lambda v: f"W{v}")
def test_line_buffer_depth_runner(w):
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    run_isolated(
        "test_delay_continuous_stream,test_delay_with_gaps,"
        "test_rearm_zero_padding_each_frame,test_midstream_reset_restarts_delay",
        verilog_sources=[os.path.join(proj_root, "rtl", "common", "line_buffer_2line.sv")],
        includes=[os.path.join(proj_root, "include")],
        toplevel="line_buffer_2line",
        module="test_line_buffer_depth",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": w},
        compile_args=["-g2012", "-Wall"],
        sim_build=os.path.join(proj_root, "sim", f"sim_build_line_buffer_depth_w{w}"),
        extra_env={"TEST_IMG_WIDTH": str(w)},
    )