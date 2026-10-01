"""Traca warmup1_cnt_r/warmup2_cnt_r/warm1/warm2 (line_buffer_2line) e
col_cnt_r/geom (window_3x3) ao redor das 3 fronteiras de frame (1-2,
2-3, 3-4), usando o mesmo callback on_cycle ja validado. Objetivo:
achar a DIFERENCA especifica entre a fronteira 1-2 (nao causa erro,
confirmado pela suite oficial) e as fronteiras 2-3/3-4 (causam erro)."""
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
async def test_compare_all_boundaries(dut):
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

    all_rows = []  # continuous, all frames

    for frame_idx, image in enumerate(images):
        def on_cycle(cyc, i_valid, i_pixel, _fidx=frame_idx):
            row = dict(
                frame=_fidx + 1,
                rearm=int(dut.frame_start_pulse.value),
                i_rearm_lb=int(dut.u_line_buffer.i_rearm.value),
                warm1=int(dut.u_line_buffer.warm1.value),
                warm2=int(dut.u_line_buffer.warm2.value),
                warmup1_cnt=int(dut.u_line_buffer.warmup1_cnt_r.value),
                warmup2_cnt=int(dut.u_line_buffer.warmup2_cnt_r.value),
                lb_valid_in=int(dut.lb_valid_in.value),
                win_valid=int(dut.win_valid.value),
                win_valid_real=int(dut.win_valid_real.value),
                geom=int(dut.u_window.o_window_valid_geom.value),
                col_cnt=int(dut.u_window.col_cnt_r.value),
                phantom=int(dut.u_window.phantom_pending_r.value),
                feed_cnt=int(dut.feed_cnt_r.value),
            )
            all_rows.append(row)

        collected = await _feed_image_and_collect(dut, image, stall_prob=0.0,
                                                    seed=frame_idx, on_cycle=on_cycle)
        print(f"[frame {frame_idx+1}] collected={len(collected)}")

    # ALTERADO: frame_start_pulse e combinacional (mesma pegadinha de
    # amostragem ja identificada nesta sessao para i_valid vs feed_cnt_r
    # - confirmado por evidencia real: 0 disparos capturados na 1a
    # tentativa, apesar do mecanismo existir no RTL). Deteccao robusta:
    # queda em warmup1_cnt_r (REGISTRADOR, nao fio combinacional) - a
    # mesma tecnica ja validada no historico do projeto
    # (test_confirm_rearm_skips_pulse_second_frame).
    rearm_indices = []
    prev_w1 = 0
    for i, r in enumerate(all_rows):
        if r["warmup1_cnt"] < prev_w1:
            rearm_indices.append(i)
        prev_w1 = r["warmup1_cnt"]
    print(f"\n=== {len(rearm_indices)} quedas de warmup1_cnt_r encontradas, "
          f"em indices: {rearm_indices} ===")

    for k, ridx in enumerate(rearm_indices):
        print(f"\n--- Fronteira #{k+1} (idx={ridx}, frame={all_rows[ridx]['frame']}) "
              f"- 3 ciclos antes ate 20 depois ---")
        header = ("  idx frame rearm i_rearm_lb warm1 warm2 warmup1_cnt warmup2_cnt "
                   "lb_valid_in win_valid win_valid_real geom col_cnt phantom feed_cnt")
        print(header)
        lo = max(0, ridx - 3)
        hi = min(len(all_rows), ridx + 20)
        for i in range(lo, hi):
            r = all_rows[i]
            print(f"  {i:4d} {r['frame']:5d} {r['rearm']:5d} {r['i_rearm_lb']:10d} "
                  f"{r['warm1']:5d} {r['warm2']:5d} {r['warmup1_cnt']:11d} "
                  f"{r['warmup2_cnt']:11d} {r['lb_valid_in']:11d} {r['win_valid']:9d} "
                  f"{r['win_valid_real']:14d} {r['geom']:4d} {r['col_cnt']:7d} "
                  f"{r['phantom']:7d} {r['feed_cnt']:8d}")


def test_compare_all_boundaries_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_compare_all_boundaries")
    run_isolated(
        "test_compare_all_boundaries",
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
        module="test_compare_boundaries",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH,
                    "IMG_HEIGHT": IMG_HEIGHT, "COEFF_WIDTH": COEFF_WIDTH,
                    "ACC_WIDTH": ACC_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


if __name__ == "__main__":
    test_compare_all_boundaries_runner()
