"""Sonda D1-b (NAO faz parte da suite; nome probe_*, rodar explicitamente, depois
arquivar em diagnosticos/). NAO altera RTL. NAO executada por quem escreveu.

Confere, no RTL REAL de line_buffer_2line (isolado, i_rearm=0), o contrato que o modelo
da Camada 2 assume para o sideband `last` (hipotese: usar a porta i_tag):
  - apos um pulso valido com i_tag=T, no ciclo seguinte o_curr_tag == T, junto de o_curr/o_valid;
  - nos buracos (i_valid=0) o_curr_tag fica MANTIDO no ultimo valor valido, mesmo com i_tag
    mudando livremente (veneno) durante o buraco.
Modo canario (PROBE_CANARY=1): espera o comportamento ERRADO (tag acompanha i_tag ao vivo
no buraco) e EXIGE que haja divergencia; se nao houver, a sonda e vazia.
Imprime o numero de verificacoes (verificacao vazia nao prova nada).

Uso (de tb_python/):  python3 -m pytest probe_lb_last_sideband.py -v -s
"""
import os
import random

import pytest

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge

from _cocotb_helpers import run_isolated

DATA_WIDTH = 8


def _w() -> int:
    return int(os.environ["TEST_IMG_WIDTH"])


def _pix(g: int) -> int:
    return (g * 37 + 11) % 255 + 1


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


async def _step(dut, valid: int, pixel: int, tag: int):
    dut.i_valid.value = valid
    dut.i_pixel.value = pixel
    dut.i_tag.value = tag
    dut.i_rearm.value = 0
    await RisingEdge(dut.clk)
    await ReadOnly()
    out = {
        "valid": int(dut.o_valid.value),
        "curr": int(dut.o_curr.value),          # int() falha se houver X
        "curr_tag": int(dut.o_curr_tag.value),
    }
    await NextTimeStep()
    return out


def _gap_schedule(w: int, rnd: random.Random):
    gaps = [0] * (3 * w + 4)
    gaps += [(rnd.randint(1, 6) if rnd.random() < 0.4 else 0) for _ in range(4 * w + 6)]
    gaps += [(0 if (i % 11) < 7 else rnd.randint(2, 6)) for i in range(4 * w + 6)]
    long_at = {0, w - 1, w, w + 1, 2 * w, 2 * w + 1, 3 * w}
    gaps += [(3 * w + 5 if i in long_at else 0) for i in range(4 * w)]
    gaps[-1] = 10 * w
    return gaps


@cocotb.test()
async def probe_lb_last_sideband(dut):
    w = _w()
    canary = os.environ.get("PROBE_CANARY") == "1"
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    rnd = random.Random(4321 + w)

    held_tag = 0                       # estado pos-reset
    n_pulses = n_gap_cycles = n_tag1_pulses = n_gap_live_differs = 0
    mismatches = []
    g = 0

    def check(out, exp, tag_name):
        for k in ("valid", "curr", "curr_tag"):
            if out[k] != exp[k] and len(mismatches) < 8:
                mismatches.append((tag_name, k, out[k], exp[k]))
            elif out[k] != exp[k]:
                mismatches.append(None)

    last_curr = 0
    for gap in _gap_schedule(w, rnd):
        for _ in range(gap):
            live = rnd.randint(0, 1)                      # veneno: tag aleatoria no buraco
            if live != held_tag:
                n_gap_live_differs += 1                   # buraco que DISTINGUE hold de live
            exp_tag = live if canary else held_tag        # canario: modelo errado (live)
            out = await _step(dut, 0, 0xFF, live)
            check(out, {"valid": 0, "curr": last_curr, "curr_tag": exp_tag}, f"gap@pulso{g}")
            n_gap_cycles += 1

        tag = 1 if (g % (w + 1) == w or rnd.random() < 0.15) else 0
        p = _pix(g)
        held_tag, last_curr = tag, p
        n_tag1_pulses += tag
        out = await _step(dut, 1, p, tag)
        check(out, {"valid": 1, "curr": p, "curr_tag": tag}, f"pulso{g}")
        g += 1
        n_pulses += 1

    n_bad = len(mismatches)
    print(f"\nPROBE_LB_LAST W={w} canary={canary}: pulsos={n_pulses} (com tag=1: {n_tag1_pulses}) "
          f"ciclos_de_buraco={n_gap_cycles} (live!=held em {n_gap_live_differs}) "
          f"divergencias={n_bad}")
    for m in [x for x in mismatches if x][:8]:
        print(f"  DIVERGENCIA {m}  (onde, campo, obtido, esperado)")

    assert n_pulses > 0 and n_gap_cycles > 0 and n_tag1_pulses > 0, "verificacao vazia"
    assert n_gap_live_differs > 0, "VAZIA: nenhum buraco distingue hold de live"
    if canary:
        assert n_bad > 0, "CANARIO nao detectou diferenca: sonda nao distingue hold de live"
        print("RESULT: PASS (canario morde)")
    else:
        assert n_bad == 0, f"{n_bad} divergencias no contrato de o_curr_tag"
        print("RESULT: PASS")


def _runner(w, canary):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    run_isolated(
        "probe_lb_last_sideband",
        verilog_sources=[os.path.join(root, "rtl", "common", "line_buffer_2line.sv")],
        includes=[os.path.join(root, "include")],
        toplevel="line_buffer_2line",
        module="probe_lb_last_sideband",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": w},
        compile_args=["-g2012", "-Wall"],
        sim_build=os.path.join(root, "sim", f"sim_build_probe_lb_last_w{w}{'_canary' if canary else ''}"),
        extra_env={"TEST_IMG_WIDTH": str(w), "PROBE_CANARY": "1" if canary else "0"},
    )


@pytest.mark.parametrize("w", [2, 3, 4, 5, 8, 16], ids=lambda v: f"W{v}")
def test_probe_lb_last_sideband_runner(w):
    _runner(w, canary=False)


@pytest.mark.parametrize("w", [4, 8], ids=lambda v: f"W{v}")
def test_probe_lb_last_sideband_canary_runner(w):
    _runner(w, canary=True)