"""Validacao da Camada 2 (ciclos). NAO executado por quem escreveu.
Uso:  cd tb_python/models && python3 validate_window_stream_cycles.py
Saida final: RESULT: PASS/FAIL. Exit code 0 so se baseline passa E todo mutante morre.
Oraculo independente: np.pad (janelas) + Sobel vetorizado; nao importa a Camada 1.
"""
import os
import random
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from window_stream_cycle_model import MUTANTS, ContractError, WindowStreamCycleModel

GX = [[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]]
GY = [[-1, -2, -1], [0, 0, 0], [1, 2, 1]]

GEOMS = [(w, h) for w in (2, 3, 4, 5, 6, 8, 16) for h in (1, 2, 3, 5)]   # H=1 em toda a matriz
STREAMS = [(1, 1), (1, 2), (2, 1), (3, 2)]                               # (streams, frames/stream)
GAPS = ["none", "bern", "burst", "periodic", "long"]
MASSES = ["baixo", "cheia"]
GEOMS_M = [(3, 1), (3, 2), (4, 3), (8, 2), (5, 5)]
STREAMS_M = [(2, 2)]


# ------------------------------------------------------------------ oraculo
def make_frame(w, h, mass, seed):
    hi = 13 if mass == "baixo" else 256
    return np.random.RandomState(seed).randint(0, hi, size=(h, w))


def expected_windows(frame):
    h, w = frame.shape
    p = np.pad(frame, 1, mode="constant", constant_values=0)
    return [p[r:r + 3, c:c + 3].tolist() for r in range(h) for c in range(w)]


def sobel_from_window(win):
    gx = sum(win[r][c] * GX[r][c] for r in range(3) for c in range(3))
    gy = sum(win[r][c] * GY[r][c] for r in range(3) for c in range(3))
    return min(abs(gx) + abs(gy), 255)


def golden_sobel(img):
    img = np.asarray(img, dtype=np.int64)
    h, w = img.shape
    p = np.pad(img, 1, mode="constant", constant_values=0)
    gx = (p[0:h, 2:w + 2] + 2 * p[1:h + 1, 2:w + 2] + p[2:h + 2, 2:w + 2]) - (
        p[0:h, 0:w] + 2 * p[1:h + 1, 0:w] + p[2:h + 2, 0:w])
    gy = (p[2:h + 2, 0:w] + 2 * p[2:h + 2, 1:w + 1] + p[2:h + 2, 2:w + 2]) - (
        p[0:h, 0:w] + 2 * p[0:h, 1:w + 1] + p[0:h, 2:w + 2])
    return np.minimum(np.abs(gx) + np.abs(gy), 255).flatten().tolist()


# ------------------------------------------------------------------ driver
def make_gap_fn(kind, w, h, seed):
    rng = random.Random(seed)
    fr = w * h
    special = {0, 1, w, w + 1, w + 2, fr - 1, fr // 2}

    def fn(i):
        if kind == "none":
            return 0
        if kind == "bern":
            g = 0
            while rng.random() < 0.35 and g < 12:
                g += 1
            return g
        if kind == "burst":
            return 0 if (i % 11) < 7 else rng.randint(2, 6)
        if kind == "periodic":
            return 2 if i % 2 == 0 else 0
        if kind == "long":
            return 3 * w + 7 if (i % fr) in special else 0
        raise ValueError(kind)

    return fn


def drive(model, streams, gap, w, h, max_cycles=400_000):
    """Respeita o_ready (ready-before-valid). Devolve (trace, pulse_cycles/stream, flush_cycles).
    pulse_cycles = ciclo de CADA pulso do line_buffer (pixels reais + W+1 de flush, nominais)."""
    trace, pcs, fcs = [], [], []

    def idle():
        if len(trace) > max_cycles:
            raise RuntimeError("timeout do driver")
        trace.append(model.step(0, 0, 0))

    for frames in streams:
        flat = [int(x) for fr in frames for x in fr.flatten()]
        total = len(flat)
        pulse_cycles = []
        i = 0
        wait = gap(0)
        while i < total:
            if len(trace) > max_cycles:
                raise RuntimeError("timeout do driver")
            if wait > 0:
                wait -= 1
                v = 0
            else:
                v = 1 if model.ready() else 0
            obs = model.step(v, flat[i] if v else 0, 0)
            if v:
                pulse_cycles.append(len(trace))
                i += 1
                wait = gap(i)               # i==total: gap antes do flush
            trace.append(obs)
        while wait > 0:
            idle()
            wait -= 1
        while not model.ready():
            idle()
        t_f = len(trace)
        trace.append(model.step(0, 0, 1))
        fcs.append(t_f)
        pulse_cycles.extend(range(t_f + 1, t_f + w + 2))   # W+1 pulsos nominais
        pcs.append(pulse_cycles)
    for _ in range(w + 6):
        idle()
    return trace, pcs, fcs


# ------------------------------------------------------------------ um caso
def run_case(w, h, n_streams, n_frames, gap_kind, mass, seed, mutant=None):
    streams = [[make_frame(w, h, mass, seed * 100 + s * 10 + f) for f in range(n_frames)]
               for s in range(n_streams)]
    model = WindowStreamCycleModel(w, h, mutant=mutant, seed=seed)
    try:
        trace, pcs, fcs = drive(model, streams, make_gap_fn(gap_kind, w, h, seed), w, h)
    except ContractError as e:
        return dict(ok=False, why=f"ContractError: {e}", n_win=0, n_cyc=0, n_sat=0)

    L = WindowStreamCycleModel.LATENCY
    expected, gold = {}, []
    for s, frames in enumerate(streams):
        wins = [win for fr in frames for win in expected_windows(fr)]
        pc = pcs[s]
        if len(pc) != len(wins) + w + 1:
            return dict(ok=False, why="oraculo inconsistente (bug do script)", n_win=0, n_cyc=0, n_sat=0)
        for c, win in enumerate(wins):
            expected[pc[c + w + 1] + L] = win
        for fr in frames:
            gold += golden_sobel(fr)
    got = {t: o["o_window"] for t, o in enumerate(trace) if o["o_valid"]}

    missing = sorted(set(expected) - set(got))
    extra = sorted(set(got) - set(expected))
    wrong = sorted(t for t in set(got) & set(expected) if got[t] != expected[t])
    why = []
    if missing:
        why.append(f"faltam {len(missing)} janelas (1o ciclo {missing[0]})")
    if extra:
        why.append(f"{len(extra)} valid extras (1o ciclo {extra[0]})")
    if wrong:
        why.append(f"{len(wrong)} janelas com conteudo/tempo errado (1o ciclo {wrong[0]})")

    for t_f in fcs:                              # janela de o_ready=0 do flush
        bad = [t for t in range(t_f + 1, t_f + w + 2) if trace[t]["o_ready"] != 0]
        if trace[t_f]["o_ready"] != 1 or bad:
            why.append(f"o_ready incorreto no flush de t_f={t_f}")
        t_end = t_f + w + 2
        if t_end < len(trace) and trace[t_end]["o_ready"] != 1:
            why.append(f"o_ready nao voltou a 1 em t={t_end}")

    got_sobel = [sobel_from_window(got[t]) for t in sorted(got)]
    if not why and got_sobel != gold:
        why.append("Sobel derivado das janelas diverge do golden vetorizado")

    return dict(ok=not why, why="; ".join(why), n_win=len(expected), n_cyc=len(trace),
                n_sat=sum(1 for v in gold if v == 255))


# ------------------------------------------------------------------ canario manual e contrato
def canary_hand_case():
    """W=2,H=1, pixels [5,7]. Derivado a mao: pulsos nos ciclos 0,1; flush cmd em 2;
    pulsos de flush em 3,4,5 -> centros c0,c1 nos pulsos n=3,4 (ciclos 4,5) -> janelas em 6 e 7."""
    m = WindowStreamCycleModel(2, 1, seed=1)
    tr = [m.step(1, 5), m.step(1, 7), m.step(0, 0, 1)] + [m.step(0, 0) for _ in range(8)]
    vt = {t: o["o_window"] for t, o in enumerate(tr) if o["o_valid"]}
    assert set(vt) == {6, 7}, f"canario: ciclos validos {sorted(vt)} != [6, 7]"
    assert vt[6] == [[0, 0, 0], [0, 5, 7], [0, 0, 0]], vt[6]
    assert vt[7] == [[0, 0, 0], [5, 7, 0], [0, 0, 0]], vt[7]


def contract_negatives():
    def expect_error(fn, name):
        try:
            fn()
        except ContractError:
            return
        raise AssertionError(f"negativo '{name}' nao levantou ContractError")

    def flush_empty():
        WindowStreamCycleModel(4, 2).step(0, 0, 1)

    def flush_mid_frame():
        m = WindowStreamCycleModel(4, 2)
        m.step(1, 3)
        m.step(0, 0, 1)

    def input_while_busy():
        m = WindowStreamCycleModel(2, 1)
        m.step(1, 1)
        m.step(1, 1)
        m.step(0, 0, 1)
        m.step(1, 9)

    def valid_and_flush():
        m = WindowStreamCycleModel(2, 1)
        m.step(1, 1)
        m.step(1, 1)
        m.step(1, 1, 1)

    expect_error(flush_empty, "flush sem pixels")
    expect_error(flush_mid_frame, "flush no meio do frame")
    expect_error(input_while_busy, "entrada durante flush")
    expect_error(valid_and_flush, "i_valid e i_flush juntos")


# ------------------------------------------------------------------ main
def main():
    canary_hand_case()
    contract_negatives()
    print("canario manual (W=2,H=1) e 4 negativos de contrato: OK")

    n_runs = n_win = n_cyc = n_sat = 0
    fails = []
    for (w, h) in GEOMS:
        for (ns, nf) in STREAMS:
            for g in GAPS:
                for mass in MASSES:
                    seed = w * 1000 + h * 100 + ns * 10 + nf
                    r = run_case(w, h, ns, nf, g, mass, seed)
                    n_runs += 1
                    n_win += r["n_win"]
                    n_cyc += r["n_cyc"]
                    n_sat += r["n_sat"]
                    if not r["ok"]:
                        fails.append((w, h, ns, nf, g, mass, r["why"]))
    print(f"BASELINE: casos={n_runs} janelas_verificadas={n_win} ciclos={n_cyc} "
          f"pixels_saturados_exercitados={n_sat} falhas={len(fails)}")
    for f in fails[:15]:
        print("  FALHA", f)
    assert n_win > 0 and n_sat > 0, "verificacao vazia"

    survivors = []
    for mut in MUTANTS:
        killed_by = None
        for (w, h) in GEOMS_M:
            for (ns, nf) in STREAMS_M:
                for g in GAPS:
                    for mass in MASSES:
                        r = run_case(w, h, ns, nf, g, mass, w * 77 + h, mutant=mut)
                        if not r["ok"]:
                            killed_by = (w, h, g, mass, r["why"])
                            break
                    if killed_by:
                        break
                if killed_by:
                    break
            if killed_by:
                break
        print(f"MUTANTE {mut:14s}: {'MORTO  ' + str(killed_by) if killed_by else 'SOBREVIVEU'}")
        if not killed_by:
            survivors.append(mut)

    ok = not fails and not survivors
    print(f"RESULT: {'PASS' if ok else 'FAIL'}  baseline_falhas={len(fails)} "
          f"mutantes_vivos={survivors}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()