"""Aceite F-17 ampliado (Opcao 2: contador ciclico por ordem de janela).
NAO altera RTL. Cobre as ressalvas 2 (stall externo) e 4 (IMG_HEIGHT
variavel) de RESUMO_ESTADO_PROJETO.md, secao 'Achado F-17'.

IMG_WIDTH e IMG_HEIGHT sao parametros de COMPILACAO: cada par (W,H) e
uma elaboracao separada (env TEST_IMG_WIDTH/TEST_IMG_HEIGHT). Dentro de
cada simulacao, a lista STALL_CONFIGS roda em sequencia SEM reset entre
lotes (deliberado: exercita o contador ciclico por muitos frames).
Reusa _feed_image_and_collect ja validado (sem laco de conducao proprio).
"""
import os

import numpy as np
import pytest

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from _cocotb_helpers import run_isolated
from test_sobel_multicycle import _feed_image_and_collect, _reference_sobel_l1

DATA_WIDTH, COEFF_WIDTH, ACC_WIDTH, N_FRAMES = 8, 3, 11, 4

# (stall_prob, seed) - 0.0 e o caso sem pausas; os demais, pausas irregulares
STALL_CONFIGS = [(0.0, 0), (0.3, 1), (0.3, 42), (0.6, 7), (0.8, 3)]


def _images(w, h):
    # baixo contraste real: pixels em [0,12] => |Gx|+|Gy| <= 96 < 255
    return [
        ((np.arange(h * w) * (3 + f) + f * 7) % 13).reshape(h, w)
        for f in range(N_FRAMES)
    ]


@cocotb.test()
async def test_f17_extended(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    w = int(os.environ.get("TEST_IMG_WIDTH", "4"))
    h = int(os.environ.get("TEST_IMG_HEIGHT", "3"))

    for batch, (stall, seed) in enumerate(STALL_CONFIGS):
        images = _images(w, h)
        expected = [p for im in images for p in _reference_sobel_l1(im)]
        n_sat = sum(1 for v in expected if v == 255)
        assert n_sat == 0, f"massa saturou ({n_sat}) - nao serve como regressao"

        stats = {"real": 0, "real_geom0": 0}

        def on_cycle(cyc, i_valid, i_pixel):
            if int(dut.win_valid_real.value):
                stats["real"] += 1
            if (int(dut.win_valid.value) and not int(dut.win_is_spurious.value)
                    and not int(dut.u_window.o_window_valid_geom.value)):
                stats["real_geom0"] += 1

        collected = await _feed_image_and_collect(
            dut, np.vstack(images), stall_prob=stall, seed=seed, on_cycle=on_cycle)

        tag = f"W={w} H={h} lote={batch} stall={stall} seed={seed}"
        print(f"\n=== {tag}: win_valid_real={stats['real']} "
              f"(esperado {N_FRAMES*h*w}); reais com geom=0: {stats['real_geom0']}; "
              f"saturadas: {n_sat}/{len(expected)} ===")

        assert stats["real_geom0"] == 0, f"{tag}: gate geom descartou janela real"
        assert stats["real"] == N_FRAMES * h * w, f"{tag}: contagem de win_valid_real errada"
        assert len(collected) == len(expected), (
            f"{tag}: len(collected)={len(collected)} != {len(expected)}")
        if collected != expected:
            i = next(k for k, (g, e) in enumerate(zip(collected, expected)) if g != e)
            fr, rem = divmod(i, h * w)
            r, c = divmod(rem, w)
            raise AssertionError(
                f"{tag}: 1a divergencia idx={i} (frame={fr+1}, linha={r}, col={c}): "
                f"obtido={collected[i]} esperado={expected[i]}")


def _runner(w, h):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    run_isolated(
        "test_f17_extended",
        verilog_sources=[os.path.join(root, "rtl", d, f) for d, f in [
            ("common", "line_buffer_2line.sv"), ("common", "window_3x3.sv"),
            ("common", "line_window_skid.sv"), ("common", "abs_saturate.sv"),
            ("common", "magnitude_l1.sv"), ("multicycle", "mac_unit.sv"),
            ("multicycle", "kernel_rom.sv"), ("multicycle", "mac_control_fsm.sv"),
            ("multicycle", "skid_fifo2.sv"), ("multicycle", "sobel_multicycle.sv")]],
        includes=[os.path.join(root, "include")],
        toplevel="sobel_multicycle",
        module="test_f17_cyclic_discard",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": w, "IMG_HEIGHT": h,
                    "COEFF_WIDTH": COEFF_WIDTH, "ACC_WIDTH": ACC_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=os.path.join(root, "sim", f"sim_build_f17_w{w}_h{h}"),
        extra_env={"TEST_IMG_WIDTH": str(w), "TEST_IMG_HEIGHT": str(h)},
    )


@pytest.mark.parametrize("h", [2, 3, 5], ids=lambda v: f"H{v}")
@pytest.mark.parametrize("w", [4, 6, 8], ids=lambda v: f"W{v}")
def test_f17_extended_runner(w, h):
    _runner(w, h)


@pytest.mark.parametrize("w", [4, 6, 8], ids=lambda v: f"W{v}")
def test_f17_degenerate_h1_runner(w):
    """H=1 (Acao A-07): caso degenerado, sem evidencia previa - se falhar,
    e informacao nova sobre o RTL, nao erro do teste."""
    _runner(w, 1)