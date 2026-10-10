"""Sonda de injecao de perda (Fase 2, Ressalva 3). NAO faz parte da suite
normal (nome probe_*, rodar explicitamente). NAO altera RTL: usa
Force/Release do cocotb 2.0 em sinais internos.

I1: perde 1 amostra A MONTANTE de window_3x3 (u_window.i_valid forcado a 0).
I2: perde 1 janela A JUSANTE (u_skid.i_push forcado a 0).
none: controle (assert: saida == golden, 0 $error).
Env: TEST_IMG_WIDTH, TEST_IMG_HEIGHT, PROBE_MODE, PROBE_OFF, PROBE_FRAMES.
"""
import os

import numpy as np
import pytest

import cocotb
from cocotb.clock import Clock
from cocotb.handle import Force, Release
from cocotb.triggers import FallingEdge, RisingEdge, Timer

from _cocotb_helpers import capture_errors, run_isolated
from test_sobel_multicycle import _feed_image_and_collect, _reference_sobel_l1

DATA_WIDTH, COEFF_WIDTH, ACC_WIDTH = 8, 3, 11
INJECT_FRAME = 2


def _images(w, h, n):
    # baixo contraste real: pixels em [0,12] => |Gx|+|Gy| <= 96
    return [((np.arange(h * w) * (3 + f) + f * 7) % 13).reshape(h, w) for f in range(n)]


async def _injector(dut, mode, target, log):
    n = 0
    while True:
        await FallingEdge(dut.clk)
        if mode == "I1":
            sig, elig = dut.u_window.i_valid, int(dut.u_window.i_valid.value)
        else:
            sig, elig = dut.u_skid.i_push, int(dut.win_valid_real.value)
        if not elig:
            continue
        if n == target:
            sig.set(Force(0))
            await RisingEdge(dut.clk)
            await Timer(1, unit="ns")
            sig.set(Release())
            log["fired"] = True
            return
        n += 1


@cocotb.test()
async def probe(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    w = int(os.environ["TEST_IMG_WIDTH"])
    h = int(os.environ["TEST_IMG_HEIGHT"])
    mode = os.environ["PROBE_MODE"]
    off = int(os.environ.get("PROBE_OFF", "0"))
    nfr = int(os.environ.get("PROBE_FRAMES", "8"))
    npf = w * h

    images = _images(w, h, nfr)
    exp_frames = [_reference_sobel_l1(im) for im in images]
    expected = [p for fr in exp_frames for p in fr]
    n_sat = sum(1 for v in expected if v == 255)

    per_frame_elig = w * (h + 1) if mode == "I1" else w * h
    log = {"fired": False}
    if mode in ("I1", "I2"):
        cocotb.start_soon(_injector(dut, mode, INJECT_FRAME * per_frame_elig + off, log))

    outs, raw = [], {"win": 0}

    def on_cycle(cyc, i_valid, i_pixel):
        if int(dut.o_valid.value):
            outs.append(int(dut.o_pixel.value))
        if int(dut.win_valid.value):
            raw["win"] += 1

    timed_out = False
    try:
        await _feed_image_and_collect(dut, np.vstack(images), stall_prob=0.0,
                                      seed=0, on_cycle=on_cycle)
    except TimeoutError:
        timed_out = True

    first_div = next((i for i, (g, e) in enumerate(zip(outs, expected)) if g != e), None)
    print(f"\n=== PROBE W={w} H={h} mode={mode} off={off} frames={nfr} "
          f"(inject em frame {INJECT_FRAME}) ===")
    print(f"fired={log['fired']} timed_out={timed_out} saturadas={n_sat}/{len(expected)}")
    print(f"len(outs)={len(outs)} esperado={len(expected)}  "
          f"win_valid_raw={raw['win']} esperado={nfr * w * (h + 1)}")
    print(f"win_cnt_r_final={int(dut.win_cnt_r.value)} (0 = alinhado)  "
          f"feed_cnt_r_final={int(dut.feed_cnt_r.value)}  primeira_divergencia_global={first_div}")
    print("frame  len  pixels_errados")
    for f in range(nfr):
        got = outs[f * npf:(f + 1) * npf]
        exp = exp_frames[f]
        mism = sum(1 for g, e in zip(got, exp) if g != e) + max(0, len(exp) - len(got))
        print(f"  {f:3d}  {len(got):3d}  {mism}{'   <- inject' if f == INJECT_FRAME else ''}")

    if mode == "none":
        assert outs == expected, "CONTROLE falhou: sonda invalida (ou regressao do RTL)"
    else:
        assert log["fired"], "injecao nao disparou: alvo nao alcancado, sonda invalida"


def _runner(w, h, mode, off=0, frames=8):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with capture_errors() as cap:
        run_isolated(
            "probe",
            verilog_sources=[os.path.join(root, "rtl", d, f) for d, f in [
                ("common", "line_buffer_2line.sv"), ("common", "window_3x3.sv"),
                ("common", "line_window_skid.sv"), ("common", "abs_saturate.sv"),
                ("common", "magnitude_l1.sv"), ("multicycle", "mac_unit.sv"),
                ("multicycle", "kernel_rom.sv"), ("multicycle", "mac_control_fsm.sv"),
                ("multicycle", "skid_fifo2.sv"), ("multicycle", "sobel_multicycle.sv")]],
            includes=[os.path.join(root, "include")],
            toplevel="sobel_multicycle",
            module="probe_inject_loss",
            parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": w, "IMG_HEIGHT": h,
                        "COEFF_WIDTH": COEFF_WIDTH, "ACC_WIDTH": ACC_WIDTH},
            compile_args=["-g2012", "-Wall"],
            sim_build=os.path.join(root, "sim", f"sim_build_probe_w{w}_h{h}"),
            extra_env={"TEST_IMG_WIDTH": str(w), "TEST_IMG_HEIGHT": str(h),
                       "PROBE_MODE": mode, "PROBE_OFF": str(off),
                       "PROBE_FRAMES": str(frames)},
        )
    print(f"ERROR_COUNT: {cap.count}  (mode={mode} W={w} H={h} off={off})")
    if mode == "none":
        assert cap.count == 0


def test_probe_none_w4():
    _runner(4, 3, "none")


@pytest.mark.parametrize("off", [0, 1, 3, 4, 6, 9, 12, 15], ids=lambda v: f"off{v}")
def test_probe_i1_w4(off):
    _runner(4, 3, "I1", off)


@pytest.mark.parametrize("off", [0, 1, 3, 4, 7, 11], ids=lambda v: f"off{v}")
def test_probe_i2_w4(off):
    _runner(4, 3, "I2", off)


# Re-medicao de largura (item 4/5): controle sem injecao, 2 frames.
# Pode demorar (tempo NAO medido por mim).
@pytest.mark.parametrize("w", [320, 640], ids=lambda v: f"W{v}")
def test_probe_none_large(w):
    _runner(w, 3, "none", frames=2)