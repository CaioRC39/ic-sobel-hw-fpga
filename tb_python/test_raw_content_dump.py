"""Dump do CONTEUDO REAL (nao comparado contra nenhuma referencia
construida por mim - apenas observacao direta, sem risco de bug de
indexacao proprio) das janelas em cada win_valid=1, com contador de
grupo (a cada 4 pulsos = 1 grupo/linha), para os primeiros grupos
apos cada fronteira de frame. Objetivo: comparar ESTRUTURALMENTE
fronteira#1 (frame2, resultado final correto) vs fronteira#2/#3
(frame3/4, resultado final incorreto)."""
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


def _unpack_window(raw: int, data_width: int):
    mask = (1 << data_width) - 1
    window = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
    for r in range(3):
        for c in range(3):
            k = 3 * r + c
            shift = (8 - k) * data_width
            window[r][c] = (raw >> shift) & mask
    return window


@cocotb.test()
async def test_raw_content_dump(dut):
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
    for i, im in enumerate(images):
        print(f"imagem {i+1} (linhas reais): {im.tolist()}")

    pulses = []  # (frame_idx, win, vreal, geom)

    for frame_idx, image in enumerate(images):
        def on_cycle(cyc, i_valid, i_pixel, _fidx=frame_idx):
            if int(dut.win_valid.value):
                raw = int(dut.u_window.o_window.value)
                win = _unpack_window(raw, DATA_WIDTH)
                vreal = int(dut.win_valid_real.value)
                geom = int(dut.u_window.o_window_valid_geom.value)
                pulses.append((_fidx + 1, win, vreal, geom))

        collected = await _feed_image_and_collect(dut, image, stall_prob=0.0,
                                                    seed=frame_idx, on_cycle=on_cycle)
        print(f"[frame {frame_idx+1}] collected={len(collected)} valores={collected}")

    print(f"\n=== TODOS OS {len(pulses)} PULSOS (frame_python, janela, win_valid_real, geom) ===")
    for i, (fidx, win, vreal, geom) in enumerate(pulses):
        print(f"  idx={i:3d} frame={fidx} vreal={vreal} geom={geom} win={win}")


def test_raw_content_dump_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_raw_content_dump")
    run_isolated(
        "test_raw_content_dump",
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
        module="test_raw_content_dump",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH,
                    "IMG_HEIGHT": IMG_HEIGHT, "COEFF_WIDTH": COEFF_WIDTH,
                    "ACC_WIDTH": ACC_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


if __name__ == "__main__":
    test_raw_content_dump_runner()
