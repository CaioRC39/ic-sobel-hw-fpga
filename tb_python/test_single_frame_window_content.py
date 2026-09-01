"""Mesmo cenario de test_single_frame_low_contrast (1 frame isolado,
sem fronteira nenhuma), mas capturando o CONTEUDO de cada janela via
on_cycle - para comparar contra a referencia ja validada
(_build_reference_windows, do proprio test_window_3x3.py oficial) e
achar exatamente ONDE dentro do pipeline (line_buffer_2line ->
window_3x3 -> mac_control_fsm) o defeito esta."""
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


def _build_reference_windows(image: np.ndarray):
    """IDENTICA a test_window_3x3.py::_build_reference_windows (ja
    validada oficialmente) - reutilizada, nao reimplementada."""
    h, w = image.shape
    padded = np.pad(image, 1, mode="constant", constant_values=0)
    windows = []
    for out_row in range(h - 1):
        for col in range(w):
            win = padded[out_row:out_row + 3, col:col + 3]
            windows.append(win.astype(int).tolist())
    return windows


@cocotb.test()
async def test_single_frame_window_content(dut):
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

    expected_windows = _build_reference_windows(image)
    print(f"expected_windows ({len(expected_windows)}): {expected_windows}")

    pulses = []

    def on_cycle(cyc, i_valid, i_pixel):
        if int(dut.win_valid.value):
            raw = int(dut.u_window.o_window.value)
            win = _unpack_window(raw, DATA_WIDTH)
            vreal = int(dut.win_valid_real.value)
            pulses.append((win, vreal))

    collected = await _feed_image_and_collect(dut, image, stall_prob=0.0, seed=0,
                                                on_cycle=on_cycle)
    print(f"collected={collected}")
    print(f"total pulsos capturados: {len(pulses)}")

    # descarta a 1a linha virtual (warmup global) - mesma convencao de
    # test_window_3x3.py.
    real_pulses = pulses[IMG_WIDTH:]
    print(f"real_pulses (pos-descarte topo): {len(real_pulses)}")

    n = min(len(real_pulses), len(expected_windows))
    n_mismatch = 0
    for i in range(n):
        win, vreal = real_pulses[i]
        exp = expected_windows[i]
        if win != exp:
            n_mismatch += 1
            print(f"  MISMATCH janela idx={i}: vreal={vreal} obtido={win} esperado={exp}")
    print(f"=== RESUMO: comparadas={n} mismatches_conteudo={n_mismatch} "
          f"len(real_pulses)={len(real_pulses)} len(expected)={len(expected_windows)} ===")


def test_single_frame_window_content_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_single_frame_window_content")
    run_isolated(
        "test_single_frame_window_content",
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
        module="test_single_frame_window_content",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH,
                    "IMG_HEIGHT": IMG_HEIGHT, "COEFF_WIDTH": COEFF_WIDTH,
                    "ACC_WIDTH": ACC_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


if __name__ == "__main__":
    test_single_frame_window_content_runner()
