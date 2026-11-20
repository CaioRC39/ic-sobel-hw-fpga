"""Validacao Camada 2, contrato A'. Oraculo independente (np.pad + Sobel vetorizado)."""
import os, random, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from window_stream_cycle_model import MUTANTS, CONTRACT_MUTANTS, ContractError, WindowStreamCycleModel

GX = [[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]]
GY = [[-1, -2, -1], [0, 0, 0], [1, 2, 1]]
GEOMS = [(w, h) for w in (2, 3, 4, 5, 6, 8, 16) for h in (1, 2, 3, 5)]
STREAMS = [(1, 1), (1, 2), (2, 1), (3, 2)]
GAPS = ["none", "bern", "burst", "periodic", "long"]
MASSES = ["baixo", "cheia"]
GEOMS_M = [(3, 1), (3, 2), (4, 3), (8, 2), (5, 5)]
STREAMS_M = [(2, 2)]


def make_frame(w, h, mass, seed):
    return np.random.RandomState(seed).randint(0, 13 if mass == "baixo" else 256, size=(h, w))

def expected_windows(frame):
    h, w = frame.shape
    p = np.pad(frame, 1, mode="constant", constant_values=0)
    return [p[r:r + 3, c:c + 3].tolist() for r in range(h) for c in range(w)]

def sobel_from_window(win):
    gx = sum(win[r][c] * GX[r][c] for r in range(3) for c in range(3))
    gy = sum(win[r][c] * GY[r][c] for r in range(3) for c in range(3))
    return min(abs(gx) + abs(gy), 255)

def golden_sobel(img):
    img = np.asarray(img, dtype=np.int64); h, w = img.shape
    p = np.pad(img, 1, mode="constant", constant_values=0)
    gx = (p[0:h, 2:w+2] + 2*p[1:h+1, 2:w+2] + p[2:h+2, 2:w+2]) - (p[0:h, 0:w] + 2*p[1:h+1, 0:w] + p[2:h+2, 0:w])
    gy = (p[2:h+2, 0:w] + 2*p[2:h+2, 1:w+1] + p[2:h+2, 2:w+2]) - (p[0:h, 0:w] + 2*p[0:h, 1:w+1] + p[0:h, 2:w+2])
    return np.minimum(np.abs(gx) + np.abs(gy), 255).flatten().tolist()

def make_gap_fn(kind, w, h, seed):
    rng = random.Random(seed); fr = w * h
    special = {0, 1, w, w + 1, w + 2, fr - 1, fr // 2}
    def fn(i):
        if kind == "none": return 0
        if kind == "bern":
            g = 0
            while rng.random() < 0.35 and g < 12: g += 1
            return g
        if kind == "burst": return 0 if (i % 11) < 7 else rng.randint(2, 6)
        if kind == "periodic": return 2 if i % 2 == 0 else 0
        if kind == "long": return 3*w + 7 if (i % fr) in special else 0
    return fn

def drive(model, streams, gap, w, h, max_cycles=400_000):
    trace, pcs, lcs = [], [], []
    def idle():
        if len(trace) > max_cycles: raise RuntimeError("timeout")
        trace.append(model.step(0, 0, 0))
    for frames in streams:
        flat = [int(x) for fr in frames for x in fr.flatten()]
        total = len(flat); pc = []; i = 0; wait = gap(0)
        while i < total:
            if len(trace) > max_cycles: raise RuntimeError("timeout")
            if wait > 0: wait -= 1; v = 0
            else: v = 1 if model.ready() else 0
            last = 1 if (v and i == total - 1) else 0
            obs = model.step(v, flat[i] if v else 0, last)
            if v:
                pc.append(len(trace)); i += 1; wait = gap(i)
            trace.append(obs)
        t_l = pc[-1]; lcs.append(t_l)
        pc.extend(range(t_l + 1, t_l + w + 2))
        pcs.append(pc)
    for _ in range(w + 6): idle()
    return trace, pcs, lcs

def run_case(w, h, ns, nf, gap_kind, mass, seed, mutant=None):
    streams = [[make_frame(w, h, mass, seed*100 + s*10 + f) for f in range(nf)] for s in range(ns)]
    model = WindowStreamCycleModel(w, h, mutant=mutant, seed=seed)
    try:
        trace, pcs, lcs = drive(model, streams, make_gap_fn(gap_kind, w, h, seed), w, h)
    except ContractError as e:
        return dict(ok=False, why=f"ContractError: {e}", n_win=0, n_cyc=0, n_sat=0)
    L = WindowStreamCycleModel.LATENCY
    expected, gold = {}, []
    for s, frames in enumerate(streams):
        wins = [x for fr in frames for x in expected_windows(fr)]
        pc = pcs[s]
        if len(pc) != len(wins) + w + 1:
            return dict(ok=False, why="oraculo inconsistente", n_win=0, n_cyc=0, n_sat=0)
        for c, win in enumerate(wins): expected[pc[c + w + 1] + L] = win
        for fr in frames: gold += golden_sobel(fr)
    got = {t: o["o_window"] for t, o in enumerate(trace) if o["o_valid"]}
    missing = sorted(set(expected) - set(got)); extra = sorted(set(got) - set(expected))
    wrong = sorted(t for t in set(got) & set(expected) if got[t] != expected[t])
    why = []
    if missing: why.append(f"faltam {len(missing)} janelas")
    if extra: why.append(f"{len(extra)} valid extras")
    if wrong: why.append(f"{len(wrong)} janelas erradas")
    for t_l in lcs:
        bad = [t for t in range(t_l + 1, t_l + w + 2) if trace[t]["o_ready"] != 0]
        if trace[t_l]["o_ready"] != 1 or bad: why.append(f"o_ready incorreto no flush apos last t={t_l}")
        t_end = t_l + w + 2
        if t_end < len(trace) and trace[t_end]["o_ready"] != 1: why.append("o_ready nao voltou a 1")
    got_s = [sobel_from_window(got[t]) for t in sorted(got)]
    if not why and got_s != gold: why.append("Sobel diverge do golden")
    return dict(ok=not why, why="; ".join(why), n_win=len(expected), n_cyc=len(trace),
                n_sat=sum(1 for v in gold if v == 255))

def canary_hand_case():
    """W=2,H=1, [5,7], last no 2o pixel: pulsos 0,1; flush 2,3,4; centros em n=3,4 -> janelas em 5 e 6."""
    m = WindowStreamCycleModel(2, 1, seed=1)
    tr = [m.step(1, 5), m.step(1, 7, 1)] + [m.step(0, 0) for _ in range(8)]
    vt = {t: o["o_window"] for t, o in enumerate(tr) if o["o_valid"]}
    assert set(vt) == {5, 6}, f"canario: {sorted(vt)} != [5, 6]"
    assert vt[5] == [[0,0,0],[0,5,7],[0,0,0]], vt[5]
    assert vt[6] == [[0,0,0],[5,7,0],[0,0,0]], vt[6]
    assert [tr[t]["o_ready"] for t in range(6)] == [1, 1, 0, 0, 0, 1], [tr[t]["o_ready"] for t in range(6)]

def negatives(mutant=None):
    """Devolve a lista de negativos que NAO levantaram ContractError (vazia = todos ok)."""
    def last_mid_frame():
        m = WindowStreamCycleModel(4, 2, mutant=mutant); m.step(1, 3, 1)
    def last_no_valid():
        m = WindowStreamCycleModel(4, 2, mutant=mutant); m.step(1, 3); m.step(0, 0, 1)
    def input_while_busy():
        m = WindowStreamCycleModel(2, 1, mutant=mutant); m.step(1, 1); m.step(1, 1, 1); m.step(1, 9)
    def last_while_busy():
        m = WindowStreamCycleModel(2, 1, mutant=mutant); m.step(1, 1); m.step(1, 1, 1); m.step(0, 0, 1)
    silent = []
    for name, fn in (("last fora de fronteira", last_mid_frame), ("last sem valid", last_no_valid),
                     ("entrada durante flush", input_while_busy), ("last durante flush", last_while_busy)):
        try: fn(); silent.append(name)
        except ContractError: pass
    return silent

def main():
    canary_hand_case()
    assert negatives() == [], negatives()
    print("canario manual (W=2,H=1) e 4 negativos de contrato: OK")
    for mc in CONTRACT_MUTANTS:
        s = negatives(mc)
        print(f"MUTANTE-CONTRATO {mc:22s}: {'MORTO (silencioso: '+', '.join(s)+')' if s else 'SOBREVIVEU'}")
        assert s, f"mutante de contrato sobreviveu: {mc}"
    n_runs = n_win = n_cyc = n_sat = 0; fails = []
    for (w, h) in GEOMS:
        for (ns, nf) in STREAMS:
            for g in GAPS:
                for mass in MASSES:
                    seed = w*1000 + h*100 + ns*10 + nf
                    r = run_case(w, h, ns, nf, g, mass, seed)
                    n_runs += 1; n_win += r["n_win"]; n_cyc += r["n_cyc"]; n_sat += r["n_sat"]
                    if not r["ok"]: fails.append((w, h, ns, nf, g, mass, r["why"]))
    print(f"BASELINE: casos={n_runs} janelas={n_win} ciclos={n_cyc} saturados={n_sat} falhas={len(fails)}")
    for f in fails[:10]: print("  FALHA", f)
    assert n_win > 0 and n_sat > 0
    surv = []
    for mut in MUTANTS:
        kb = None
        for (w, h) in GEOMS_M:
            for (ns, nf) in STREAMS_M:
                for g in GAPS:
                    for mass in MASSES:
                        r = run_case(w, h, ns, nf, g, mass, w*77 + h, mutant=mut)
                        if not r["ok"]: kb = (w, h, g, mass, r["why"]); break
                    if kb: break
                if kb: break
            if kb: break
        print(f"MUTANTE {mut:14s}: {'MORTO  '+str(kb) if kb else 'SOBREVIVEU'}")
        if not kb: surv.append(mut)
    ok = not fails and not surv
    print(f"RESULT: {'PASS' if ok else 'FAIL'} baseline_falhas={len(fails)} mutantes_vivos={surv}")
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()