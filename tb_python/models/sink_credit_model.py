"""Modelo do sink finito com creditos (P1). NAO executado por quem escreveu.
Uso:  cd tb_python/models && python3 sink_credit_model.py
Saida final: RESULT: PASS/FAIL. Exit code 0 so se o design com creditos passa E todo mutante morre.

Cena: wrapper -> pipeline (WindowStreamCycleModel) -> FIFO de saida (profundidade DEPTH) -> sink.
Credito: injeta pixel se len(fifo) + (enviados - produzidos) + 1 <= DEPTH. Invariante (por inducao):
  count + pendentes <= DEPTH em todo inicio de ciclo => nenhuma janela futura encontra FIFO cheio.
Overflow e contado pela ocupacao no INICIO do ciclo (conservador: ignora pop simultaneo).
Oraculo: janelas via np.pad (importadas do validador da Camada 2), comparadas em ordem.
"""
import os
import random
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validate_window_stream_cycles import expected_windows, make_frame  # noqa: E402
from window_stream_cycle_model import WindowStreamCycleModel  # noqa: E402

GEOMS = [(2, 1), (3, 2), (4, 3), (8, 3), (16, 2)]
SINKS = [("p", 1.0), ("p", 0.5), ("p", 0.2), ("burst", 20, 60), ("burst", 3, 9)]
MUTANTS = ("no_credit", "credit_off_by_one")


def sink_ready(mode, cyc, rng):
    if mode[0] == "p":
        return rng.random() < mode[1]
    on, off = mode[1], mode[2]
    return (cyc % (on + off)) < on


def run_case(w, h, depth, sink, seed, mutant=None, n_streams=2, frames_per_stream=2,
             src_p=1.0, max_cycles=2_000_000):
    imgs = [make_frame(w, h, "cheia", seed * 10 + f) for f in range(n_streams * frames_per_stream)]
    flat = [int(x) for im in imgs for x in im.flatten()]
    exp = [win for im in imgs for win in expected_windows(im)]
    per_stream = w * h * frames_per_stream
    total = len(flat)

    model = WindowStreamCycleModel(w, h, seed=seed)
    rs, rsrc = random.Random(seed * 7 + 1), random.Random(seed * 13 + 5)
    fifo, popped = deque(), []
    i = sent = produced = overflow = credit_blocks = max_fifo = cyc = 0
    slack = 1 if mutant == "credit_off_by_one" else 0

    while len(popped) < len(exp):
        if cyc > max_cycles:
            return dict(status="DEADLOCK", overflow=overflow, ok=False, cyc=cyc,
                        credit_blocks=credit_blocks, max_fifo=max_fifo, got=len(popped), exp=len(exp))
        count_before = len(fifo)
        v = 0
        if i < total and model.ready() and rsrc.random() < src_p:
            pending = sent - produced
            if mutant == "no_credit" or count_before + pending + 1 <= depth + slack:
                v = 1
            else:
                credit_blocks += 1
        last = 1 if (v and (i + 1) % per_stream == 0) else 0
        obs = model.step(v, flat[i] if v else 0, last)
        if v:
            sent += 1
            i += 1
        if sink_ready(sink, cyc, rs) and fifo:          # pop (decidido sobre ocupacao do ciclo)
            popped.append(fifo.popleft())
        if obs["o_valid"]:
            produced += 1
            if count_before >= depth:
                overflow += 1                            # janela perdida
            else:
                fifo.append(obs["o_window"])
        max_fifo = max(max_fifo, len(fifo))
        cyc += 1

    ok = (overflow == 0 and popped == exp)
    return dict(status="OK", overflow=overflow, ok=ok, cyc=cyc, credit_blocks=credit_blocks,
                max_fifo=max_fifo, got=len(popped), exp=len(exp), px_per_cyc=total / cyc)


def min_depth(w, h, seed):
    """Menor DEPTH sem deadlock com sink sempre pronto (medido, nao assumido)."""
    for d in range(1, 6 * w + 20):
        r = run_case(w, h, d, ("p", 1.0), seed, max_cycles=50_000)
        if r["status"] == "OK" and r["ok"]:
            return d
    return None


def main():
    fails = []
    tot_credit_blocks = n_cases = 0

    print("--- menor DEPTH sem deadlock (sink sempre pronto) ---")
    for (w, h) in GEOMS:
        d = min_depth(w, h, seed=w * 10 + h)
        print(f"  W={w} H={h}: min_depth={d}  (W+1={w + 1}, W+2={w + 2})")
        if d is None:
            fails.append(f"sem profundidade viavel W={w} H={h}")

    print("--- design com creditos: 0 perdas, saida == oraculo ---")
    for (w, h) in GEOMS:
        dmin = min_depth(w, h, seed=w * 10 + h) or (w + 4)
        for depth in sorted({dmin, dmin + 4, 2 * w + 8}):
            for sk in SINKS:
                for src_p in (1.0, 0.6):
                    r = run_case(w, h, depth, sk, seed=w * 31 + h, src_p=src_p)
                    n_cases += 1
                    tot_credit_blocks += r["credit_blocks"]
                    if not r["ok"]:
                        fails.append((w, h, depth, sk, src_p, r["status"], r["overflow"],
                                      f"{r['got']}/{r['exp']}"))
    print(f"  casos={n_cases} bloqueios_por_credito={tot_credit_blocks} falhas={len(fails)}")
    for f in fails[:10]:
        print("  FALHA", f)
    assert n_cases > 0 and tot_credit_blocks > 0, "verificacao vazia: credito nunca atuou"

    print("--- vazao com sink sempre pronto (informativo, sem assercao) ---")
    for (w, h) in GEOMS:
        r = run_case(w, h, 2 * w + 8, ("p", 1.0), seed=w * 31 + h)
        print(f"  W={w} H={h} DEPTH={2 * w + 8}: px/ciclo={r['px_per_cyc']:.3f} max_fifo={r['max_fifo']}")

    print("--- mutantes (devem causar overflow ou saida errada) ---")
    survivors = []
    for mut in MUTANTS:
        killed = None
        for (w, h) in GEOMS:
            for sk in SINKS[1:]:
                r = run_case(w, h, w + 8, sk, seed=w * 31 + h, mutant=mut)
                if not r["ok"]:
                    killed = (w, h, sk, r["overflow"])
                    break
            if killed:
                break
        print(f"  MUTANTE {mut:18s}: {'MORTO ' + str(killed) if killed else 'SOBREVIVEU'}")
        if not killed:
            survivors.append(mut)

    ok = not fails and not survivors
    print(f"RESULT: {'PASS' if ok else 'FAIL'} falhas={len(fails)} mutantes_vivos={survivors}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()