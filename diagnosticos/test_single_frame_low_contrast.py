"""Teste decisivo, sem qualquer fronteira de frame envolvida: 1 UNICO
frame, imagem de BAIXO CONTRASTE (sem saturacao em 255) - segue a
'licao de processo' ja registrada em RESUMO_ESTADO_PROJETO.md
('imagens que saturam mascaram bugs de conteudo'). Se o resultado
bater 100% com a referencia, confirma que sobel_multicycle esta
correto para o caso de 1 frame isolado, e o defeito encontrado em
test_four_consecutive_frames e necessariamente algo que so aparece
GRACAS a fronteira entre frames (rearm/tag), nao um bug generico de
pipeline dentro de um frame."""
import os

import numpy as np

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from _cocotb_helpers import run_isolated
from test_sobel_multicycle import _feed_image_and_collect, _reference_sobel_l1

DATA_WIDTH = 8
COEFF_WIDTH = 3
ACC_WIDTH = 11
IMG_WIDTH = 4
IMG_HEIGHT = 3


@cocotb.test()
async def test_single_frame_low_contrast(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    # Imagem de baixo contraste/gradiente suave - NAO deve saturar em
    # 255 na maioria das posicoes (diferente das imagens de alto
    # contraste usadas no resto da suite).
    image = np.array([
        [10, 12, 14, 16],
        [11, 13, 15, 17],
        [12, 14, 16, 18],
    ], dtype=int)
    expected = _reference_sobel_l1(image)
    print(f"imagem: {image.tolist()}")
    print(f"esperado: {expected}")

    collected = await _feed_image_and_collect(dut, image, stall_prob=0.0, seed=0)
    print(f"obtido:   {collected}")

    n_saturated = sum(1 for v in expected if v == 255)
    print(f"posicoes saturadas em 255 na referencia: {n_saturated}/{len(expected)}")

    mismatches = [(i, g, e) for i, (g, e) in enumerate(zip(collected, expected)) if g != e]
    if mismatches:
        print(f"MISMATCHES: {mismatches}")
    assert len(collected) == len(expected), (
        f"contagem errada: obtido={len(collected)} esperado={len(expected)}"
    )
    assert collected == expected, f"conteudo errado: obtido={collected} esperado={expected}"
    print("=== RESULTADO: 1 frame isolado, baixo contraste, SEM ERRO ===")


def test_single_frame_low_contrast_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_single_frame_low_contrast")
    run_isolated(
        "test_single_frame_low_contrast",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "line_buffer_2line.sv"),
            os.path.join(proj_root, "rtl", "common", "line_window_skid.sv"),
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
        module="test_single_frame_low_contrast",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH,
                    "IMG_HEIGHT": IMG_HEIGHT, "COEFF_WIDTH": COEFF_WIDTH,
                    "ACC_WIDTH": ACC_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


if __name__ == "__main__":
    test_single_frame_low_contrast_runner()
