"""Teste de FRAME COMPLETO de sobel_multicycle (Frente 2, etapa 4.7).

NAO altera RTL. Dois testes de natureza diferente neste arquivo:

1. test_vectorized_reference_matches_loop_reference  (SEMPRE ativo, Python puro, rapido)
   Valida o gabarito vetorizado (numpy) contra _reference_sobel_l1, o gabarito de laco ja
   usado em toda a suite. Sem isso, o gabarito vetorizado seria uma 2a fonte de verdade
   nao verificada. Cobre formas degeneradas (1x1, 1xN, Nx1), imagens de baixo contraste e
   imagens de faixa cheia (0..255) que SATURAM - e exige que a saturacao tenha de fato
   ocorrido (guarda contra validacao vazia).

2. test_frame_full_runner  (LENTO, so com RUN_SLOW=1)
   F frames back-to-back (padrao: 2) de WxH (padrao: 640x480) numa UNICA simulacao,
   alimentados como 1 fluxo continuo (sem pausa entre frames: o caso mais duro para
   rearm/win_cnt_r/frame_tag_r). Confere: saida completa == gabarito; total de
   win_valid_real == F*W*H; o_status == 000; zero $error (guarda de run_isolated).
   Os ciclos medidos sao IMPRESSOS e comparados com a previsao do modelo
   16*W*H*F + (2W-1)*F + 6 (ajustado a W=16/640, 3 e 6 linhas, 1 e 4 frames), mas SEM
   asserção: a previsao e uma extrapolacao falseavel, nao um requisito do RTL.

Massa: pseudoaleatoria com semente fixa, pixels em [0,12] => |Gx|+|Gy| <= 96 < 255 (sem
saturacao, para nao mascarar bugs de conteudo - Licao 3/4 do RESUMO). Aleatoria de
proposito: um padrao periodico (como o de periodo 13 dos outros testes) mascararia um
deslocamento de multiplos do periodo.

Como rodar (de tb_python/ ou via `make frame`):
  RUN_SLOW=1 SIM=icarus python3 -m pytest test_frame_640x480.py -v -s \
      -o log_cli=true --log-cli-level=INFO
Teste rapido do proprio script (sem esperar ~13 min):
  RUN_SLOW=1 FRAME_W=16 FRAME_H=8 FRAME_N=2 SIM=icarus python3 -m pytest test_frame_640x480.py -v -s \
      -o log_cli=true --log-cli-level=INFO
Variaveis: FRAME_W (640), FRAME_H (480), FRAME_N (2). SIM=icarus|verilator.
Com COV_MODE=1 SIM=verilator o gancho de cobertura grava o .dat em sim/cov_data (4.8).
"""

import os
import shutil
import time

import numpy as np
import pytest

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from _cocotb_helpers import run_isolated
from test_sobel_multicycle import _feed_image_and_collect, _reference_sobel_l1

DATA_WIDTH, COEFF_WIDTH, ACC_WIDTH = 8, 3, 11
RUN_SLOW = os.environ.get("RUN_SLOW") == "1"
PROGRESS_EVERY = 1_000_000  # ciclos entre mensagens de progresso


# ----------------------------------------------------------------------
# Gabarito vetorizado e massa
# ----------------------------------------------------------------------
def _sobel_l1_vectorized(image: np.ndarray):
    """Sobel L1 saturado em 255, zero-padding nas 4 bordas, ordem linha-major.
    Mesmas formulas algebricas do projeto: Gx=(c+2f+i)-(a+2d+g), Gy=(g+2h+i)-(a+2b+c)."""
    img = np.asarray(image, dtype=np.int64)
    h, w = img.shape
    p = np.pad(img, 1, mode="constant", constant_values=0)
    gx = (p[0:h, 2:w + 2] + 2 * p[1:h + 1, 2:w + 2] + p[2:h + 2, 2:w + 2]) - (
        p[0:h, 0:w] + 2 * p[1:h + 1, 0:w] + p[2:h + 2, 0:w])
    gy = (p[2:h + 2, 0:w] + 2 * p[2:h + 2, 1:w + 1] + p[2:h + 2, 2:w + 2]) - (
        p[0:h, 0:w] + 2 * p[0:h, 1:w + 1] + p[0:h, 2:w + 2])
    return np.minimum(np.abs(gx) + np.abs(gy), 255).flatten().tolist()


def _frame_images(w, h, n):
    """n frames de baixo contraste, pseudoaleatorios, reprodutiveis (semente fixa por frame)."""
    return [np.random.RandomState(1000 + f).randint(0, 13, size=(h, w)) for f in range(n)]


# ----------------------------------------------------------------------
# Teste 1 (sempre ativo): valida o gabarito vetorizado
# ----------------------------------------------------------------------
def test_vectorized_reference_matches_loop_reference():
    shapes = [(1, 1), (1, 5), (5, 1), (2, 2), (3, 4), (7, 9), (16, 16), (31, 5)]
    total_sat = 0
    n_cases = 0
    for (h, w) in shapes:
        for kind, seed in (("baixo", 1), ("cheia", 2)):
            rng = np.random.RandomState(seed * 100 + h * 7 + w)
            img = rng.randint(0, 13, size=(h, w)) if kind == "baixo" else rng.randint(0, 256, size=(h, w))
            got = _sobel_l1_vectorized(img)
            exp = _reference_sobel_l1(img)
            assert got == exp, f"gabarito vetorizado diverge em {h}x{w} ({kind})"
            total_sat += sum(1 for v in exp if v == 255)
            n_cases += 1
    assert total_sat > 0, "nenhum caso saturou: a validacao da clamp em 255 seria vazia"
    print(f"vetorizado == laco em {n_cases} casos; pixels saturados exercitados: {total_sat}")


# ----------------------------------------------------------------------
# Teste 2 (lento): frame completo
# ----------------------------------------------------------------------
def _predicted_cycles(w, h, n):
    return 16 * w * h * n + (2 * w - 1) * n + 6


def _mode():
    if os.environ.get("COV_MODE") == "1":
        return "verilator+cov"
    return "verilator" if os.environ.get("SIM") == "verilator" else "icarus"


@cocotb.test()
async def frame_full(dut):
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
    n = int(os.environ["FRAME_N"])

    images = _frame_images(w, h, n)
    expected = [p for im in images for p in _sobel_l1_vectorized(im)]
    n_sat = sum(1 for v in expected if v == 255)
    assert n_sat == 0, f"massa saturou ({n_sat}/{len(expected)}): teste invalido"
    assert len(set(expected)) > 8, "gabarito quase constante: nao detectaria deslocamento"

    acc = {"cycles": 0, "status": 0, "real": 0}
    t0 = time.perf_counter()

    def on_cycle(cyc, i_valid, i_pixel):
        acc["cycles"] = cyc + 1
        acc["status"] |= int(dut.o_status.value)
        acc["real"] += int(dut.win_valid_real.value)
        if cyc and cyc % PROGRESS_EVERY == 0:
            el = time.perf_counter() - t0
            print(f"[progresso] ciclo={cyc} decorrido={el:.0f}s ({cyc / el:.0f} ciclos/s)", flush=True)

    collected = await _feed_image_and_collect(
        dut, np.vstack(images), stall_prob=0.0, seed=0, on_cycle=on_cycle)
    dt = time.perf_counter() - t0

    cyc = acc["cycles"]
    pred = _predicted_cycles(w, h, n)
    ok = collected == expected
    print(f"\nFRAME_FULL mode={_mode()} W={w} H={h} frames={n} px={len(expected)} cycles={cyc} "
          f"pred={pred} delta={cyc - pred:+d} sim_wall_s={dt:.1f} cyc_per_s={cyc / dt:.0f} "
          f"win_valid_real={acc['real']}/{n * w * h} o_status={acc['status']:03b} golden_ok={ok}",
          flush=True)

    assert len(collected) == len(expected), f"len(collected)={len(collected)} != {len(expected)}"
    if not ok:
        i = next(k for k, (g, e) in enumerate(zip(collected, expected)) if g != e)
        n_bad = sum(1 for g, e in zip(collected, expected) if g != e)
        fr, rem = divmod(i, w * h)
        r, c = divmod(rem, w)
        raise AssertionError(
            f"{n_bad}/{len(expected)} pixels divergem; 1a divergencia idx={i} "
            f"(frame={fr + 1}, linha={r}, col={c}): obtido={collected[i]} esperado={expected[i]}")
    assert acc["real"] == n * w * h, f"win_valid_real={acc['real']} != {n * w * h}"
    assert acc["status"] == 0, f"o_status={acc['status']:03b} (esperado 000)"


@pytest.mark.skipif(not RUN_SLOW, reason="teste lento: defina RUN_SLOW=1 (ou use `make frame`)")
def test_frame_full_runner():
    w = int(os.environ.get("FRAME_W", "640"))
    h = int(os.environ.get("FRAME_H", "480"))
    n = int(os.environ.get("FRAME_N", "2"))
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mode = _mode()
    tag = {"icarus": "ic", "verilator": "vl", "verilator+cov": "vlcov"}[mode]
    sim_build = os.path.join(root, "sim", f"sim_build_frame_{tag}_w{w}_h{h}")
    for d in (sim_build, sim_build + "_cov"):
        shutil.rmtree(d, ignore_errors=True)  # nunca herdar build de RTL antigo

    # -g2012/-Wall sao flags do Icarus; no modo cobertura o gancho os remove sozinho.
    compile_args = ["-Wno-fatal"] if mode == "verilator" else ["-g2012", "-Wall"]

    t0 = time.perf_counter()
    run_isolated(
        "frame_full",
        verilog_sources=[os.path.join(root, "rtl", d, f) for d, f in [
            ("common", "line_buffer_2line.sv"), ("common", "window_3x3.sv"),
            ("common", "line_window_skid.sv"), ("common", "abs_saturate.sv"),
            ("common", "magnitude_l1.sv"), ("multicycle", "mac_unit.sv"),
            ("multicycle", "kernel_rom.sv"), ("multicycle", "mac_control_fsm.sv"),
            ("multicycle", "skid_fifo2.sv"), ("multicycle", "sobel_multicycle.sv")]],
        includes=[os.path.join(root, "include")],
        toplevel="sobel_multicycle",
        module="test_frame_640x480",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": w, "IMG_HEIGHT": h,
                    "COEFF_WIDTH": COEFF_WIDTH, "ACC_WIDTH": ACC_WIDTH},
        compile_args=compile_args,
        sim_build=sim_build,
        extra_env={"TEST_IMG_WIDTH": str(w), "TEST_IMG_HEIGHT": str(h), "FRAME_N": str(n)},
    )
    print(f"FRAME_TOTAL mode={mode} W={w} H={h} frames={n} total_wall_s={time.perf_counter() - t0:.1f} "
          f"(build + simulacao + partida)", flush=True)
