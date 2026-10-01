"""Traca INCONDICIONALMENTE (todo ciclo com lb_valid_in=1) os sinais
de saida de line_buffer_2line (o_curr, o_line1, warm1, warmup1_cnt_r)
para os primeiros pixels reais do frame de baixo contraste - sem
filtro de win_valid, sem depender de nenhum calculo de grupo/coluna
feito por mim. Objetivo: ver EXATAMENTE, pixel a pixel, o que
line_buffer_2line entrega e comparar contra o que deveria entregar
(o_line1 deveria mostrar o valor de 4 pixels atras, uma vez 'warm')."""
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
async def test_lb_output_unconditional_trace(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    image = np.array([
        [10, 12, 14, 16],
        [11, 13, 15, 17],
        [12, 14, 16, 18],
    ], dtype=int)
    flat = image.flatten().tolist()
    print(f"flat (ordem real de alimentacao): {flat}")

    rows = []

    all_cycles = []

    def on_cycle(cyc, i_valid, i_pixel):
        all_cycles.append(dict(
            cyc=cyc,
            i_valid=i_valid,
            lb_valid_in=int(dut.lb_valid_in.value),
            warmup1_cnt=int(dut.u_line_buffer.warmup1_cnt_r.value),
            wr_ptr1=int(dut.u_line_buffer.wr_ptr1_r.value),
        ))
        if int(dut.lb_valid_in.value):
            rows.append(dict(
                pulse=len(rows),
                cyc=cyc,
                lb_pixel_in=int(dut.lb_pixel_in.value),
                o_curr=int(dut.u_line_buffer.o_curr.value),
                o_line1=int(dut.u_line_buffer.o_line1.value),
                warm1=int(dut.u_line_buffer.warm1.value),
                warmup1_cnt=int(dut.u_line_buffer.warmup1_cnt_r.value),
                wr_ptr1=int(dut.u_line_buffer.wr_ptr1_r.value),
                i_rearm=int(dut.u_line_buffer.i_rearm.value),
            ))

    collected = await _feed_image_and_collect(dut, image, stall_prob=0.0, seed=0,
                                                on_cycle=on_cycle)
    print(f"collected={collected}")

    print(f"\n=== TODOS os primeiros 15 ciclos (incondicional) ===")
    print("  cyc i_valid lb_valid_in warmup1_cnt wr_ptr1")
    for r in all_cycles[:15]:
        print(f"  {r['cyc']:3d} {r['i_valid']:7d} {r['lb_valid_in']:11d} "
              f"{r['warmup1_cnt']:11d} {r['wr_ptr1']:7d}")

    print(f"\n=== {len(rows)} pulsos reais (lb_valid_in=1) capturados - "
          f"primeiros 16 ===")
    header = ("  pulse cyc lb_pixel_in o_curr o_line1 warm1 warmup1_cnt wr_ptr1 "
              "i_rearm")
    print(header)
    for r in rows[:16]:
        print(f"  {r['pulse']:5d} {r['cyc']:3d} {r['lb_pixel_in']:11d} {r['o_curr']:6d} "
              f"{r['o_line1']:7d} {r['warm1']:5d} {r['warmup1_cnt']:11d} "
              f"{r['wr_ptr1']:7d} {r['i_rearm']:7d}")


def test_lb_output_unconditional_trace_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_lb_output_unconditional")
    run_isolated(
        "test_lb_output_unconditional_trace",
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
        module="test_lb_output_unconditional",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH,
                    "IMG_HEIGHT": IMG_HEIGHT, "COEFF_WIDTH": COEFF_WIDTH,
                    "ACC_WIDTH": ACC_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


if __name__ == "__main__":
    test_lb_output_unconditional_trace_runner()
