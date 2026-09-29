"""Teste dedicado (NAO faz parte da suite normal, NAO altera RTL) para
CONFIRMAR ou REFUTAR, por execucao real, a hipotese central de
docs/MODELO_LATENCIA_PIPELINE.md: window_3x3 emite, em TODO frame (nao
so no 1o), IMG_WIDTH janelas espurias correspondentes a uma "linha de
saida -1" virtual - gerada porque i_rearm forca line1/line2 de volta a
zero-padding no 1o ciclo de cada frame (Alternativa 3-C, necessaria e
correta), mas o mecanismo de descarte do integrador
(discard_cnt_r/warmup_done_r em sobel_multicycle.sv) so dispara 1x na
vida do modulo.

Metodologia: usa o modelo de identidade (models/pipeline_identity_model.py)
para prever, em ordem, quais das janelas RAW (win_valid, NAO
win_valid_real - deliberadamente ignora frame_tag_r/geom, que ja se
provaram nao confiaveis como indicador de conteudo) sao espurias -
compara essa previsao contra o CONTEUDO REAL de cada janela emitida
(pixels, nao tags): uma janela prevista como espuria deveria ter
line1 e line2 TODOS ZERO (e curr tambem zero, ja que corresponde a
"linha -1", onde nem curr teria dado real ainda vindo da linha 0) -
uma janela prevista como real deveria ter conteudo != 0 (exceto
posicoes legitimamente zero por padding de borda esq/dir/inferior,
tratadas separadamente).

Reusa _feed_image_and_collect ja validado (nunca laco de conducao
proprio - licao de processo ja registrada no projeto).
"""

import os
import sys

import numpy as np

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from _cocotb_helpers import run_isolated
from test_sobel_multicycle import _feed_image_and_collect, _reference_sobel_l1

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "models"))
from pipeline_identity_model import predict_window_stream, LogicalPos

DATA_WIDTH = 8
COEFF_WIDTH = 3
ACC_WIDTH = 11
IMG_WIDTH = 4
IMG_HEIGHT = 3
N_FRAMES = 4


def _unpack_window(raw: int, data_width: int):
    mask = (1 << data_width) - 1
    window = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
    for r in range(3):
        for c in range(3):
            k = 3 * r + c
            shift = (8 - k) * data_width
            window[r][c] = (raw >> shift) & mask
    return window


def _images():
    return [
        (np.arange(1, IMG_HEIGHT * IMG_WIDTH + 1) * 17 % 256).reshape(IMG_HEIGHT, IMG_WIDTH),
        (np.arange(50, 50 + IMG_HEIGHT * IMG_WIDTH) * 23 % 256).reshape(IMG_HEIGHT, IMG_WIDTH),
        (np.arange(7, 7 + IMG_HEIGHT * IMG_WIDTH) * 31 % 256).reshape(IMG_HEIGHT, IMG_WIDTH),
        (np.arange(100, 100 + IMG_HEIGHT * IMG_WIDTH) * 41 % 256).reshape(IMG_HEIGHT, IMG_WIDTH),
    ]


@cocotb.test()
async def test_identity_model_vs_raw_window_content(dut):
    """IMPORTANTE: este teste le win_valid (RAW), nao win_valid_real -
    de proposito, para nao depender do gate ja demonstrado nao
    confiavel (geom/tag). Compara cada janela RAW, em ordem, contra a
    predicao do modelo de identidade."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    images = _images()
    captured = []  # (window, is_real_predicted, logicalpos_predicted)

    predicted = predict_window_stream(IMG_WIDTH, IMG_HEIGHT, N_FRAMES)
    pred_idx_holder = {"i": 0}

    for frame_idx, image in enumerate(images):
        def on_cycle(cyc, i_valid, i_pixel):
            if int(dut.win_valid.value):
                raw = int(dut.u_window.o_window.value)
                win = _unpack_window(raw, DATA_WIDTH)
                idx = pred_idx_holder["i"]
                if idx < len(predicted):
                    is_real, pos = predicted[idx]
                    captured.append((win, is_real, pos))
                pred_idx_holder["i"] += 1

        await _feed_image_and_collect(dut, image, stall_prob=0.0, seed=frame_idx,
                                       on_cycle=on_cycle)

    print(f"\n=== TOTAL de janelas RAW capturadas: {len(captured)} "
          f"(modelo previu {len(predicted)}) ===")

    # Para cada janela prevista como ESPURIA (linha de saida "-1"),
    # confirma que line1/line2 SAO REALMENTE ZERO (assinatura de
    # zero-padding pos-rearm) - se forem, a hipotese esta CONFIRMADA
    # por conteudo real, nao so por contagem.
    n_spurious_checked = 0
    n_spurious_confirmed_zero = 0
    n_real_checked = 0
    n_real_nonzero = 0
    mismatches_espurio_com_dado_real = []

    for i, (win, is_real, pos) in enumerate(captured):
        line1_line2_all_zero = (win[0] == [0, 0, 0] and win[1] == [0, 0, 0])
        if not is_real:
            n_spurious_checked += 1
            if line1_line2_all_zero:
                n_spurious_confirmed_zero += 1
            else:
                mismatches_espurio_com_dado_real.append((i, win))
        else:
            n_real_checked += 1
            if not line1_line2_all_zero:
                n_real_nonzero += 1

    print(f"\n=== Janelas previstas ESPURIAS pelo modelo: {n_spurious_checked} ===")
    print(f"  confirmadas com line1/line2 TODOS ZERO (assinatura de zero-padding "
          f"pos-rearm): {n_spurious_confirmed_zero}/{n_spurious_checked}")
    if mismatches_espurio_com_dado_real:
        print(f"  *** {len(mismatches_espurio_com_dado_real)} janela(s) prevista(s) "
              f"espuria(s) mas com DADO REAL (nao-zero) - hipotese REFUTADA nesses "
              f"casos: ***")
        for (i, win) in mismatches_espurio_com_dado_real[:10]:
            print(f"    idx={i} window={win}")

    print(f"\n=== Janelas previstas REAIS pelo modelo: {n_real_checked} ===")
    print(f"  com line1 ou line2 nao-totalmente-zero (esperado para a maioria, "
          f"exceto padding legitimo de borda): {n_real_nonzero}/{n_real_checked}")

    print(f"\n=== VEREDITO ===")
    if n_spurious_checked > 0 and n_spurious_confirmed_zero == n_spurious_checked:
        print("HIPOTESE CONFIRMADA por conteudo real: TODAS as janelas previstas "
              "como espurias (linha de saida '-1' de CADA frame, nao so do frame 0) "
              "tem line1/line2 genuinamente zero - consistente com serem geradas "
              "pelo rearm e NUNCA descartadas apos o frame 0.")
    else:
        print("HIPOTESE NAO TOTALMENTE CONFIRMADA - ver mismatches acima, "
              "investigacao adicional necessaria antes de qualquer correcao.")


def test_identity_model_vs_raw_window_content_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_identity_model_validation")
    run_isolated(
        "test_identity_model_vs_raw_window_content",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "line_buffer_2line.sv"),
            os.path.join(proj_root, "rtl", "common", "window_3x3.sv"),
            os.path.join(proj_root, "rtl", "common", "line_window_skid.sv"),
            os.path.join(proj_root, "rtl", "common", "abs_saturate.sv"),
            os.path.join(proj_root, "rtl", "common", "magnitude_l1.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "mac_unit.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "kernel_rom.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "mac_control_fsm.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "skid_fifo2.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "sobel_multicycle.sv"),
        ],
        includes=[os.path.join(proj_root, "include")],
        toplevel="sobel_multicycle",
        module="test_pipeline_identity_model",
        parameters={
            "DATA_WIDTH": DATA_WIDTH,
            "IMG_WIDTH": IMG_WIDTH,
            "IMG_HEIGHT": IMG_HEIGHT,
            "COEFF_WIDTH": COEFF_WIDTH,
            "ACC_WIDTH": ACC_WIDTH,
        },
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


if __name__ == "__main__":
    test_identity_model_vs_raw_window_content_runner()

# ---------------------------------------------------------------------
# COMO RODAR (no repositorio REAL — IMPORTANTE: este teste depende do
# arquivo tb_python/models/pipeline_identity_model.py, que precisa ser
# copiado junto):
#
#   mkdir -p <repo>/tb_python/models
#   cp models/pipeline_identity_model.py <repo>/tb_python/models/
#   cp test_pipeline_identity_model.py <repo>/tb_python/
#   cd <repo>/tb_python
#   python3 -m pytest test_pipeline_identity_model.py -v -s
#
# ANTES DE RODAR: reverta a Alternativa A em sobel_multicycle.sv (ela
# nao ataca a causa real e so acrescenta ruido a este diagnostico) -
# ver docs/MODELO_LATENCIA_PIPELINE.md secao 6.
#
# Colar de volta na conversa o bloco "=== VEREDITO ===" e os blocos
# acima dele (contagens de espurias/reais confirmadas).
# ---------------------------------------------------------------------
