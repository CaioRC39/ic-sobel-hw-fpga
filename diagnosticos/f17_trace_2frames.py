import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tb_python"))

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
IMG_HEIGHT = 2
N_FRAMES = 2


@cocotb.test()
async def f17_trace_2frames(dut):
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
    ]

    trace = []

    def on_cycle(cyc, i_valid, i_pixel):
        if int(dut.win_valid.value):
            trace.append({
                'cyc': cyc,
                'win_cnt': int(dut.win_cnt_r.value),
                'spurious': int(dut.win_is_spurious.value),
                'valid_real': int(dut.win_valid_real.value),
                'frame_tag': int(dut.frame_tag_r.value),
            })

    for i, img in enumerate(images):
        await _feed_image_and_collect(dut, img, stall_prob=0.0, seed=i, on_cycle=on_cycle)

    print("\n=== F-17 TRACE (2 frames, IMG_WIDTH=4, IMG_HEIGHT=2) ===")
    print(f"Total de pulsos win_valid: {len(trace)} (esperado 24 = 2 × 12)")
    print("\nidx | frame_tag | win_cnt | spurious | valid_real")
    print("----|-----------|---------|----------|-----------")
    for i, e in enumerate(trace):
        print(f"{i:3d} |     {e['frame_tag']}     |    {e['win_cnt']:2d}   |"
              f"    {e['spurious']}     |     {e['valid_real']}")


def test_f17_trace_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_f17_trace")
    run_isolated(
        "f17_trace_2frames",
        verilog_sources=[os.path.join(proj_root, "rtl", d, f) for d, f in [
            ("common", "line_buffer_2line.sv"), ("common", "window_3x3.sv"),
            ("common", "line_window_skid.sv"), ("common", "abs_saturate.sv"),
            ("common", "magnitude_l1.sv"), ("multicycle", "mac_unit.sv"),
            ("multicycle", "kernel_rom.sv"), ("multicycle", "mac_control_fsm.sv"),
            ("multicycle", "skid_fifo2.sv"), ("multicycle", "sobel_multicycle.sv")]],
        includes=[os.path.join(proj_root, "include")],
        toplevel="sobel_multicycle",
        module="f17_trace_2frames",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH,
                    "IMG_HEIGHT": IMG_HEIGHT, "COEFF_WIDTH": COEFF_WIDTH,
                    "ACC_WIDTH": ACC_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


if __name__ == "__main__":
    test_f17_trace_runner()