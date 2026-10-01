"""Traca TODO ciclo (nao so os com win_valid=1) ao redor da fronteira
frame1->frame2, mostrando lb_valid_in, win_valid, col_cnt_r,
phantom_pending_r, frame_tag_r, e as 3 tags vistas por window_3x3
(i_curr_tag/i_line1_tag/i_line2_tag, via porta de u_window) - para
localizar exatamente o que acontece com o "4o grupo" que falta em
frame2 (grupo que deveria corresponder a fronteira row3(padding,tag
frame1) -> row4(real, tag frame2))."""
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
async def test_tag_at_boundary_trace(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    image1 = (np.arange(1, IMG_HEIGHT * IMG_WIDTH + 1) * 17 % 256).reshape(IMG_HEIGHT, IMG_WIDTH)
    image2 = (np.arange(50, 50 + IMG_HEIGHT * IMG_WIDTH) * 23 % 256).reshape(IMG_HEIGHT, IMG_WIDTH)

    rows = []

    def make_on_cycle(frame_idx):
        def on_cycle(cyc, i_valid, i_pixel):
            row = dict(
                frame=frame_idx + 1,
                cyc=cyc,
                i_valid=i_valid,
                lb_valid_in=int(dut.lb_valid_in.value),
                win_valid=int(dut.win_valid.value),
                win_valid_real=int(dut.win_valid_real.value),
                col_cnt=int(dut.u_window.col_cnt_r.value),
                phantom=int(dut.u_window.phantom_pending_r.value),
                geom=int(dut.u_window.o_window_valid_geom.value),
                curr_tag=int(dut.u_window.i_curr_tag.value),
                line1_tag=int(dut.u_window.i_line1_tag.value),
                line2_tag=int(dut.u_window.i_line2_tag.value),
                frame_tag=int(dut.frame_tag_r.value),
                feed_cnt=int(dut.feed_cnt_r.value),
            )
            rows.append(row)
        return on_cycle

    collected1 = await _feed_image_and_collect(dut, image1, stall_prob=0.0, seed=1,
                                                on_cycle=make_on_cycle(0))
    print(f"[frame 1] collected={len(collected1)}, ciclos totais={len(rows)}")
    n_after_frame1 = len(rows)

    collected2 = await _feed_image_and_collect(dut, image2, stall_prob=0.0, seed=2,
                                                on_cycle=make_on_cycle(1))
    print(f"[frame 2] collected={len(collected2)}, ciclos totais(frame2)={len(rows) - n_after_frame1}")

    # Mostra os ultimos 20 ciclos do frame1 + os primeiros 30 do frame2 -
    # a janela onde a fronteira acontece.
    window_start = max(0, n_after_frame1 - 20)
    window_end = min(len(rows), n_after_frame1 + 30)

    print(f"\n=== CICLOS AO REDOR DA FRONTEIRA (indices {window_start}..{window_end}) ===")
    header = ("  idx frame cyc i_valid lb_valid_in win_valid win_valid_real col_cnt "
              "phantom geom curr_tag line1_tag line2_tag frame_tag feed_cnt")
    print(header)
    for i in range(window_start, window_end):
        r = rows[i]
        print(f"  {i:4d} {r['frame']:5d} {r['cyc']:4d} {r['i_valid']:7d} "
              f"{r['lb_valid_in']:11d} {r['win_valid']:9d} {r['win_valid_real']:14d} "
              f"{r['col_cnt']:7d} {r['phantom']:7d} {r['geom']:4d} {r['curr_tag']:8d} "
              f"{r['line1_tag']:9d} {r['line2_tag']:9d} {r['frame_tag']:9d} {r['feed_cnt']:8d}")


def test_tag_at_boundary_trace_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_tag_at_boundary_trace")
    run_isolated(
        "test_tag_at_boundary_trace",
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
        module="test_tag_at_boundary_trace",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH,
                    "IMG_HEIGHT": IMG_HEIGHT, "COEFF_WIDTH": COEFF_WIDTH,
                    "ACC_WIDTH": ACC_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


if __name__ == "__main__":
    test_tag_at_boundary_trace_runner()
