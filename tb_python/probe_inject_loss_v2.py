"""Sonda v2 (Fase 2, Ressalva 3). NAO faz parte da suite normal. NAO altera RTL.
Mudancas vs v1: (1) metrica de alinhamento (delecao unica / subsequencia / LCS)
no lugar da tabela por frame; (2) faixa de D=(feed_cnt_r-win_cnt_r) mod P e
D nos instantes DRENADOS (episodios, nao ciclos); (3) stall opcional.
Todos os sinais de contagem/ocupacao sao REGISTRADORES lidos apos a mesma borda
(mesma classe de latencia) - ver ARQUITETURA_MULTICICLO.md, 6a pegadinha.
Env: TEST_IMG_WIDTH, TEST_IMG_HEIGHT, PROBE_MODE(none|I1|I2), PROBE_OFF,
PROBE_FRAMES, PROBE_STALL, PROBE_SEED.
"""
import os
from collections import Counter

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
    return [((np.arange(h * w) * (3 + f) + f * 7) % 13).reshape(h, w) for f in range(n)]


def _lcs(a, b):
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(prev[j] + 1 if x == y else max(prev[j + 1], cur[j]))
        prev = cur
    return prev[-1]


def _is_subseq(small, big):
    i = 0
    for x in big:
        if i < len(small) and small[i] == x:
            i += 1
    return i == len(small)


def _classify(outs, exp):
    if outs == exp:
        return "EXATO"
    msg = []
    if len(outs) == len(exp) - 1:
        ks = [k for k in range(len(exp)) if exp[:k] + exp[k + 1:] == outs]
        if ks:
            msg.append(f"DELECAO_UNICA k={ks[0]}..{ks[-1]} (intervalo: valores repetidos)")
    if len(outs) < len(exp) and _is_subseq(outs, exp):
        msg.append(f"SUBSEQUENCIA (faltam {len(exp) - len(outs)}, nenhum pixel errado)")
    if not msg:
        msg.append("OUTRO (nao e delecao pura)")
    msg.append(f"LCS={_lcs(outs, exp)}/{len(outs)} saidas explicadas pelo golden")
    return "; ".join(msg)


def _drained(dut):
    return (int(dut.lb_valid.value) == 0 and int(dut.win_valid.value) == 0
            and int(dut.u_lw_skid.count_r.value) == 0
            and int(dut.u_skid.skid_count_r.value) == 0
            and int(dut.u_window.phantom_pending_r.value) == 0)


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
    stall = float(os.environ.get("PROBE_STALL", "0.0"))
    seed = int(os.environ.get("PROBE_SEED", "0"))
    P = w * (h + 1)

    images = _images(w, h, nfr)
    expected = [p for im in images for p in _reference_sobel_l1(im)]
    n_sat = sum(1 for v in expected if v == 255)

    per_frame_elig = P if mode == "I1" else w * h
    log = {"fired": False}
    if mode in ("I1", "I2"):
        cocotb.start_soon(_injector(dut, mode, INJECT_FRAME * per_frame_elig + off, log))

    outs = []
    raw = {"win": 0, "real": 0}
    dmin = {"pre": None, "post": None}
    dmax = {"pre": None, "post": None}
    episodes = {"pre": Counter(), "post": Counter()}
    state = {"last": None}

    def on_cycle(cyc, i_valid, i_pixel):
        if int(dut.o_valid.value):
            outs.append(int(dut.o_pixel.value))
        if int(dut.win_valid.value):
            raw["win"] += 1
        if int(dut.win_valid_real.value):
            raw["real"] += 1
        feed = int(dut.feed_cnt_r.value)
        wc = int(dut.win_cnt_r.value)
        d = (feed - wc) % P
        ds = d if d <= P // 2 else d - P
        ph = "post" if log["fired"] else "pre"
        dmin[ph] = ds if dmin[ph] is None else min(dmin[ph], ds)
        dmax[ph] = ds if dmax[ph] is None else max(dmax[ph], ds)
        if _drained(dut):
            key = (ds, feed % w, int(dut.u_window.col_cnt_r.value))
            if key != state["last"]:           # episodio, nao ciclo (M5)
                episodes[ph][key] += 1
            state["last"] = key
        else:
            state["last"] = None

    timed_out = False
    try:
        await _feed_image_and_collect(dut, np.vstack(images), stall_prob=stall,
                                      seed=seed, on_cycle=on_cycle)
    except TimeoutError:
        timed_out = True

    await Timer(1, unit="ns")
    final_drained = _drained(dut)
    print(f"\n=== PROBE2 W={w} H={h} mode={mode} off={off} frames={nfr} "
          f"stall={stall} seed={seed} (inject no frame {INJECT_FRAME}) ===")
    print(f"fired={log['fired']} timed_out={timed_out} final_drained={final_drained} "
          f"saturadas={n_sat}/{len(expected)}")
    print(f"len(outs)={len(outs)} esperado={len(expected)}  "
          f"win_raw={raw['win']} esperado={nfr * P}  win_real={raw['real']} "
          f"esperado={nfr * w * h}")
    print(f"win_cnt_r_final={int(dut.win_cnt_r.value)} feed_cnt_r_final={int(dut.feed_cnt_r.value)}")
    print(f"ALINHAMENTO: {_classify(outs, expected)}")
    print(f"D_range pre-injecao: min={dmin['pre']} max={dmax['pre']}   "
          f"pos-injecao: min={dmin['post']} max={dmax['post']}")
    for ph in ("pre", "post"):
        viol = sum(c for (ds, fm, cc), c in episodes[ph].items() if ds != (1 if fm != 0 else 0))
        tot = sum(episodes[ph].values())
        print(f"DRENADO {ph}: episodios={tot} violam_regra(D==(feed%W!=0))={viol}")
        for key, c in sorted(episodes[ph].items()):
            print(f"   (D={key[0]}, feed%W={key[1]}, col_cnt={key[2]}) x{c}")

    if mode == "none":
        assert outs == expected, "CONTROLE falhou: sonda invalida (ou regressao do RTL)"
    else:
        assert log["fired"], "injecao nao disparou: sonda invalida"


def _runner(w, h, mode, off=0, frames=8, stall=0.0, seed=0):
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
            module="probe_inject_loss_v2",
            parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": w, "IMG_HEIGHT": h,
                        "COEFF_WIDTH": COEFF_WIDTH, "ACC_WIDTH": ACC_WIDTH},
            compile_args=["-g2012", "-Wall"],
            sim_build=os.path.join(root, "sim", f"sim_build_probe2_w{w}_h{h}"),
            extra_env={"TEST_IMG_WIDTH": str(w), "TEST_IMG_HEIGHT": str(h),
                       "PROBE_MODE": mode, "PROBE_OFF": str(off),
                       "PROBE_FRAMES": str(frames), "PROBE_STALL": str(stall),
                       "PROBE_SEED": str(seed)},
        )
    print(f"ERROR_COUNT: {cap.count}  (mode={mode} W={w} H={h} off={off} stall={stall})")
    if mode == "none":
        assert cap.count == 0


@pytest.mark.parametrize("stall", [0.0, 0.3], ids=lambda v: f"s{v}")
def test_probe2_none_w8(stall):
    _runner(8, 3, "none", stall=stall, seed=1)


# offsets I1 (P=32 amostras/frame): inicio de linha(0,8), meio(5,20), fim de linha(7), fim de frame(31)
@pytest.mark.parametrize("off", [0, 5, 7, 8, 20, 31], ids=lambda v: f"off{v}")
def test_probe2_i1_w8(off):
    _runner(8, 3, "I1", off)


# offsets I2 (24 janelas reais/frame)
@pytest.mark.parametrize("off", [0, 5, 12, 23], ids=lambda v: f"off{v}")
def test_probe2_i2_w8(off):
    _runner(8, 3, "I2", off)


def test_probe2_i1_w8_stall():
    _runner(8, 3, "I1", 5, stall=0.3, seed=1)


def test_probe2_i2_w8_stall():
    _runner(8, 3, "I2", 5, stall=0.3, seed=1)