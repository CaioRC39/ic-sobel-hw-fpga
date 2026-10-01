"""Instrumentacao minima (Lesson #1/#2 de RESUMO_ESTADO_PROJETO.md,
secao 'Sessao de depuracao adicional 2026-08-15'): impressao
INCONDICIONAL de lb_valid_in nos primeiros ~30 ciclos, via callback
on_cycle no laco ja validado _feed_image_and_collect - sem laco de
conducao proprio, sem logica de filtro/contagem. Nao faz parte da
suite normal (`make cocotb`); rodar isolado (ver instrucoes no final).
"""

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

N_CYCLES_TO_PRINT = 30


@cocotb.test()
async def test_lb_valid_in_minimal_trace(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    image = (np.arange(1, IMG_HEIGHT * IMG_WIDTH + 1) * 17 % 256).reshape(IMG_HEIGHT, IMG_WIDTH)

    def on_cycle(cyc, i_valid, i_pixel):
        if cyc < N_CYCLES_TO_PRINT:
            print(f"cyc={cyc:3d} i_valid={i_valid} i_pixel={i_pixel:3d} "
                  f"o_ready={int(dut.o_ready.value)} lb_valid_in={int(dut.lb_valid_in.value)}")

    await _feed_image_and_collect(dut, image, stall_prob=0.0, on_cycle=on_cycle)


def test_lb_valid_in_minimal_trace_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_lb_valid_in_minimal_trace")

    run_isolated(
        "test_lb_valid_in_minimal_trace",
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
        module="test_lb_valid_in_minimal_trace",
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
    test_lb_valid_in_minimal_trace_runner()