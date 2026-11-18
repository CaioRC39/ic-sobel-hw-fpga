"""Sonda D1-a (NAO faz parte da suite; nome probe_*, rodar explicitamente, depois
arquivar em diagnosticos/). NAO altera RTL. NAO executada por quem escreveu.

Confere, no RTL REAL de line_buffer_2line (isolado, i_rearm=0, i_tag=0), o contrato que o
modelo da Camada 2 ASSUME: estado so avanca em i_valid=1; apos o pulso g: curr=pix[g],
line1=pix[g-W] (0 se g<W), line2=pix[g-2W] (0 se g<2W), valid=1 no ciclo seguinte;
nos buracos valid=0 e curr/line1/line2 ficam MANTIDOS. Padroes: sem buraco, Bernoulli,
rajadas e buracos LONGOS (3W+5 a 10W) em pontos criticos (limite de aquecimento, voltas
do ponteiro). Padrao de leitura = _step de test_line_buffer_2line.py (pos-borda, ReadOnly).
Imprime o numero de verificacoes (verificacao vazia nao prova nada).

Uso (de tb_python/):  python3 -m pytest probe_lb_gap_contract.py -v -s
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
    return (g * 37 + 11) % 255 + 1          # 1..255, nunca 0 (distingue dado de padding)


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


async def _step(dut, valid: int, pixel: int):
    dut.i_valid.value = valid
    dut.i_pixel.value = pixel
    dut.i_tag.value = 0
    dut.i_rearm.value = 0
    await RisingEdge(dut.clk)
    await ReadOnly()
    out = {
        "valid": int(dut.o_valid.value),
        "curr": int(dut.o_curr.value),      # int() falha se houver X
        "line1": int(dut.o_line1.value),
        "line2": int(dut.o_line2.value),
    }
    await NextTimeStep()
    return out


def _gap_schedule(w: int, rnd: random.Random):
    """Lista de buracos ANTES de cada pulso, concatenando 4 trechos."""
    gaps = [0] * (3 * w + 4)                                            # A: sem buraco
    gaps += [(rnd.randint(1, 6) if rnd.random() < 0.4 else 0) for _ in range(4 * w + 6)]  # B
    gaps += [(0 if (i % 11) < 7 else rnd.randint(2, 6)) for i in range(4 * w + 6)]        # C
    long_at = {0, w - 1, w, w + 1, 2 * w, 2 * w + 1, 3 * w}             # D: buracos longos
    gaps += [(3 * w + 5 if i in long_at else 0) for i in range(4 * w)]
    gaps[-1] = 10 * w
    return gaps


@cocotb.test()
async def probe_lb_gap_contract(dut):
    w = _w()
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    rnd = random.Random(1234 + w)

    hist = []
    exp = {"valid": 0, "curr": 0, "line1": 0, "line2": 0}   # estado pos-reset
    n_pulses = n_gap_cycles = n_hold_checked = max_gap = 0
    mismatches = []

    def check(out, tag):
        for k in ("valid", "curr", "line1", "line2"):
            if out[k] != exp[k] and len(mismatches) < 8:
                mismatches.append((tag, k, out[k], exp[k]))

    for gap in _gap_schedule(w, rnd):
        for _ in range(gap):                                 # buraco: nada avanca
            exp["valid"] = 0                                 # curr/line1/line2 MANTIDOS
            out = await _step(dut, 0, 0xFF)                  # pixel de lixo no buraco
            check(out, f"gap@pulso{n_pulses}")
            n_gap_cycles += 1
            n_hold_checked += 1
        max_gap = max(max_gap, gap)

        g = len(hist)
        p = _pix(g)
        hist.append(p)
        exp = {"valid": 1, "curr": p,
               "line1": hist[g - w] if g >= w else 0,
               "line2": hist[g - 2 * w] if g >= 2 * w else 0}
        out = await _step(dut, 1, p)
        check(out, f"pulso{g}")
        n_pulses += 1

    print(f"\nPROBE_LB_GAP W={w}: pulsos={n_pulses} ciclos_de_buraco={n_gap_cycles} "
          f"(hold conferido em {n_hold_checked}) maior_buraco={max_gap} "
          f"divergencias={len(mismatches)}")
    for m in mismatches:
        print(f"  DIVERGENCIA {m}  (tag, campo, obtido, esperado)")
    print(f"RESULT: {'PASS' if not mismatches else 'FAIL'}")

    assert n_pulses > 0 and n_gap_cycles > 0, "verificacao vazia"
    assert not mismatches, f"{len(mismatches)} divergencias do contrato do line_buffer_2line"


@pytest.mark.parametrize("w", [2, 3, 4, 5, 8, 16], ids=lambda v: f"W{v}")
def test_probe_lb_gap_contract_runner(w):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    run_isolated(
        "probe_lb_gap_contract",
        verilog_sources=[os.path.join(root, "rtl", "common", "line_buffer_2line.sv")],
        includes=[os.path.join(root, "include")],
        toplevel="line_buffer_2line",
        module="probe_lb_gap_contract",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": w},
        compile_args=["-g2012", "-Wall"],
        sim_build=os.path.join(root, "sim", f"sim_build_probe_lb_gap_w{w}"),
        extra_env={"TEST_IMG_WIDTH": str(w)},
    )