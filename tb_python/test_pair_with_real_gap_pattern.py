"""Testa line_buffer_2line + window_3x3 EM CONJUNTO (par isolado, sem
sobel_multicycle/mac_control_fsm por perto), alimentados o mais rapido
possivel respeitando window_3x3.o_ready dinamicamente (mesmo gating
que sobel_multicycle usa via accept_sample) - compara o_window contra
a referencia com padding inferior. Isola definitivamente: bug na
combinacao dos 2 modulos comuns, vs bug na integracao com
mac_control_fsm/skid-buffer dentro de sobel_multicycle."""
import os

import numpy as np

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge

from _cocotb_helpers import run_isolated

DATA_WIDTH = 8
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


def _build_reference_windows_with_bottom_padding(image: np.ndarray):
    h, w = image.shape
    padded = np.pad(image, 1, mode="constant", constant_values=0)
    windows = []
    for r in range(h):
        for col in range(w):
            win = padded[r:r + 3, col:col + 3]
            windows.append(win.astype(int).tolist())
    return windows


WRAPPER_SRC = """
`include "timescale.svh"
module lb_window_pair #(
    parameter int DATA_WIDTH = 8,
    parameter int IMG_WIDTH = 4
)(
    input logic clk,
    input logic rst_n,
    input logic i_valid,
    input logic [DATA_WIDTH-1:0] i_pixel,
    output logic win_valid,
    output logic [9*DATA_WIDTH-1:0] win_window,
    output logic win_ready
);
    logic lb_valid;
    logic [DATA_WIDTH-1:0] lb_curr, lb_line1, lb_line2;
    logic lb_curr_tag, lb_line1_tag, lb_line2_tag;
    logic win_tag, win_geom;

    line_buffer_2line #(.DATA_WIDTH(DATA_WIDTH), .IMG_WIDTH(IMG_WIDTH)) u_lb (
        .clk(clk), .rst_n(rst_n),
        .i_valid(i_valid), .i_pixel(i_pixel),
        .i_tag(1'b0), .i_rearm(1'b0),
        .o_valid(lb_valid), .o_curr(lb_curr), .o_line1(lb_line1), .o_line2(lb_line2),
        .o_curr_tag(lb_curr_tag), .o_line1_tag(lb_line1_tag), .o_line2_tag(lb_line2_tag)
    );

    window_3x3 #(.DATA_WIDTH(DATA_WIDTH), .IMG_WIDTH(IMG_WIDTH)) u_win (
        .clk(clk), .rst_n(rst_n),
        .i_valid(lb_valid), .i_curr(lb_curr), .i_line1(lb_line1), .i_line2(lb_line2),
        .i_curr_tag(lb_curr_tag), .i_line1_tag(lb_line1_tag), .i_line2_tag(lb_line2_tag),
        .o_ready(win_ready), .o_valid(win_valid), .o_window(win_window),
        .o_tag(win_tag), .o_window_valid_geom(win_geom)
    );
endmodule
"""


@cocotb.test()
async def test_pair_real_pattern(dut):
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
    expected = _build_reference_windows_with_bottom_padding(image)
    print(f"expected ({len(expected)}): {expected}")

    # Alimenta respeitando win_ready dinamicamente (mesmo gating que
    # sobel_multicycle usa via accept_sample=win_ready&&...) - o mais
    # rapido possivel (sem gating de FSM aqui, ja que nao ha FSM neste
    # par isolado), garantindo que o contrato de interface de
    # window_3x3 nunca seja violado.
    idx = 0
    captured = []
    cyc = 0
    max_cycles = 200
    while cyc < max_cycles:
        await ReadOnly()
        win_ready = int(dut.win_ready.value)
        wv = int(dut.win_valid.value)
        ww = _unpack_window(int(dut.win_window.value), DATA_WIDTH) if wv else None
        await NextTimeStep()
        if wv:
            captured.append(ww)

        present_now = win_ready and idx < len(flat)
        dut.i_valid.value = 1 if present_now else 0
        dut.i_pixel.value = flat[idx] if present_now else 0
        if present_now:
            idx += 1

        await RisingEdge(dut.clk)
        cyc += 1
        if idx >= len(flat) and len(captured) >= 16:
            break

    dut.i_valid.value = 0

    print(f"captured ({len(captured)}): {captured}")
    real_captured = captured[IMG_WIDTH:]
    n = min(len(real_captured), len(expected))
    n_mismatch = 0
    for i in range(n):
        if real_captured[i] != expected[i]:
            n_mismatch += 1
            print(f"  MISMATCH idx={i}: obtido={real_captured[i]} esperado={expected[i]}")
    print(f"=== RESUMO: comparados={n} mismatches={n_mismatch} "
          f"len(real_captured)={len(real_captured)} len(expected)={len(expected)} ===")


def test_pair_real_pattern_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_pair_real_pattern")
    wrapper_path = os.path.join(sim_build, "lb_window_pair.sv")
    os.makedirs(sim_build, exist_ok=True)
    with open(wrapper_path, "w") as f:
        f.write(WRAPPER_SRC)

    run_isolated(
        "test_pair_real_pattern",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "line_buffer_2line.sv"),
            os.path.join(proj_root, "rtl", "common", "window_3x3.sv"),
            wrapper_path,
        ],
        includes=[os.path.join(proj_root, "include")],
        toplevel="lb_window_pair",
        module="test_pair_with_real_gap_pattern",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


if __name__ == "__main__":
    test_pair_real_pattern_runner()
