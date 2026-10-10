"""Teste de aceite de o_status (Ressalva 3 da Auditoria 01), sobre o RTL REAL.

Criterios (aprovados no desenho):
  1. Controles (sem injecao) -> o_status == 0, 0 $error, e as verificacoes
     NAO sao vazias (drained_d e e2_check ocorrem varias vezes - licao R5:
     "0 violacoes" so vale se houve verificacoes).
  2. I1 (perda de 1 amostra a montante de window_3x3)  -> bit2 (D), so ele.
  3. B  (perda de 1 janela a jusante)                  -> bit1 (E2), so ele.
  4. C  (duplicacao: pop nao contabilizado)            -> bit1 (E2) aceso
     (outros bits nao sao afirmados: nos casos de C o ponto de injecao
     perturba o controle de admissao, ver Fase 2).
  5. E1 (overflow): teste de FIACAO - forca o_overflow de u_skid / u_lw_skid
     por 1 ciclo e confere o bit0. O overflow GENUINO de cada modulo e
     coberto pelos testes unitarios (test_skid_fifo2.py, test_line_window_skid.py).
  6. Reset limpa o flag (sticky so cai com reset).
  7. Cada bit aceso gera exatamente 1 $error de localizacao.

Injecao por Force/Release em NETS INTERNOS (nunca portas de modulo: a Fase 2
mostrou que Force em porta vaza para a rede externa), exceto no teste E1, onde
o vazamento da porta para o net do topo e justamente o que se quer exercitar.
Nao altera RTL. Reusa _feed_image_and_collect (nunca laco de conducao proprio).
"""

import os

import numpy as np
import pytest

import cocotb
from cocotb.clock import Clock
from cocotb.handle import Force, Release
from cocotb.triggers import FallingEdge, NextTimeStep, ReadOnly, RisingEdge, Timer

from _cocotb_helpers import run_isolated
from test_sobel_multicycle import _feed_image_and_collect, _reference_sobel_l1

DATA_WIDTH, COEFF_WIDTH, ACC_WIDTH = 8, 3, 11
INJECT_FRAME = 2
DRAIN_CYCLES = 150


def _images(w, h, n):
    # baixo contraste real (pixels em [0,12] => |Gx|+|Gy| <= 96 < 255)
    return [((np.arange(h * w) * (3 + f) + f * 7) % 13).reshape(h, w) for f in range(n)]


async def _injector(dut, mode, target, log):
    if mode in ("E1S", "E1L"):
        sig = dut.u_skid.o_overflow if mode == "E1S" else dut.u_lw_skid.o_overflow
        for _ in range(target):  # target = ciclo de disparo
            await FallingEdge(dut.clk)
        sig.set(Force(1))
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        sig.set(Release())
        log["fired"] = True
        return
    n = 0
    while True:
        await FallingEdge(dut.clk)
        sig = {"B": dut.u_skid.skid_push_accepted, "C": dut.u_skid.skid_pop,
               "I1": dut.u_window.i_valid}[mode]
        if not int(sig.value):
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
async def status_probe(dut):
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
    stall = float(os.environ.get("PROBE_STALL", "0.0"))
    seed = int(os.environ.get("PROBE_SEED", "0"))
    expect_exact = os.environ.get("EXPECT_EXACT")        # mascara exata, ou None
    expect_set = int(os.environ.get("EXPECT_SET", "0"))  # bits que DEVEM estar acesos
    P = w * (h + 1)

    images = _images(w, h, nfr)
    expected = [p for im in images for p in _reference_sobel_l1(im)]
    assert sum(1 for v in expected if v == 255) == 0, "massa saturou: teste invalido"

    per_frame_elig = P if mode == "I1" else w * h
    target = off if mode in ("E1S", "E1L") else INJECT_FRAME * per_frame_elig + off
    log = {"fired": False}
    if mode != "none":
        cocotb.start_soon(_injector(dut, mode, target, log))

    outs = []
    cnt = {"drained": 0, "e2": 0}

    def sample():
        if int(dut.o_valid.value):
            outs.append(int(dut.o_pixel.value))
        cnt["drained"] += int(dut.drained_d.value)
        cnt["e2"] += int(dut.e2_check.value)

    timed_out = False
    try:
        await _feed_image_and_collect(dut, np.vstack(images), stall_prob=stall, seed=seed,
                                      on_cycle=lambda cyc, iv, ip: sample())
    except TimeoutError:
        timed_out = True
    for _ in range(DRAIN_CYCLES):  # so leitura, mesma posicao de amostragem do helper
        await ReadOnly()
        sample()
        await NextTimeStep()
        await RisingEdge(dut.clk)

    await ReadOnly()
    status = int(dut.o_status.value)
    await NextTimeStep()
    print(f"\n=== STATUS W={w} H={h} mode={mode} off={off} frames={nfr} stall={stall}: "
          f"o_status={status:03b} fired={log['fired']} timed_out={timed_out} "
          f"len(outs)={len(outs)}/{len(expected)} verif_drained={cnt['drained']} "
          f"verif_e2={cnt['e2']} ===")

    if mode == "none":
        assert outs == expected, "CONTROLE: saida diverge do golden (sonda invalida ou regressao)"
        assert status == 0, f"FALSO POSITIVO no controle: o_status={status:03b}"
        assert cnt["drained"] > 0 and cnt["e2"] > 0, "verificacoes vazias: controle nao prova nada"
    else:
        assert log["fired"], "injecao nao disparou: teste invalido"
        if expect_exact is not None:
            assert status == int(expect_exact, 2), (
                f"esperado o_status={expect_exact}, obtido={status:03b}")
        assert (status & expect_set) == expect_set, (
            f"bits esperados {expect_set:03b} nao acesos: o_status={status:03b}")

    if os.environ.get("CHECK_RESET") == "1":
        assert status != 0, "pre-condicao do teste de reset: flag deveria estar aceso"
        dut.rst_n.value = 0
        for _ in range(3):
            await RisingEdge(dut.clk)
        dut.rst_n.value = 1
        await RisingEdge(dut.clk)
        await ReadOnly()
        assert int(dut.o_status.value) == 0, "reset nao limpou o_status"
        await NextTimeStep()


def _runner(w, h, mode, off=0, frames=8, stall=0.0, seed=0, exact=None, must=0,
            expect_errors=0, check_reset=False):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {"TEST_IMG_WIDTH": str(w), "TEST_IMG_HEIGHT": str(h), "PROBE_MODE": mode,
           "PROBE_OFF": str(off), "PROBE_FRAMES": str(frames), "PROBE_STALL": str(stall),
           "PROBE_SEED": str(seed), "EXPECT_SET": str(must),
           "CHECK_RESET": "1" if check_reset else "0"}
    if exact is not None:
        env["EXPECT_EXACT"] = exact
    # expect_errors: contagem EXATA de $error de localizacao (1 por bit aceso do
    # o_status) + os do proprio modulo que transborda, no caso do teste E1.
    run_isolated(
        "status_probe",
        verilog_sources=[os.path.join(root, "rtl", d, f) for d, f in [
            ("common", "line_buffer_2line.sv"), ("common", "window_3x3.sv"),
            ("common", "line_window_skid.sv"), ("common", "abs_saturate.sv"),
            ("common", "magnitude_l1.sv"), ("multicycle", "mac_unit.sv"),
            ("multicycle", "kernel_rom.sv"), ("multicycle", "mac_control_fsm.sv"),
            ("multicycle", "skid_fifo2.sv"), ("multicycle", "sobel_multicycle.sv")]],
        includes=[os.path.join(root, "include")],
        toplevel="sobel_multicycle",
        module="test_pipeline_status",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": w, "IMG_HEIGHT": h,
                    "COEFF_WIDTH": COEFF_WIDTH, "ACC_WIDTH": ACC_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=os.path.join(root, "sim", f"sim_build_status_w{w}_h{h}"),
        extra_env=env,
        expect_errors=expect_errors,
    )


# --- 1. controles -----------------------------------------------------------
@pytest.mark.parametrize("w,h,frames,stall", [
    (8, 3, 8, 0.0), (8, 3, 8, 0.3), (8, 3, 8, 0.8), (6, 5, 6, 0.3), (320, 3, 2, 0.0), (320, 3, 2, 0.3),
], ids=lambda v: str(v))
def test_status_control_silent(w, h, frames, stall):
    _runner(w, h, "none", frames=frames, stall=stall, seed=1)


# --- 2. I1 -> bit2, so ele (medido na Fase 2/v3: E2 nao acende em I1) ---------
@pytest.mark.parametrize("off", [5, 8], ids=lambda v: f"off{v}")
def test_status_I1_sets_bit2(off):
    _runner(8, 3, "I1", off, exact="100", expect_errors=1)


# --- 3. B -> bit1, so ele ---------------------------------------------------
@pytest.mark.parametrize("off", [0, 5, 12, 23], ids=lambda v: f"off{v}")
def test_status_B_sets_bit1(off):
    _runner(8, 3, "B", off, exact="010", expect_errors=1)


def test_status_B_stall_sets_bit1():
    _runner(8, 3, "B", 5, stall=0.3, seed=1, exact="010", expect_errors=1)


# --- 4. C -> bit1 aceso (demais nao afirmados) ------------------------------
@pytest.mark.parametrize("off", [0, 12], ids=lambda v: f"off{v}")
def test_status_C_sets_bit1(off):
    _runner(8, 3, "C", off, must=0b010, expect_errors=1)


def test_status_C_stall_sets_bit1():
    _runner(8, 3, "C", 5, stall=0.3, seed=1, must=0b010, expect_errors=1)


# --- 5. E1: fiacao (overflow genuino coberto nos testes unitarios) ----------
def test_status_E1_wiring_u_skid():
    _runner(8, 3, "E1S", 300, frames=2, exact="001", expect_errors=2)


def test_status_E1_wiring_u_lw_skid():
    _runner(8, 3, "E1L", 300, frames=2, exact="001", expect_errors=2)


# --- 6. reset limpa ----------------------------------------------------------
def test_status_reset_clears_flag():
    _runner(8, 3, "B", 5, exact="010", expect_errors=1, check_reset=True)
