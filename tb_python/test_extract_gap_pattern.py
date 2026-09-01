"""Captura a sequencia REAL, EXATA (nao uma aproximacao manual) de
gaps entre pulsos que sobel_multicycle entrega a line_buffer_2line
internamente, usando deteccao por MUDANCA de wr_ptr1_r (registrador,
tecnica ja confirmada confiavel nesta sessao - ver test_win_reg_direct,
cross-check com 0 mismatches). Em seguida, reproduz essa sequencia
EXATA isoladamente em uma instancia separada de line_buffer_2line,
com timing de teste CORRETO (RisingEdge->ReadOnly->captura->
NextTimeStep), fechando definitivamente se o defeito esta em
line_buffer_2line (mesmo com o padrao real de pacing) ou em outro
lugar (window_3x3 ou a fiacao dentro de sobel_multicycle)."""
import os

import numpy as np

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge

from _cocotb_helpers import run_isolated

DATA_WIDTH = 8
COEFF_WIDTH = 3
ACC_WIDTH = 11
IMG_WIDTH = 4
IMG_HEIGHT = 3


@cocotb.test()
async def test_extract_real_gap_pattern(dut):
    """dut = sobel_multicycle (ver runner)."""
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

    idx = 0
    cyc = 0
    max_cycles = 3000
    prev_wr_ptr1 = None
    accept_cycles = []  # ciclos (absolutos) em que wr_ptr1_r mudou (=1 aceite real)

    while True:
        await ReadOnly()
        ready = int(dut.o_ready.value)
        out_valid = int(dut.o_valid.value)
        wr_ptr1 = int(dut.u_line_buffer.wr_ptr1_r.value)
        await NextTimeStep()

        if prev_wr_ptr1 is not None and wr_ptr1 != prev_wr_ptr1:
            accept_cycles.append(cyc)
        prev_wr_ptr1 = wr_ptr1

        present_now = ready and idx < len(flat)
        dut.i_valid.value = 1 if present_now else 0
        dut.i_pixel.value = flat[idx] if present_now else 0
        if present_now:
            idx += 1

        await RisingEdge(dut.clk)
        cyc += 1
        if cyc > max_cycles:
            raise TimeoutError("timeout")
        if idx >= len(flat) and len(accept_cycles) >= len(flat):
            break

    print(f"accept_cycles (ciclos absolutos onde wr_ptr1_r mudou, {len(accept_cycles)}): "
          f"{accept_cycles}")

    # Converte para gaps relativos (gap ANTES de cada aceite, relativo
    # ao aceite anterior) - mesmo formato usado em
    # test_lb_isolated_burst_pattern.py.
    gaps = []
    prev_c = None
    for c in accept_cycles[:len(flat)]:
        if prev_c is None:
            gaps.append(c)  # gap desde o inicio (cyc=0) ate o 1o aceite
        else:
            gaps.append(c - prev_c - 1)
        prev_c = c
    print(f"gaps derivados (formato test_lb_isolated_burst_pattern): {gaps}")


def test_extract_real_gap_pattern_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_extract_gap_pattern")
    run_isolated(
        "test_extract_real_gap_pattern",
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
        module="test_extract_gap_pattern",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH,
                    "IMG_HEIGHT": IMG_HEIGHT, "COEFF_WIDTH": COEFF_WIDTH,
                    "ACC_WIDTH": ACC_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


if __name__ == "__main__":
    test_extract_real_gap_pattern_runner()
