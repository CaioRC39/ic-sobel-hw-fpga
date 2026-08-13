"""Testbench cocotb para o modulo rtl/multicycle/sobel_multicycle.sv.

Modelo de referencia: convolucao Sobel L1 com zero-padding manual (1
pixel de borda em todos os 4 lados) via numpy - mesma convencao de
borda ja usada em window_3x3 (esquerda/direita/superior) e fechada
neste modulo para a borda inferior (ver RESUMO_ESTADO_PROJETO.md,
"Design fechado para sobel_multicycle.sv", item 4).

IMG_WIDTH/IMG_HEIGHT pequenos de proposito (4x3): a arquitetura
multiciclo gasta ~15 ciclos uteis por pixel (ver
docs/ARQUITETURA_MULTICICLO.md, secao 5.2) - uma imagem 640x480 real
seria inviavel de simular aqui.
"""

import os

import numpy as np

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge
from cocotb_test.simulator import run

DATA_WIDTH = 8
COEFF_WIDTH = 3
ACC_WIDTH = 11
IMG_WIDTH = 4
IMG_HEIGHT = 3

GX_KERNEL = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]])
GY_KERNEL = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]])


def _reference_sobel_l1(image: np.ndarray):
    """Zero-padding de 1 pixel nos 4 lados (padrao ja usado pelos
    modulos comuns + a extensao de borda inferior fechada neste
    modulo), convolucao valida 3x3 em cada pixel real, magnitude L1
    saturada em 255. Retorna a lista de pixels esperados em ordem
    raster-scan (mesma ordem em que o DUT deve produzir o_pixel)."""
    padded = np.pad(image, 1, mode="constant", constant_values=0).astype(int)
    h, w = image.shape
    out = []
    for r in range(h):
        for c in range(w):
            win = padded[r:r + 3, c:c + 3]
            gx = int(np.sum(win * GX_KERNEL))
            gy = int(np.sum(win * GY_KERNEL))
            out.append(min(abs(gx) + abs(gy), 255))
    return out


async def _reset(dut):
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def _feed_image_and_collect(dut, image: np.ndarray, stall_prob: float = 0.0, seed: int = 0):
    """Alimenta a imagem inteira respeitando o_ready (nunca calcula
    backpressure manualmente - mesmo espirito de
    test_ready_gating_prevents_manual_gap_calculation em
    test_window_3x3.py), opcionalmente inserindo bolhas aleatorias
    (i_valid=0 mesmo com o_ready=1) para exercitar tolerancia a
    stalls externos. Retorna a lista de pixels de saida coletados."""
    import random

    rnd = random.Random(seed)
    h, w = image.shape
    flat = image.flatten().tolist()
    idx = 0
    collected = []

    max_cycles = 50 * len(flat) + 2000  # margem generosa (15 ciclos/pixel + drenagem)
    cycles = 0
    while True:
        await ReadOnly()
        ready = int(dut.o_ready.value)
        out_valid = int(dut.o_valid.value)
        pixel = int(dut.o_pixel.value) if out_valid else None
        await NextTimeStep()

        present_now = ready and idx < len(flat) and rnd.random() >= stall_prob
        dut.i_valid.value = 1 if present_now else 0
        dut.i_pixel.value = flat[idx] if present_now else 0

        if out_valid:
            collected.append(pixel)
        if present_now:
            idx += 1

        await RisingEdge(dut.clk)
        cycles += 1
        if cycles > max_cycles:
            raise TimeoutError("simulacao excedeu o numero maximo de ciclos esperado")
        if idx >= len(flat) and len(collected) >= h * w:
            break

    dut.i_valid.value = 0
    return collected


@cocotb.test()
async def test_reset_state(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    await ReadOnly()
    assert dut.o_ready.value == 1, "apos reset, o_ready deveria ser 1 (pronto pro 1o pixel)"
    assert dut.o_valid.value == 0
    await NextTimeStep()


@cocotb.test()
async def test_small_image_golden(dut):
    """Imagem pequena, sem stalls externos - compara pixel a pixel
    contra a referencia numpy (zero-padding nos 4 lados)."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    image = (np.arange(1, IMG_HEIGHT * IMG_WIDTH + 1) * 17 % 256).reshape(IMG_HEIGHT, IMG_WIDTH)
    expected = _reference_sobel_l1(image)

    collected = await _feed_image_and_collect(dut, image, stall_prob=0.0)

    assert len(collected) == len(expected), (
        f"pixels coletados ({len(collected)}) != esperado ({len(expected)})"
    )
    for idx, (got, exp) in enumerate(zip(collected, expected)):
        r, c = divmod(idx, IMG_WIDTH)
        assert got == exp, f"pixel (linha={r}, col={c}): esperado={exp} obtido={got}"


@cocotb.test()
async def test_small_image_with_external_stalls(dut):
    """Mesma imagem, mas com bolhas aleatorias de i_valid=0 mesmo com
    o_ready=1 (fonte externa intermitente) - o resultado deve ser
    IDENTICO ao caso sem stall, apenas levando mais ciclos."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    image = (np.arange(1, IMG_HEIGHT * IMG_WIDTH + 1) * 17 % 256).reshape(IMG_HEIGHT, IMG_WIDTH)
    expected = _reference_sobel_l1(image)

    collected = await _feed_image_and_collect(dut, image, stall_prob=0.3, seed=42)

    assert len(collected) == len(expected)
    for idx, (got, exp) in enumerate(zip(collected, expected)):
        assert got == exp, f"idx={idx} (com stalls externos): esperado={exp} obtido={got}"


@cocotb.test()
async def test_two_consecutive_frames(dut):
    """2 frames seguidos, back-to-back (sem gap manual entre eles -
    so respeita o_ready, que deve voltar sozinho a 1 apos o frame
    anterior drenar, Ponto 5 do design fechado). Confirma que o
    contador feed_cnt_r realmente faz wrap e realinha corretamente
    para o 2o frame."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    image1 = (np.arange(1, IMG_HEIGHT * IMG_WIDTH + 1) * 17 % 256).reshape(IMG_HEIGHT, IMG_WIDTH)
    image2 = (np.arange(50, 50 + IMG_HEIGHT * IMG_WIDTH) * 23 % 256).reshape(IMG_HEIGHT, IMG_WIDTH)

    collected1 = await _feed_image_and_collect(dut, image1, stall_prob=0.0, seed=1)
    collected2 = await _feed_image_and_collect(dut, image2, stall_prob=0.0, seed=2)

    expected1 = _reference_sobel_l1(image1)
    expected2 = _reference_sobel_l1(image2)

    assert collected1 == expected1, "frame 1 divergiu da referencia"
    assert collected2 == expected2, "frame 2 (apos wrap do feed_cnt_r) divergiu da referencia"


def test_sobel_multicycle_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_sobel_multicycle")

    run(
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "line_buffer_2line.sv"),
            os.path.join(proj_root, "rtl", "common", "window_3x3.sv"),
            os.path.join(proj_root, "rtl", "common", "abs_saturate.sv"),
            os.path.join(proj_root, "rtl", "common", "magnitude_l1.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "mac_unit.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "kernel_rom.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "mac_control_fsm.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "sobel_multicycle.sv"),
        ],
        includes=[os.path.join(proj_root, "include")],
        toplevel="sobel_multicycle",
        module="test_sobel_multicycle",
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
    test_sobel_multicycle_runner()
