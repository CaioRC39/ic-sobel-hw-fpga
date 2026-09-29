"""Diagnostico dedicado (NAO faz parte da suite normal - mesmo padrao
de docs/MANIFESTO_SCRIPTS_DIAG_F-16.md e CLAUDE.md 14.3/15.9/15.11.2)
para a UNICA divergencia restante apos a correcao da Alternativa A3:
test_four_consecutive_frames, frame 3, idx=7 (linha=1, col=3),
obtido=154, esperado=255.

NAO propoe nem aplica nenhuma correcao de RTL - e so instrumentacao,
seguindo CLAUDE.md 15.11.2 ("evidencia real antes de qualquer
alternativa de correcao").

Metodologia (2 streams correlacionados POR INDICE, nao por ciclo -
mesmo principio ja usado no projeto para comparar sequencias
ordenadas por uma FIFO que preserva ordem):

  Stream A (o que a FSM de fato usou): deteccao de MUDANCA em win_reg
  (registrador dentro de u_fsm=mac_control_fsm), mesma tecnica ja
  validada e robusta de test_win_reg_direct.py - cada mudanca
  corresponde a exatamente 1 janela aceita pela FSM, na ORDEM em que
  chegaram (FIFO skid_fifo2 preserva ordem).

  Stream B (o que window_3x3 emitiu e o que decidiu se aquela janela
  era "pura"): toda ocorrencia de win_valid_real=1 (a UNICA porta de
  entrada de dados em u_skid) - captura o_window (conteudo bruto),
  win_window_valid_geom, win_tag, frame_tag_r NAQUELE instante.

  Como win_valid_real e a UNICA fonte que alimenta u_skid, e u_skid
  preserva ordem FIFO, o i-esimo evento do Stream B corresponde
  exatamente ao i-esimo evento do Stream A - permite comparar, por
  indice, "o que geom/tag diziam sobre esta janela quando ela entrou"
  vs "o que a FSM efetivamente calculou a partir dela".

Reusa _feed_image_and_collect ja validado (nunca um laco de conducao
proprio - licao de processo ja registrada em RESUMO_ESTADO_PROJETO.md).
"""

import os

import numpy as np

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge

from _cocotb_helpers import run_isolated
from test_sobel_multicycle import _feed_image_and_collect, _reference_sobel_l1

DATA_WIDTH = 8
COEFF_WIDTH = 3
ACC_WIDTH = 11
IMG_WIDTH = 4
IMG_HEIGHT = 3


def _unpack_window(raw: int, data_width: int):
    mask = (1 << data_width) - 1
    window = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
    for r in range(3):
        for c in range(3):
            k = 3 * r + c
            shift = (8 - k) * data_width
            window[r][c] = (raw >> shift) & mask
    return window


def _read_win_reg(dut):
    vals = [int(dut.u_fsm.win_reg[i].value) for i in range(9)]
    return [[vals[0], vals[1], vals[2]],
            [vals[3], vals[4], vals[5]],
            [vals[6], vals[7], vals[8]]]


@cocotb.test()
async def test_frame3_idx7_diagnostic(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    images = [
        (np.arange(1, IMG_HEIGHT * IMG_WIDTH + 1) * 17 % 256).reshape(IMG_HEIGHT, IMG_WIDTH),
        (np.arange(50, 50 + IMG_HEIGHT * IMG_WIDTH) * 23 % 256).reshape(IMG_HEIGHT, IMG_WIDTH),
        (np.arange(7, 7 + IMG_HEIGHT * IMG_WIDTH) * 31 % 256).reshape(IMG_HEIGHT, IMG_WIDTH),
        (np.arange(100, 100 + IMG_HEIGHT * IMG_WIDTH) * 41 % 256).reshape(IMG_HEIGHT, IMG_WIDTH),
    ]

    # Stream A (por frame): (cyc, win_reg_content, out_pixel_associado)
    streamA_per_frame = [[] for _ in images]
    # Stream B (por frame): (cyc, o_window, geom, win_tag, frame_tag_r)
    streamB_per_frame = [[] for _ in images]

    for frame_idx, image in enumerate(images):
        prev_win = None
        cyc_holder = {"c": 0}

        def on_cycle(cyc, i_valid, i_pixel, _fidx=frame_idx):
            nonlocal prev_win
            cyc_holder["c"] = cyc

            # Stream B: toda entrada real no skid (win_valid_real)
            if int(dut.win_valid_real.value):
                raw = int(dut.u_window.o_window.value)
                win = _unpack_window(raw, DATA_WIDTH)
                geom = int(dut.u_window.o_window_valid_geom.value)
                tag = int(dut.win_tag.value)
                ftag = int(dut.frame_tag_r.value)
                streamB_per_frame[_fidx].append((cyc, win, geom, tag, ftag))

            # Stream A: mudanca em win_reg (registrador real dentro da FSM)
            cur_win = _read_win_reg(dut)
            if prev_win is not None and cur_win != prev_win:
                streamA_per_frame[_fidx].append((cyc, cur_win))
            prev_win = cur_win

        collected = await _feed_image_and_collect(
            dut, image, stall_prob=0.0, seed=frame_idx, on_cycle=on_cycle
        )
        expected = _reference_sobel_l1(image)
        print(f"[frame {frame_idx+1}/4] collected={collected}")
        print(f"[frame {frame_idx+1}/4] expected ={expected}")
        mism = [(i, g, e) for i, (g, e) in enumerate(zip(collected, expected)) if g != e]
        print(f"[frame {frame_idx+1}/4] mismatches={mism}")

    # Foco: frame 3 (indice python 2), correlacionando Stream A x Stream B
    # POR INDICE (ordem preservada pela FIFO u_skid).
    print("\n" + "=" * 70)
    print("=== FRAME 3 - correlacao Stream A (win_reg/FSM) x Stream B (geom/tag) ===")
    print("=" * 70)
    fidx = 2  # frame 3, 0-indexed
    A = streamA_per_frame[fidx]
    B = streamB_per_frame[fidx]
    print(f"len(StreamA)={len(A)}  len(StreamB)={len(B)}")

    n = min(len(A), len(B))
    for i in range(n):
        cycA, winA = A[i]
        cycB, winB, geom, tag, ftag = B[i]
        row, col = divmod(i, IMG_WIDTH)
        marker = "  <<<< IDX 7 (o pixel divergente) >>>>" if i == 7 else ""
        content_match = (winA == winB)
        print(f"\n--- indice={i} (linha={row}, col={col}){marker} ---")
        print(f"  StreamB: cyc={cycB} geom={geom} win_tag={tag} frame_tag_r={ftag} "
              f"win={winB}")
        print(f"  StreamA: cyc={cycA} win_reg={winA}")
        print(f"  StreamA==StreamB (win_reg bate com o que window_3x3 emitiu)? {content_match}")

    print("\n=== RESUMO ===")
    print("Se, no indice 7, geom==0: o_window_valid_geom classificou "
          "corretamente como impura, mas a janela AINDA ASSIM chegou na FSM "
          "-> bug no GATE (win_valid_real ou downstream), nao no calculo de geom.")
    print("Se, no indice 7, geom==1 e win_reg==winB, mas o conteudo (winB) "
          "diverge da janela geometricamente correta esperada -> geom teve "
          "FALSO NEGATIVO (tags bateram, mas o conteudo/pixel esta errado "
          "por outro motivo - ex: timing do ciclo fantasma vs line_window_skid).")
    print("Se, no indice 7, win_reg != winB (StreamA diverge de StreamB) -> "
          "a FSM usou um conteudo DIFERENTE do que window_3x3 emitiu - bug "
          "entre window_3x3 e win_reg (skid_fifo2 ou a propria FSM).")


def test_frame3_idx7_diagnostic_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_frame3_idx7_diagnostic")
    run_isolated(
        "test_frame3_idx7_diagnostic",
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
        module="test_frame3_idx7_diagnostic",
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
    test_frame3_idx7_diagnostic_runner()

# ---------------------------------------------------------------------
# COMO RODAR (no repositorio REAL, nao neste ambiente de chat - ver
# CLAUDE.md 14.3 sobre distinguir evidencia real de reproducao):
#
#   cp test_frame3_idx7_diagnostic.py <repo>/tb_python/
#   cd <repo>/tb_python
#   python3 -m pytest test_frame3_idx7_diagnostic.py -v -s
#
# Colar de volta na conversa:
#   1. Os 4 blocos "[frame N/4] mismatches=..." (confirma que so o
#      frame 3, idx=7, diverge - nenhuma regressao nova).
#   2. O bloco inteiro "=== FRAME 3 - correlacao ... ===" (a tabela
#      completa dos ~12 indices, nao so o idx=7 - o contexto ao redor
#      importa tanto quanto o proprio indice divergente).
#   3. O bloco "=== RESUMO ===".
#
# NADA neste script altera RTL - e puramente observacional. A proxima
# correcao so sera proposta depois de ver esse resultado real.
# ---------------------------------------------------------------------
