"""Validador do modelo window_stream_model (Camada 1). NAO altera RTL.
Rodar de tb_python/models/:  python3 validate_window_stream.py
Saida de interesse: bloco "=== RESUMO ===" e a linha RESULT. Exit code 1 se FAIL.

Verificacoes (CLAUDE.md 15.11.2 / licoes do projeto):
  0. caso trivial de resposta conhecida (literal escrito a mao, nao np.pad)
  1. janela a janela vs np.pad, W x H x F variados, memoria envenenada
  2. Sobel vs _reference_sobel_l1 (massa [0,12] com guarda n_sat==0; faixa cheia satura)
  3. Nivel 2: padrao de valid == [0]*(W+1) + [1]*(F*W*H); latencia W+1; descarga W+1
  4. dois streams: com restart() deve bater; SEM restart() deve FALHAR (risco 1 do `started`)
  5. canarios: cada mutante tem que ser MORTO (senao a validacao e vazia)
"""
import os
import random
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
try:
    from test_sobel_multicycle import _reference_sobel_l1  # fonte oficial
    REF_SRC = "oficial (test_sobel_multicycle)"
except ImportError:  # sem cocotb no ambiente: copia identica, AVISO
    REF_SRC = "COPIA LOCAL (cocotb ausente) - nao e a fonte oficial"
    _GX = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]])
    _GY = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]])

    def _reference_sobel_l1(image):
        p = np.pad(image, 1, mode="constant", constant_values=0).astype(int)
        h, w = image.shape
        out = []
        for r in range(h):
            for c in range(w):
                win = p[r:r + 3, c:c + 3]
                out.append(min(abs(int(np.sum(win * _GX))) + abs(int(np.sum(win * _GY))), 255))
        return out

from window_stream_model import WindowStream, run_stream  # noqa: E402

START_MODE = sys.argv[1] if len(sys.argv) > 1 else "counter"

GX = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]])
GY = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]])


def sobel_from_window(win):
    a = np.array(win, dtype=int)
    return min(abs(int(np.sum(a * GX))) + abs(int(np.sum(a * GY))), 255)


def expected_windows(images):
    out = []
    for im in images:
        h, w = im.shape
        p = np.pad(im, 1, mode="constant", constant_values=0).astype(int)
        for r in range(h):
            for c in range(w):
                out.append(p[r:r + 3, c:c + 3].tolist())
    return out


def make_images(w, h, f, rng, low):
    lo, hi = (0, 12) if low else (1, 255)  # faixa cheia sem zeros: mascara distinguivel de dado
    return [np.array([[rng.randint(lo, hi) for _ in range(w)] for _ in range(h)]) for _ in range(f)]


def run_case(w, h, f, seed, low, flush=True, model_kw=None, stream_mut=None):
    rng = random.Random(seed)
    images = make_images(w, h, f, rng, low)
    exp_w = expected_windows(images)
    exp_s = [s for im in images for s in _reference_sobel_l1(im)]
    n_sat = sum(1 for v in exp_s if v == 255)
    m = WindowStream(w, h, seed=seed + 1, start_mode=START_MODE, **(model_kw or {}))
    pixels = [int(v) for im in images for v in im.flatten()]
    if stream_mut == "drop":
        del pixels[len(pixels) // 2]
    elif stream_mut == "insert":
        pixels.insert(len(pixels) // 2, 77)
    if flush:
        pixels += [m.poison_pixel() for _ in range(w + 1)]
    valids, wins = run_stream(m, pixels)
    n_exp_pulses = f * w * h + (w + 1)
    exp_valid = [False] * (w + 1) + [True] * (f * w * h)
    valid_ok = (valids == exp_valid) if (flush and stream_mut is None) else None
    bad_w = sum(1 for g, e in zip(wins, exp_w) if g != e) + abs(len(wins) - len(exp_w))
    got_s = [sobel_from_window(x) for x in wins]
    bad_s = sum(1 for g, e in zip(got_s, exp_s) if g != e) + abs(len(got_s) - len(exp_s))
    first_valid = valids.index(True) if True in valids else None
    return dict(checks=len(exp_w), bad_w=bad_w, bad_s=bad_s, valid_ok=valid_ok,
                first_valid=first_valid, n_out=len(wins), n_sat=n_sat, pulses=len(pixels),
                exp_pulses=n_exp_pulses)


def case_ok(r, w):
    return (r["bad_w"] == 0 and r["bad_s"] == 0 and r["valid_ok"] is True
            and r["first_valid"] == w + 1)


def main():
    fails = []
    print(f"referencia Sobel: {REF_SRC}")
    print(f"start_mode: {START_MODE}")

    # 0. caso trivial, literal a mao: img [[1,2,3],[4,5,6]], janela centrada em (0,0)
    m = WindowStream(3, 2, seed=5, start_mode=START_MODE)
    valids, wins = run_stream(m, [1, 2, 3, 4, 5, 6, 9, 9, 9, 9])
    triv_ok = (valids.index(True) == 4 and wins[0] == [[0, 0, 0], [0, 1, 2], [0, 4, 5]]
               and wins[5] == [[2, 3, 0], [5, 6, 0], [0, 0, 0]] and len(wins) == 6)
    print(f"[0] trivial 3x2: primeira janela={wins[0]} ultima={wins[-1]} ok={triv_ok}")
    if not triv_ok:
        fails.append("trivial")

    # 1-3. matriz de geometrias
    n_checks = n_cases = n_bad_cases = sat_full = 0
    for w in (2, 3, 4, 5, 6, 8, 16):
        for h in (1, 2, 3, 5):
            for f in (1, 2, 4):
                for low in (False, True):
                    r = run_case(w, h, f, seed=1000 * w + 10 * h + f, low=low)
                    n_cases += 1
                    n_checks += r["checks"]
                    if low:
                        if r["n_sat"] != 0:
                            fails.append(f"massa saturou W{w}H{h}F{f}")
                    else:
                        sat_full += r["n_sat"]
                    if not case_ok(r, w) or r["n_out"] != f * w * h:
                        n_bad_cases += 1
                        fails.append(f"caso W{w} H{h} F{f} low={low}: {r}")
    print(f"[1-3] casos={n_cases} janelas comparadas={n_checks} casos_com_falha={n_bad_cases} "
          f"pixels saturados exercitados (faixa cheia)={sat_full}")
    if sat_full == 0:
        fails.append("faixa cheia nao saturou: validacao de clamp vazia")

    # 4. dois streams
    def two_streams(restart):
        w, h, f = 5, 3, 2
        rng = random.Random(7)
        im1, im2 = make_images(w, h, f, rng, False), make_images(w, h, f, rng, False)
        m = WindowStream(w, h, seed=3, start_mode=START_MODE)
        _, w1 = run_stream(m, [int(v) for im in im1 for v in im.flatten()]
                           + [m.poison_pixel() for _ in range(w + 1)])
        if restart:
            m.restart()
        _, w2 = run_stream(m, [int(v) for im in im2 for v in im.flatten()]
                           + [m.poison_pixel() for _ in range(w + 1)])
        return w1 == expected_windows(im1) and w2 == expected_windows(im2)

    with_r, without_r = two_streams(True), two_streams(False)
    print(f"[4] 2 streams: com restart bate={with_r} | SEM restart bate={without_r} "
          f"(esperado: True / False - confirma o risco do `started` pegajoso)")
    if not with_r:
        fails.append("2 streams com restart")
    if without_r:
        fails.append("2 streams sem restart bateu: derivacao do risco 1 esta errada")

    # 5. canarios
    mutants = [
        ("sem mascara esquerda", dict(model_kw=dict(mask_left=False))),
        ("sem mascara direita", dict(model_kw=dict(mask_right=False))),
        ("sem mascara topo", dict(model_kw=dict(mask_top=False))),
        ("sem mascara base", dict(model_kw=dict(mask_bottom=False))),
        ("latencia +1", dict(model_kw=dict(init_shift=1))),
        ("latencia -1", dict(model_kw=dict(init_shift=-1))),
        ("sem descarga", dict(flush=False)),
        ("frame com 1 pulso a menos", dict(stream_mut="drop")),
        ("frame com 1 pulso a mais", dict(stream_mut="insert")),
    ]
    killed = 0
    for name, kw in mutants:
        dead = False
        for (w, h, f) in ((4, 3, 2), (6, 2, 3), (3, 1, 2), (5, 4, 2)):
            r = run_case(w, h, f, seed=99 + w, low=False, **kw)
            if r["bad_w"] or r["bad_s"] or r["valid_ok"] is False or r["n_out"] != f * w * h:
                dead = True
                break
        killed += dead
        print(f"[5] mutante '{name}': {'MORTO' if dead else 'SOBREVIVEU  <<<'}")
        if not dead:
            fails.append(f"mutante sobreviveu: {name}")

    print("\n=== RESUMO ===")
    print(f"janelas comparadas={n_checks}  casos={n_cases}  mutantes mortos={killed}/{len(mutants)}")
    print("RESULT: " + ("PASS" if not fails else "FAIL"))
    for x in fails[:15]:
        print("  FALHA:", x)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
