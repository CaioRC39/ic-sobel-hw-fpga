"""Traca a SEQUENCIA de col_cnt_r (window_3x3) em todo ciclo com
win_valid=1, ao longo dos 4 frames continuos - via on_cycle no laco ja
validado (_feed_image_and_collect). Objetivo: localizar exatamente o
ponto onde a sequencia 0,1,2,3,0,1,2,3,... deveria se repetir
periodicamente mas nao se repete (pulo ou repeticao de coluna),
correlacionando com win_valid_real e collected."""
import os

import numpy as np

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from _cocotb_helpers import run_isolated
from test_sobel_multicycle import _feed_image_and_collect

DATA_WIDTH = 8
COEFF_WIDTH = 3
ACC_WIDTH = 11
IMG_WIDTH = 4
IMG_HEIGHT = 3


@cocotb.test()
async def test_colcnt_sequence_trace(dut):
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

    seq = []  # (global_pulse_idx, frame_idx, col_cnt_r_no_momento_do_pulso, win_valid_real, feed_cnt)

    for frame_idx, image in enumerate(images):
        def on_cycle(cyc, i_valid, i_pixel, _frame_idx=frame_idx):
            w_valid = int(dut.win_valid.value)
            if w_valid:
                col_cnt = int(dut.u_window.col_cnt_r.value)
                phantom = int(dut.u_window.phantom_pending_r.value)
                w_valid_real = int(dut.win_valid_real.value)
                feed_cnt = int(dut.feed_cnt_r.value)
                seq.append((_frame_idx, col_cnt, phantom, w_valid_real, feed_cnt))

        collected = await _feed_image_and_collect(dut, image, stall_prob=0.0,
                                                    seed=frame_idx, on_cycle=on_cycle)
        print(f"[frame {frame_idx+1}] collected={len(collected)}")

    print(f"\n=== SEQUENCIA COMPLETA DE col_cnt_r NO INSTANTE DE win_valid=1 "
          f"({len(seq)} pulsos totais) ===")
    print("  idx frame col_cnt phantom win_valid_real feed_cnt")
    for i, (fidx, col, ph, vr, fc) in enumerate(seq):
        print(f"  {i:3d}   {fidx+1}     {col}       {ph}         {vr}          {fc}")

    # Verificacao adicional: a sequencia de col_cnt_r deveria SEMPRE
    # avancar 0,1,2,3,0,1,2,3,... nesta ordem exata, sem pulos nem
    # repeticoes, do primeiro ao ultimo pulso de TODA a simulacao
    # (window_3x3 e livre-corrente, sem nocao de frame).
    expected_col = 0
    first_break = None
    for i, (fidx, col, ph, vr, fc) in enumerate(seq):
        if col != expected_col and first_break is None:
            first_break = (i, fidx, col, expected_col)
        expected_col = (col + 1) % IMG_WIDTH
    if first_break:
        i, fidx, got, exp = first_break
        print(f"\n=== PRIMEIRA QUEBRA DE SEQUENCIA: pulso idx={i} (frame {fidx+1}) "
              f"col_cnt_r={got}, esperado (sequencial)={exp} ===")
    else:
        print("\n=== Nenhuma quebra de sequencia de col_cnt_r detectada ===")


def test_colcnt_sequence_trace_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_colcnt_sequence_trace")
    run_isolated(
        "test_colcnt_sequence_trace",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "line_buffer_2line.sv"),
            os.path.join(proj_root, "rtl", "common", "window_3x3.sv"),
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
        module="test_colcnt_sequence_trace",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH,
                    "IMG_HEIGHT": IMG_HEIGHT, "COEFF_WIDTH": COEFF_WIDTH,
                    "ACC_WIDTH": ACC_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


if __name__ == "__main__":
    test_colcnt_sequence_trace_runner()
