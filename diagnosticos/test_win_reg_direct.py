"""Captura DIRETA de win_reg (dentro de u_fsm=mac_control_fsm) - um
REGISTRADOR (nao fio combinacional), atualizado em
'state_r==S_IDLE && i_valid' - o que efetivamente entra no calculo de
Gx/Gy. Usa deteccao por MUDANCA DE VALOR entre ciclos consecutivos
(tecnica ja validada nesta sessao para warmup1_cnt_r), evitando
qualquer leitura de fio combinacional na fronteira do ciclo."""
import os

import numpy as np

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge

from _cocotb_helpers import run_isolated
from test_sobel_multicycle import _feed_image_and_collect

DATA_WIDTH = 8
COEFF_WIDTH = 3
ACC_WIDTH = 11
IMG_WIDTH = 4
IMG_HEIGHT = 3


GX_KERNEL = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]])
GY_KERNEL = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]])


def _magnitude_from_window(win):
    w = np.array(win, dtype=int)
    gx = int(np.sum(w * GX_KERNEL))
    gy = int(np.sum(w * GY_KERNEL))
    return min(abs(gx) + abs(gy), 255)


def _build_reference_windows_with_bottom_padding(image: np.ndarray):
    """Referencia CORRETA para comparar com win_reg dentro de
    sobel_multicycle: inclui a linha de padding INFERIOR que
    sobel_multicycle adiciona (RealTotal->PaddedTotal), diferente de
    _build_reference_windows (usado so para testar window_3x3
    ISOLADO, sem essa linha extra) - mesma logica de padding que
    _reference_sobel_l1 (ja validada oficialmente) usa via
    np.pad(image,1), que cobre TODOS os 4 lados incluindo o de baixo."""
    h, w = image.shape
    padded = np.pad(image, 1, mode="constant", constant_values=0)
    windows = []
    for r in range(h):  # h saidas (nao h-1) - inclui a ultima linha real
        for col in range(w):
            win = padded[r:r + 3, col:col + 3]
            windows.append(win.astype(int).tolist())
    return windows


def _read_win_reg(dut):
    """Le os 9 elementos de win_reg (array unpacked de 9 x DATA_WIDTH
    bits dentro de u_fsm) e monta a janela 3x3 no mesmo layout
    [linha][coluna] usado por _build_reference_windows."""
    vals = [int(dut.u_fsm.win_reg[i].value) for i in range(9)]
    return [[vals[0], vals[1], vals[2]],
            [vals[3], vals[4], vals[5]],
            [vals[6], vals[7], vals[8]]]


@cocotb.test()
async def test_win_reg_direct_capture(dut):
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
    expected_windows = _build_reference_windows_with_bottom_padding(image)
    print(f"expected_windows ({len(expected_windows)}): {expected_windows}")

    idx = 0
    captured = []
    prev_win = None
    cyc = 0
    max_cycles = 3000
    out_pixels = []

    while True:
        await ReadOnly()
        ready = int(dut.o_ready.value)
        out_valid = int(dut.o_valid.value)
        pixel = int(dut.o_pixel.value) if out_valid else None
        cur_win = _read_win_reg(dut)
        state = int(dut.u_fsm.state_r.value)
        await NextTimeStep()

        if out_valid:
            out_pixels.append(pixel)

        # Detecta MUDANCA no conteudo de win_reg (registrador de
        # verdade) entre ciclos consecutivos - equivale a capturar
        # exatamente quando a FSM atualiza win_reg (S_IDLE&&i_valid).
        if prev_win is not None and cur_win != prev_win:
            captured.append((cyc, cur_win, state))
        prev_win = cur_win

        present_now = ready and idx < len(flat)
        dut.i_valid.value = 1 if present_now else 0
        dut.i_pixel.value = flat[idx] if present_now else 0
        if present_now:
            idx += 1

        await RisingEdge(dut.clk)
        cyc += 1
        if cyc > max_cycles:
            raise TimeoutError("timeout")
        if idx >= len(flat) and len(captured) >= 12:
            break

    print(f"\n=== VERIFICACAO CRUZADA: magnitude calculada de win_reg vs pixel real de saida ===")
    print(f"out_pixels (saida real, {len(out_pixels)}): {out_pixels}")
    calc_from_winreg = [_magnitude_from_window(w) for (c, w, s) in captured]
    print(f"calc_from_winreg ({len(calc_from_winreg)}): {calc_from_winreg}")
    n = min(len(out_pixels), len(calc_from_winreg))
    n_cross_mismatch = 0
    for i in range(n):
        if out_pixels[i] != calc_from_winreg[i]:
            n_cross_mismatch += 1
            print(f"  CROSS-MISMATCH idx={i}: pixel_real={out_pixels[i]} "
                  f"calc_de_win_reg={calc_from_winreg[i]}")
    print(f"=== RESUMO CRUZADO: comparados={n} cross_mismatches={n_cross_mismatch} "
          f"(0 = win_reg->saida esta consistente; a causa estaria ANTES de win_reg, "
          f"em como a janela e montada; >0 = ha inconsistencia ENTRE win_reg e a "
          f"saida, ou seja, win_reg NAO e a causa) ===")

    print(f"\n=== {len(captured)} mudancas de win_reg capturadas ===")
    for i, (c, win, st) in enumerate(captured[:20]):
        print(f"  idx={i:3d} cyc={c:4d} state={st:2d} win={win}")

    # Descarta a 1a janela capturada (corresponde ao valor inicial
    # pos-reset->1a escrita real, nao a uma "mudanca" util) e compara
    # o restante contra a referencia, na ordem.
    real_captured = [w for (c, w, s) in captured]
    n = min(len(real_captured), len(expected_windows))
    n_mismatch = 0
    for i in range(n):
        if real_captured[i] != expected_windows[i]:
            n_mismatch += 1
            print(f"  MISMATCH idx={i}: obtido={real_captured[i]} "
                  f"esperado={expected_windows[i]}")
    print(f"=== RESUMO: comparados={n} mismatches={n_mismatch} "
          f"len(captured)={len(real_captured)} len(expected)={len(expected_windows)} ===")


def test_win_reg_direct_capture_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_win_reg_direct")
    run_isolated(
        "test_win_reg_direct_capture",
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
        module="test_win_reg_direct",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH,
                    "IMG_HEIGHT": IMG_HEIGHT, "COEFF_WIDTH": COEFF_WIDTH,
                    "ACC_WIDTH": ACC_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


if __name__ == "__main__":
    test_win_reg_direct_capture_runner()
