"""Sonda O8 v2 (item 8). NAO faz parte da suite normal. NAO altera RTL.
Mede a OCUPACAO REAL de u_skid (skid_fifo2, prof. 2) e u_lw_skid (line_window_skid, DEPTH=2),
ciclo a ciclo, via on_cycle no helper validado. Todos os sinais lidos sao registradores ou fios
derivados de registradores, amostrados no mesmo ponto (pos-borda, ReadOnly) = estado do ciclo N.
v2: NENHUM await entre lotes no modo normal; o_status lido dentro do on_cycle (OR acumulado).
PROBE_PAIRS="stall:seed,..." restringe/reordena os lotes.
CANARIO (PROBE_LEGACY_GAP=1): reinsere entre lotes o gap da v1 (ReadOnly + NextTimeStep) e EXIGE
que a falha apareca no lote PROBE_EXPECT_FAIL_AT. Se nao aparecer, a hipotese de "meio ciclo de
fase" esta REFUTADA.
"""
import os
import random
from collections import Counter

import numpy as np
import pytest

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge

from _cocotb_helpers import run_isolated
from test_sobel_multicycle import _feed_image_and_collect, _reference_sobel_l1

DATA_WIDTH, COEFF_WIDTH, ACC_WIDTH, N_FRAMES = 8, 3, 11, 4
STALL_CONFIGS = [(0.0, 0), (0.3, 1), (0.3, 42), (0.6, 7), (0.8, 3)]
CAP = 2


def _configs():
    raw = os.environ.get("PROBE_PAIRS")
    if not raw:
        return STALL_CONFIGS
    return [(float(a), int(b)) for a, b in (p.split(":") for p in raw.split(","))]


def _images(w, h):
    return [((np.arange(h * w) * (3 + f) + f * 7) % 13).reshape(h, w) for f in range(N_FRAMES)]


@cocotb.test()
async def o8_probe(dut):
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
    legacy = os.environ.get("PROBE_LEGACY_GAP") == "1"
    expect_fail_at = int(os.environ.get("PROBE_EXPECT_FAIL_AT", "-1"))
    g_sk, g_lw = Counter(), Counter()
    g_ovf = 0
    reproduced = None

    for batch, (stall, seed) in enumerate(_configs()):
        images = _images(w, h)
        expected = [p for im in images for p in _reference_sobel_l1(im)]
        assert sum(1 for v in expected if v == 255) == 0, "massa saturou: teste invalido"
        sk, lw = Counter(), Counter()
        acc = {"ovf": 0, "status": 0}

        def on_cycle(cyc, i_valid, i_pixel):
            sk[int(dut.u_skid.skid_count_r.value)] += 1
            lw[int(dut.u_lw_skid.count_r.value)] += 1
            acc["ovf"] += int(dut.u_skid.o_overflow.value) + int(dut.u_lw_skid.o_overflow.value)
            acc["status"] |= int(dut.o_status.value)

        failed = None
        collected = None
        try:
            collected = await _feed_image_and_collect(
                dut, np.vstack(images), stall_prob=stall, seed=seed, on_cycle=on_cycle)
            if collected != expected:
                failed = "divergencia"
        except TimeoutError:
            failed = "timeout"

        g_sk.update(sk)
        g_lw.update(lw)
        g_ovf += acc["ovf"]
        print(f"\n=== O8 W={w} H={h} lote={batch} stall={stall} seed={seed} "
              f"1o_sorteio={random.Random(seed).random():.3f} legacy={legacy}: "
              f"falha={failed} max_u_skid={max(sk)} max_u_lw_skid={max(lw)} overflow={acc['ovf']} "
              f"hist_u_skid={dict(sorted(sk.items()))} hist_u_lw_skid={dict(sorted(lw.items()))} "
              f"o_status={acc['status']:03b} ===")

        if legacy:
            if failed:
                reproduced = (batch, failed)
                break
            await ReadOnly()                # <<< gap da v1, so no canario
            _ = int(dut.o_status.value)
            await NextTimeStep()
        else:
            assert failed is None, f"lote {batch}: falha={failed}"
            assert acc["status"] == 0, f"lote {batch}: o_status={acc['status']:03b}"
            assert acc["ovf"] == 0, f"lote {batch}: overflow={acc['ovf']}"
            assert max(sk) <= CAP and max(lw) <= CAP, f"lote {batch}: ocupacao acima da profundidade"

    if legacy:
        assert reproduced is not None, (
            "CANARIO NAO reproduziu a falha: hipotese de fase de meio ciclo REFUTADA")
        print(f"=== CANARIO REPRODUZIU a falha no lote {reproduced[0]} ({reproduced[1]}) ===")
        assert reproduced[0] == expect_fail_at, (
            f"falha no lote {reproduced[0]}, previsto {expect_fail_at}: previsao parcialmente refutada")
    else:
        print(f"\n=== O8 RESUMO W={w} H={h}: max_u_skid={max(g_sk)} (ciclos count=2: {g_sk.get(2, 0)}) "
              f"max_u_lw_skid={max(g_lw)} (ciclos count=2: {g_lw.get(2, 0)}) overflow_total={g_ovf} ===")


def _runner(w, h, pairs=None, legacy=False, expect_fail_at=None):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {"TEST_IMG_WIDTH": str(w), "TEST_IMG_HEIGHT": str(h)}
    if pairs:
        env["PROBE_PAIRS"] = pairs
    if legacy:
        env["PROBE_LEGACY_GAP"] = "1"
        env["PROBE_EXPECT_FAIL_AT"] = str(expect_fail_at)
    run_isolated(
        "o8_probe",
        verilog_sources=[os.path.join(root, "rtl", d, f) for d, f in [
            ("common", "line_buffer_2line.sv"), ("common", "window_3x3.sv"),
            ("common", "line_window_skid.sv"), ("common", "abs_saturate.sv"),
            ("common", "magnitude_l1.sv"), ("multicycle", "mac_unit.sv"),
            ("multicycle", "kernel_rom.sv"), ("multicycle", "mac_control_fsm.sv"),
            ("multicycle", "skid_fifo2.sv"), ("multicycle", "sobel_multicycle.sv")]],
        includes=[os.path.join(root, "include")],
        toplevel="sobel_multicycle",
        module="probe_o8_occupancy",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": w, "IMG_HEIGHT": h,
                    "COEFF_WIDTH": COEFF_WIDTH, "ACC_WIDTH": ACC_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=os.path.join(root, "sim", f"sim_build_o8_w{w}_h{h}"),
        extra_env=env,
    )


@pytest.mark.parametrize("w,h", [(4, 1), (4, 3), (6, 2), (8, 3), (8, 5), (16, 3), (64, 3)],
                         ids=lambda v: str(v))
def test_o8_occupancy(w, h):
    _runner(w, h)


def test_o8_pair42_isolated():
    _runner(4, 3, pairs="0.3:42")


def test_o8_canary_legacy_gap_default():
    """Sequencia original: falha prevista no lote 2 (seed 42)."""
    _runner(4, 3, legacy=True, expect_fail_at=2)


def test_o8_canary_legacy_gap_pair42_second():
    """seed 42 como lote 1: falha prevista no lote 1 (depende do sorteio, nao da posicao)."""
    _runner(4, 3, pairs="0.0:0,0.3:42", legacy=True, expect_fail_at=1)