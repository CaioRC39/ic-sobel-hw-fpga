"""Sonda v3 (Fase 2, checagem extra para I2). NAO faz parte da suite normal.
NAO altera RTL. Modelos de flag (so observacao, nada e implementado no RTL):
  E2: b (registrador) += win_valid_real - o_valid; quando fsm_ready && !fsm_i_valid,
      b deve ser 0. Flag sticky.
  D : regra do I1 (v2): drenado => D == (feed_cnt_r % W != 0). Flag sticky.
  E1: o_overflow de u_skid e u_lw_skid (contagem).
Injecao por Force em NETS INTERNOS de skid_fifo2 (nao portas):
  B = perda   (u_skid.skid_push_accepted -> 0)
  C = duplicacao (u_skid.skid_pop -> 0: item permanece e e consumido de novo)
  I1 = perda a montante (u_window.i_valid -> 0), so para a matriz de flags.
Todos os sinais lidos sao amostrados no mesmo ponto (apos a borda, ReadOnly):
valores do MESMO ciclo (ver ARQUITETURA_MULTICICLO.md, 6a pegadinha).
Env: TEST_IMG_WIDTH, TEST_IMG_HEIGHT, PROBE_MODE(none|B|C|I1), PROBE_OFF,
PROBE_FRAMES, PROBE_STALL, PROBE_SEED.
"""
import os
from collections import Counter

import numpy as np
import pytest

import cocotb
from cocotb.clock import Clock
from cocotb.handle import Force, Release
from cocotb.triggers import FallingEdge, NextTimeStep, ReadOnly, RisingEdge, Timer

from _cocotb_helpers import capture_errors, run_isolated
from test_sobel_multicycle import _feed_image_and_collect, _reference_sobel_l1

DATA_WIDTH, COEFF_WIDTH, ACC_WIDTH = 8, 3, 11
INJECT_FRAME = 2
DRAIN_CYCLES = 150


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
            msg.append(f"DELECAO_UNICA k={ks[0]}..{ks[-1]}")
    if len(outs) == len(exp) + 1:
        ks = [k for k in range(len(outs)) if outs[:k] + outs[k + 1:] == exp]
        if ks:
            msg.append(f"DUPLICACAO_UNICA k={ks[0]}..{ks[-1]} (remover 1 saida da o golden)")
    if len(outs) < len(exp) and _is_subseq(outs, exp):
        msg.append(f"SUBSEQUENCIA (faltam {len(exp) - len(outs)}, nenhum pixel errado)")
    if not msg:
        msg.append("OUTRO (nao e delecao/duplicacao pura)")
    msg.append(f"LCS={_lcs(outs, exp)}/{len(outs)}")
    return "; ".join(msg)


def _drained(dut):
    return (int(dut.lb_valid.value) == 0 and int(dut.win_valid.value) == 0
            and int(dut.u_lw_skid.count_r.value) == 0
            and int(dut.u_skid.skid_count_r.value) == 0
            and int(dut.u_window.phantom_pending_r.value) == 0)


def _new_state():
    return {
        "cyc": -1, "outs": [], "raw": 0, "real": 0, "b": 0,
        "cond_cycles": 0, "cond_episodes": 0, "prev_cond": None,
        "b_hist": Counter(), "cond_not_empty": 0, "flag2_cyc": None, "flag2_b": None,
        "t_prev": None, "acc_wvr": 0, "acc_ov": 0, "iv": Counter(), "iv_maxlen": 0,
        "d_checks": 0, "flagD_cyc": None,
        "ovf_skid": 0, "ovf_lw": 0,
    }


def _sample(dut, st, cyc, P, w):
    wvr = int(dut.win_valid_real.value)
    ov = int(dut.o_valid.value)
    if ov:
        st["outs"].append(int(dut.o_pixel.value))
    if int(dut.win_valid.value):
        st["raw"] += 1
    if wvr:
        st["real"] += 1
    st["cyc"] = cyc

    # ---- E2: b e um REGISTRADOR: compara o valor ANTES de somar os eventos
    # deste ciclo (R1). O evento do ciclo de verificacao conta para o proximo
    # intervalo (R8).
    cond = bool(int(dut.fsm_ready.value) and not int(dut.fsm_i_valid.value))
    b = st["b"]
    if cond:
        st["cond_cycles"] += 1
        st["b_hist"][b] += 1
        if int(dut.u_skid.skid_count_r.value) != 0:
            st["cond_not_empty"] += 1
        if b != 0 and st["flag2_cyc"] is None:
            st["flag2_cyc"], st["flag2_b"] = cyc, b
        if st["prev_cond"] is not True:
            st["cond_episodes"] += 1
        if st["t_prev"] is not None:
            st["iv"][(st["acc_wvr"], st["acc_ov"])] += 1
            st["iv_maxlen"] = max(st["iv_maxlen"], cyc - st["t_prev"])
        st["t_prev"], st["acc_wvr"], st["acc_ov"] = cyc, 0, 0
    st["acc_wvr"] += wvr
    st["acc_ov"] += ov
    st["prev_cond"] = cond
    st["b"] = b + wvr - ov

    # ---- regra de D (I1), igual a v2
    feed = int(dut.feed_cnt_r.value)
    wc = int(dut.win_cnt_r.value)
    d = (feed - wc) % P
    ds = d if d <= P // 2 else d - P
    if _drained(dut):
        st["d_checks"] += 1
        if ds != (1 if feed % w != 0 else 0) and st["flagD_cyc"] is None:
            st["flagD_cyc"] = cyc

    # ---- E1
    st["ovf_skid"] += int(dut.u_skid.o_overflow.value)
    st["ovf_lw"] += int(dut.u_lw_skid.o_overflow.value)


async def _drain(dut, st, P, w):
    """So leitura, na mesma posicao de amostragem do helper (R4)."""
    dut.i_valid.value = 0
    for _ in range(DRAIN_CYCLES):
        await ReadOnly()
        _sample(dut, st, st["cyc"] + 1, P, w)
        await NextTimeStep()
        await RisingEdge(dut.clk)


async def _injector(dut, mode, target, st, log):
    n = 0
    while True:
        await FallingEdge(dut.clk)
        if mode == "B":
            sig = dut.u_skid.skid_push_accepted
        elif mode == "C":
            sig = dut.u_skid.skid_pop
        else:
            sig = dut.u_window.i_valid
        if not int(sig.value):
            continue
        if n == target:
            log["fire_cyc"] = st["cyc"]
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
    assert n_sat == 0, f"massa saturou ({n_sat}): sonda invalida"

    per_frame_elig = P if mode == "I1" else w * h
    st, log = _new_state(), {"fired": False, "fire_cyc": None}
    if mode in ("B", "C", "I1"):
        cocotb.start_soon(_injector(dut, mode, INJECT_FRAME * per_frame_elig + off, st, log))

    def on_cycle(cyc, i_valid, i_pixel):
        _sample(dut, st, cyc, P, w)

    timed_out = False
    try:
        await _feed_image_and_collect(dut, np.vstack(images), stall_prob=stall,
                                      seed=seed, on_cycle=on_cycle)
    except TimeoutError:
        timed_out = True
    await _drain(dut, st, P, w)

    outs = st["outs"]
    final_drained = _drained(dut)
    lat = (None if st["flag2_cyc"] is None or log["fire_cyc"] is None
           else st["flag2_cyc"] - log["fire_cyc"])
    print(f"\n=== PROBE3 W={w} H={h} mode={mode} off={off} frames={nfr} "
          f"stall={stall} seed={seed} (inject no frame {INJECT_FRAME}) ===")
    print(f"fired={log['fired']} fire_cyc={log['fire_cyc']} timed_out={timed_out} "
          f"final_drained={final_drained}")
    print(f"len(outs)={len(outs)} esperado={len(expected)}  win_raw={st['raw']} "
          f"esperado={nfr * P}  win_real={st['real']} esperado={nfr * w * h}")
    print(f"feed_cnt_r_final={int(dut.feed_cnt_r.value)} "
          f"win_cnt_r_final={int(dut.win_cnt_r.value)} b_final={st['b']}")
    print(f"ALINHAMENTO: {_classify(outs, expected)}  "
          f"(delta={len(outs) - len(expected):+d})")
    print(f"FLAG_E2 : cyc={st['flag2_cyc']} b={st['flag2_b']} latencia_desde_injecao={lat} "
          f"| verificacoes(cond)={st['cond_cycles']} cond_com_skid_nao_vazio={st['cond_not_empty']}")
    print(f"          b_nos_instantes_cond={dict(sorted(st['b_hist'].items()))}")
    print(f"FLAG_D  : cyc={st['flagD_cyc']} | verificacoes(drenado)={st['d_checks']}")
    print(f"FLAG_E1 : overflow_u_skid={st['ovf_skid']} overflow_u_lw_skid={st['ovf_lw']}")

    if mode == "none":
        total = st["cyc"] + 1
        evs = [wv + o for (wv, o) in st["iv"].elements()]
        print(f"FREQ    : ciclos={total} cond_cycles={st['cond_cycles']} "
              f"({100.0 * st['cond_cycles'] / total:.1f}%) episodios_cond={st['cond_episodes']}")
        print(f"          intervalo_max_entre_verificacoes={st['iv_maxlen']} ciclos; "
              f"max_eventos(wvr+ov)_num_intervalo={max(evs) if evs else None}")
        print(f"          (wvr,ov)->ocorrencias nos intervalos entre verificacoes consecutivas:")
        for key, c in sorted(st["iv"].items())[:12]:
            print(f"            {key} x{c}")

    # ---- validade da sonda (nao e o veredito das hipoteses)
    if mode == "none":
        assert outs == expected, "CONTROLE falhou: sonda invalida (ou regressao do RTL)"
        assert st["cond_not_empty"] == 0, "cond nao implica skid vazio"
        assert st["flag2_cyc"] is None and st["flagD_cyc"] is None, "falso positivo no controle"
        assert st["ovf_skid"] == 0 and st["ovf_lw"] == 0
        assert st["cond_cycles"] > 0 and st["d_checks"] > 0, "verificacoes vazias (R5)"
    else:
        assert log["fired"], "injecao nao disparou: sonda invalida"
        if mode == "B":
            assert len(outs) < len(expected), "Force sem efeito (R3): sonda invalida"
        if mode == "C":
            # R3: Force deve ter tido efeito; duplicacao OU corrupcao sao
            # resultados validos do modo C (dependem do offset de injecao).
            assert outs != expected, "Force sem efeito (R3): sonda invalida"


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
            module="probe_inject_loss_v3",
            parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": w, "IMG_HEIGHT": h,
                        "COEFF_WIDTH": COEFF_WIDTH, "ACC_WIDTH": ACC_WIDTH},
            compile_args=["-g2012", "-Wall"],
            sim_build=os.path.join(root, "sim", f"sim_build_probe3_w{w}_h{h}"),
            extra_env={"TEST_IMG_WIDTH": str(w), "TEST_IMG_HEIGHT": str(h),
                       "PROBE_MODE": mode, "PROBE_OFF": str(off),
                       "PROBE_FRAMES": str(frames), "PROBE_STALL": str(stall),
                       "PROBE_SEED": str(seed)},
        )
    print(f"ERROR_COUNT: {cap.count}  (mode={mode} W={w} H={h} off={off} stall={stall})")
    if mode == "none":
        assert cap.count == 0


@pytest.mark.parametrize("w,frames,stall", [(8, 8, 0.0), (8, 8, 0.3), (8, 8, 0.8),
                                            (320, 2, 0.0), (320, 2, 0.3)],
                         ids=["w8s0.0", "w8s0.3", "w8s0.8", "w320s0.0", "w320s0.3"])
def test_probe3_none(w, frames, stall):
    _runner(w, 3, "none", frames=frames, stall=stall, seed=1)


# 24 janelas reais por frame (W=8,H=3): offsets em varios pontos
@pytest.mark.parametrize("off", [0, 5, 12, 23], ids=lambda v: f"off{v}")
def test_probe3_B_w8(off):
    _runner(8, 3, "B", off)


@pytest.mark.parametrize("off", [0, 5, 12, 23], ids=lambda v: f"off{v}")
def test_probe3_C_w8(off):
    _runner(8, 3, "C", off)


def test_probe3_B_w8_stall():
    _runner(8, 3, "B", 5, stall=0.3, seed=1)


def test_probe3_C_w8_stall():
    _runner(8, 3, "C", 5, stall=0.3, seed=1)


@pytest.mark.parametrize("off", [5, 8], ids=lambda v: f"off{v}")
def test_probe3_I1_w8(off):
    _runner(8, 3, "I1", off)