"""Compara o CONTEUDO de cada janela emitida por window_3x3 (via
sobel_multicycle) contra uma referencia de STREAM CONTINUO (todas as
linhas reais + 1 linha de padding por frame, concatenadas, SEM reset
de geometria entre frames - o modelo real que window_3x3 enxerga,
ja que o modulo nao tem nocao de frame). Usa o callback on_cycle JA
VALIDADO (nao um laco de conducao proprio)."""
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


def _build_reference_windows_continuous(rows_2d: np.ndarray):
    h, w = rows_2d.shape
    padded = np.pad(rows_2d, 1, mode="constant", constant_values=0)
    windows = []
    for out_row in range(h - 1):
        for col in range(w):
            win = padded[out_row:out_row + 3, col:col + 3]
            windows.append(win.astype(int).tolist())
    return windows


@cocotb.test()
async def test_content_vs_continuous_reference(dut):
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

    # Referencia: stream continuo (rows reais + 1 padding por frame),
    # SEM reset de geometria entre frames - modelo real de window_3x3.
    padding_row = np.zeros((1, IMG_WIDTH), dtype=int)
    continuous_rows = np.vstack([np.vstack([im, padding_row]) for im in images])
    expected_windows_full = _build_reference_windows_continuous(continuous_rows)
    expected_windows_real = expected_windows_full[IMG_WIDTH:]  # descarta "row -1" global

    raw_pulses = []  # (frame_python_idx, win_window, win_valid_real, geom)

    for frame_idx, image in enumerate(images):
        def on_cycle(cyc, i_valid, i_pixel, _fidx=frame_idx):
            if int(dut.win_valid.value):
                raw = int(dut.u_window.o_window.value)
                win = _unpack_window(raw, DATA_WIDTH)
                vreal = int(dut.win_valid_real.value)
                geom = int(dut.u_window.o_window_valid_geom.value)
                raw_pulses.append((_fidx + 1, win, vreal, geom))

        collected = await _feed_image_and_collect(dut, image, stall_prob=0.0,
                                                    seed=frame_idx, on_cycle=on_cycle)
        print(f"[frame {frame_idx+1}] collected={len(collected)}")

    print(f"\n=== TOTAL raw_pulses capturados: {len(raw_pulses)} "
          f"(esperado full={len(expected_windows_full)}) ===")

    # Descarta a 1a linha virtual global (IMG_WIDTH pulsos) das capturadas.
    real_pulses = raw_pulses[IMG_WIDTH:]
    print(f"real_pulses (pos-descarte topo)={len(real_pulses)} "
          f"expected_windows_real={len(expected_windows_real)}")

    n = min(len(real_pulses), len(expected_windows_real))
    n_content_mismatch = 0
    n_geom_wrongly_1 = 0
    n_geom_wrongly_0 = 0
    for i in range(n):
        fidx, win, vreal, geom = real_pulses[i]
        exp = expected_windows_real[i]
        content_ok = (win == exp)
        if not content_ok:
            n_content_mismatch += 1
            if n_content_mismatch <= 15:
                print(f"  CONTEUDO MISMATCH idx={i} (python-frame={fidx}) "
                      f"vreal={vreal} geom={geom} obtido={win} esperado={exp}")

    print(f"\n=== RESUMO: comparados={n} content_mismatches={n_content_mismatch} ===")
    print(f"len(real_pulses)={len(real_pulses)} vs len(expected_windows_real)="
          f"{len(expected_windows_real)} (diferenca={len(real_pulses)-len(expected_windows_real)})")


def test_content_vs_continuous_reference_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_content_vs_continuous")
    run_isolated(
        "test_content_vs_continuous_reference",
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
        module="test_content_vs_continuous",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH,
                    "IMG_HEIGHT": IMG_HEIGHT, "COEFF_WIDTH": COEFF_WIDTH,
                    "ACC_WIDTH": ACC_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


if __name__ == "__main__":
    test_content_vs_continuous_reference_runner()
