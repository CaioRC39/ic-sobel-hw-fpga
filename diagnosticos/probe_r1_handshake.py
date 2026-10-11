"""Sonda R1 v2 (Ressalva 1). NAO faz parte da suite normal. NAO altera RTL.
Modos (PROBE_MODE):
  rbv  : CONTROLE - ready-before-valid. Deve = golden, blocked=0.
  hold : R1a - valid levantado e MANTIDO (dado estavel) ate valid&&ready. Deve = golden, o_status=0.
  fire : R1b - pulso de 1 ciclo a cada PROBE_PERIOD ciclos, IGNORANDO ready (ja medido; nao precisa repetir).
PROBE_PAIRS="stall:seed,stall:seed" restringe/reordena os lotes (padrao: STALL_CONFIGS).
v2: NENHUM await entre lotes (a v1 inseria ReadOnly+NextTimeStep entre lotes, o que desloca o
driver em meio ciclo e o faz escrever i_valid no instante da borda). o_status e lido DENTRO do laco.
Transferencia = valid && ready decididos no MESMO ponto de amostragem (o_ready nao depende de i_valid).
"""
import os
import random

import numpy as np
import pytest

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge

from _cocotb_helpers import run_isolated
from test_sobel_multicycle import _reference_sobel_l1

DATA_WIDTH, COEFF_WIDTH, ACC_WIDTH, N_FRAMES = 8, 3, 11, 4
STALL_CONFIGS = [(0.0, 0), (0.3, 1), (0.3, 42), (0.6, 7), (0.8, 3)]


def _configs():
    raw = os.environ.get("PROBE_PAIRS")
    if not raw:
        return STALL_CONFIGS
    return [(float(a), int(b)) for a, b in (p.split(":") for p in raw.split(","))]


def _images(w, h):
    # baixo contraste real: pixels em [0,12] => |Gx|+|Gy| <= 96 < 255
    return [((np.arange(h * w) * (3 + f) + f * 7) % 13).reshape(h, w) for f in range(N_FRAMES)]


async def _drive(dut, flat, n_expected, mode, stall, seed, period, drain):
    rnd = random.Random(seed)
    idx, pend, cyc, done_cyc = 0, False, 0, None
    collected = []
    st = {"offered": 0, "transfers": 0, "blocked": 0, "lost": 0, "status": 0, "timeout": False}
    max_cycles = (60 + period) * len(flat) + 4000
    while True:
        await ReadOnly()
        ready = int(dut.o_ready.value)
        st["status"] |= int(dut.o_status.value)
        if int(dut.o_valid.value):
            collected.append(int(dut.o_pixel.value))
        await NextTimeStep()

        valid, data = 0, 0
        if mode == "rbv":
            if ready and idx < len(flat) and rnd.random() >= stall:
                valid, data = 1, flat[idx]
                idx += 1
                st["offered"] += 1
                st["transfers"] += 1
        elif mode == "hold":
            if not pend and idx < len(flat) and rnd.random() >= stall:
                pend = True
                st["offered"] += 1
            if pend:
                valid, data = 1, flat[idx]
                if ready:
                    st["transfers"] += 1
                    pend = False
                    idx += 1
                else:
                    st["blocked"] += 1      # valid=1 com o_ready=0, dado mantido
        else:  # fire
            if idx < len(flat) and cyc % period == 0:
                valid, data = 1, flat[idx]
                idx += 1
                st["offered"] += 1
                if ready:
                    st["transfers"] += 1
                else:
                    st["lost"] += 1

        dut.i_valid.value = valid
        dut.i_pixel.value = data
        await RisingEdge(dut.clk)
        cyc += 1
        if cyc > max_cycles:
            st["timeout"] = True
            break
        if idx >= len(flat) and not pend:
            if mode in ("rbv", "hold"):
                if len(collected) >= n_expected:
                    break
            else:
                if done_cyc is None:
                    done_cyc = cyc
                if len(collected) >= n_expected or cyc - done_cyc > drain:
                    break
    dut.i_valid.value = 0
    return collected, st


@cocotb.test()
async def r1_probe(dut):
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
    period = int(os.environ.get("PROBE_PERIOD", "1"))
    drain = 30 * (w + 4) + 200
    configs = _configs() if mode != "fire" else [(0.0, 0)]
    tot_blocked = 0

    for batch, (stall, seed) in enumerate(configs):
        images = _images(w, h)
        expected = [p for im in images for p in _reference_sobel_l1(im)]
        assert sum(1 for v in expected if v == 255) == 0, "massa saturou: teste invalido"
        flat = np.vstack(images).flatten().tolist()

        collected, st = await _drive(dut, flat, len(expected), mode, stall, seed, period, drain)

        first_div = next((i for i, (g, e) in enumerate(zip(collected, expected)) if g != e), None)
        print(f"\n=== R1 W={w} H={h} mode={mode} lote={batch} stall={stall} seed={seed} "
              f"1o_sorteio={random.Random(seed).random():.3f} period={period}: "
              f"offered={st['offered']}/{len(flat)} transfers={st['transfers']} "
              f"blocked(valid&&!ready)={st['blocked']} lost={st['lost']} "
              f"len(outs)={len(collected)}/{len(expected)} 1a_divergencia={first_div} "
              f"timeout={st['timeout']} o_status={st['status']:03b} ===")

        if mode in ("rbv", "hold"):
            assert not st["timeout"], "timeout: saidas nao completaram"
            assert st["transfers"] == len(flat), "nem todos os pixels foram aceitos"
            assert collected == expected, "saida diverge do golden"
            assert st["status"] == 0, f"o_status={st['status']:03b} (esperado 000)"
            if mode == "rbv":
                assert st["blocked"] == 0, "controle invalido: rbv nao deveria bloquear"
            tot_blocked += st["blocked"]

    if mode == "hold":
        assert tot_blocked > 0, "VAZIO: a condicao valid&&!ready nunca ocorreu"
        print(f"=== R1a RESUMO W={w} H={h}: lotes={len(configs)} "
              f"ciclos valid&&!ready exercitados = {tot_blocked} ===")


def _runner(w, h, mode, period=1, pairs=None):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {"TEST_IMG_WIDTH": str(w), "TEST_IMG_HEIGHT": str(h),
           "PROBE_MODE": mode, "PROBE_PERIOD": str(period)}
    if pairs:
        env["PROBE_PAIRS"] = pairs
    run_isolated(
        "r1_probe",
        verilog_sources=[os.path.join(root, "rtl", d, f) for d, f in [
            ("common", "line_buffer_2line.sv"), ("common", "window_3x3.sv"),
            ("common", "line_window_skid.sv"), ("common", "abs_saturate.sv"),
            ("common", "magnitude_l1.sv"), ("multicycle", "mac_unit.sv"),
            ("multicycle", "kernel_rom.sv"), ("multicycle", "mac_control_fsm.sv"),
            ("multicycle", "skid_fifo2.sv"), ("multicycle", "sobel_multicycle.sv")]],
        includes=[os.path.join(root, "include")],
        toplevel="sobel_multicycle",
        module="probe_r1_handshake",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": w, "IMG_HEIGHT": h,
                    "COEFF_WIDTH": COEFF_WIDTH, "ACC_WIDTH": ACC_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=os.path.join(root, "sim", f"sim_build_r1_{mode}_w{w}_h{h}_p{period}"),
        extra_env=env,
    )


@pytest.mark.parametrize("w,h", [(4, 3), (8, 3)], ids=lambda v: str(v))
def test_r1_control_rbv(w, h):
    _runner(w, h, "rbv")


@pytest.mark.parametrize("w,h", [(4, 1), (4, 3), (6, 2), (8, 3), (8, 5)], ids=lambda v: str(v))
def test_r1a_hold(w, h):
    _runner(w, h, "hold")


def test_r1a_hold_pair42_isolated():
    """Par (0.3,42) como unico lote, logo apos o reset."""
    _runner(4, 3, "hold", pairs="0.3:42")


@pytest.mark.parametrize("period", [1, 8, 16, 24], ids=lambda v: f"p{v}")
def test_r1b_fire(period):
    _runner(8, 3, "fire", period=period)