"""Simulacao funcional POS-SINTESE (netlist .vo do Quartus, Cyclone V) no Questa.

NAO faz parte da suite normal: so roda com NETLIST=<caminho do .vo> (senao os
runners sao pulados e `make cocotb` no Icarus nao e afetado).

Objetivo: provar, na netlist, que a correcao do read-during-write de mem1
(profundidade IMG_WIDTH+1, leitura em wr_ptr1_next) entrega o atraso correto
mesmo com o M10K em new_data_no_nbe_read.

A netlist tem IMG_WIDTH fixo (640) e IMG_HEIGHT fixo; um frame inteiro e inviavel
em gate-level. O teste alimenta POSTSYNTH_ROWS linhas (padrao 3) e compara as
(ROWS-1) primeiras linhas de saida (linha r precisa da entrada r+1; as linhas
>= ROWS-1 dependeriam de linhas nao alimentadas), independente de IMG_HEIGHT.
Com ROWS=3 ha 2 voltas do ponteiro de profundidade 641 e mem2 e exercitada.

So portas sao usadas (clk, rst_n, i_valid, i_pixel, o_ready, o_valid, o_pixel,
o_status): a hierarquia interna da netlist e achatada/renomeada.
"""

import os

import numpy as np
import pytest

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge

from _cocotb_helpers import run_isolated
from test_sobel_multicycle import _feed_image_and_collect, _reference_sobel_l1
from test_valid_hold_handshake import _drive_hold

NETLIST = os.environ.get("NETLIST")


def _cfg():
    w = int(os.environ.get("POSTSYNTH_IMG_WIDTH", "640"))
    rows = int(os.environ.get("POSTSYNTH_ROWS", "3"))
    assert rows >= 2, "POSTSYNTH_ROWS deve ser >= 2 (a saida da linha 0 precisa da entrada da linha 1)"
    return w, rows


def _make_image(rows, w):
    # baixo contraste real: pixels em [0,12] => |Gx|+|Gy| <= 96 < 255 (sem saturacao)
    rng = np.random.RandomState(12345)
    return rng.randint(0, 13, size=(rows, w))


def _golden(img):
    """Saidas das linhas 0..rows-2 (as unicas independentes de linhas nao alimentadas)."""
    rows, w = img.shape
    exp = _reference_sobel_l1(img)[: (rows - 1) * w]
    n_sat = sum(1 for v in exp if v == 255)
    assert n_sat == 0, f"massa saturou ({n_sat}): teste invalido"
    assert len(set(exp)) > 3, "golden quase constante: nao detectaria erro de atraso"
    return exp


def _compare(tag, collected, exp, w):
    assert len(collected) == len(exp), f"{tag}: len(collected)={len(collected)} != {len(exp)}"
    if collected != exp:
        i = next(k for k, (g, e) in enumerate(zip(collected, exp)) if g != e)
        n_bad = sum(1 for g, e in zip(collected, exp) if g != e)
        r, c = divmod(i, w)
        raise AssertionError(
            f"{tag}: {n_bad}/{len(exp)} pixels divergem; 1a divergencia idx={i} "
            f"(linha={r}, col={c}): obtido={collected[i]} esperado={exp[i]}"
        )


async def _reset(dut):
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


@cocotb.test()
async def test_ps_reset_state(dut):
    """Smoke test: o cocotb sobe no Questa, a netlist sai do reset sem X nas portas."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    await ReadOnly()
    assert int(dut.o_ready.value) == 1, "apos reset, o_ready deveria ser 1"
    assert int(dut.o_valid.value) == 0
    assert int(dut.o_status.value) == 0
    await NextTimeStep()


@cocotb.test()
async def test_ps_partial_frame_golden(dut):
    """Sem stall externo: ROWS linhas de baixo contraste contra o golden."""
    w, rows = _cfg()
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    img = _make_image(rows, w)
    exp = _golden(img)
    acc = {"status": 0}

    def on_cycle(cyc, i_valid, i_pixel):
        acc["status"] |= int(dut.o_status.value)

    collected = await _feed_image_and_collect(
        dut, img, stall_prob=0.0, seed=0, on_cycle=on_cycle, n_expected=len(exp))
    print(f"\n=== POSTSYNTH golden W={w} ROWS={rows}: len(outs)={len(collected)}/{len(exp)} "
          f"o_status={acc['status']:03b} ===")
    _compare(f"W={w} ROWS={rows} stall=0.0", collected, exp, w)
    assert acc["status"] == 0, f"o_status={acc['status']:03b} (esperado 000)"


@cocotb.test()
async def test_ps_external_stalls(dut):
    """Com pausas externas irregulares (ritmo de escrita/leitura de mem1 irregular)."""
    w, rows = _cfg()
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    img = _make_image(rows, w)
    exp = _golden(img)
    acc = {"status": 0}

    def on_cycle(cyc, i_valid, i_pixel):
        acc["status"] |= int(dut.o_status.value)

    collected = await _feed_image_and_collect(
        dut, img, stall_prob=0.3, seed=42, on_cycle=on_cycle, n_expected=len(exp))
    _compare(f"W={w} ROWS={rows} stall=0.3 seed=42", collected, exp, w)
    assert acc["status"] == 0, f"o_status={acc['status']:03b} (esperado 000)"


@cocotb.test()
async def test_ps_valid_hold(dut):
    """Contrato A (valid mantido ate ver o_ready): reaproveita _drive_hold."""
    w, rows = _cfg()
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    img = _make_image(rows, w)
    exp = _golden(img)
    flat = img.flatten().tolist()
    collected, st = await _drive_hold(dut, flat, len(exp), 0.3, 42)
    print(f"\n=== POSTSYNTH hold W={w}: transfers={st['transfers']}/{len(flat)} "
          f"blocked={st['blocked']} o_status={st['status']:03b} ===")
    assert st["transfers"] == len(flat), "nem todos os pixels foram aceitos"
    assert st["blocked"] > 0, "VAZIO: valid&&!ready nunca ocorreu"
    _compare(f"W={w} ROWS={rows} hold", collected[: len(exp)], exp, w)
    assert st["status"] == 0, f"o_status={st['status']:03b} (esperado 000)"


@pytest.mark.skipif(not NETLIST, reason="defina NETLIST=<caminho do .vo> para rodar no Questa")
def test_postsynth_runner(monkeypatch):
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    monkeypatch.setenv("SIM", "questa")
    run_isolated(
        "test_ps_reset_state,test_ps_partial_frame_golden,"
        "test_ps_external_stalls,test_ps_valid_hold",
        verilog_sources=[os.path.abspath(NETLIST)],
        toplevel="sobel_multicycle",
        module="test_postsynth_sobel",
        # SEM parameters=: IMG_WIDTH/IMG_HEIGHT ja foram fixados na sintese
        sim_args=["-L", "altera_mf_ver", "-L", "altera_ver", "-L", "altera_lnsim_ver",
                  "-L", "cyclonev_ver", "-voptargs=+acc"],
        sim_build=os.path.join(proj_root, "sim", "sim_build_postsynth"),
        extra_env={k: os.environ[k] for k in ("POSTSYNTH_IMG_WIDTH", "POSTSYNTH_ROWS")
                   if k in os.environ},
    )