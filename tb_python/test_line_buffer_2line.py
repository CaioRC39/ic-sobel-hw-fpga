import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge
from cocotb_test.simulator import run

DATA_WIDTH = 8
IMG_WIDTH = 6


async def _reset(dut):
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    dut.i_tag.value = 0
    dut.i_rearm.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def _step(dut, valid: int, pixel: int, tag: int = 0, rst_n: int = 1, rearm: int = 0):
    dut.rst_n.value = rst_n
    dut.i_valid.value = valid
    dut.i_pixel.value = pixel
    dut.i_tag.value = tag
    dut.i_rearm.value = rearm
    await RisingEdge(dut.clk)
    await ReadOnly()
    out = {
        "valid": int(dut.o_valid.value),
        "curr": int(dut.o_curr.value),
        "line1": int(dut.o_line1.value),
        "line2": int(dut.o_line2.value),
        "curr_tag": int(dut.o_curr_tag.value),
        "line1_tag": int(dut.o_line1_tag.value),
        "line2_tag": int(dut.o_line2_tag.value),
    }
    await NextTimeStep()
    return out


@cocotb.test()
async def test_reset_state(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    await ReadOnly()
    assert dut.o_curr.value == 0
    assert dut.o_line1.value == 0
    assert dut.o_line2.value == 0
    assert dut.o_curr_tag.value == 0
    assert dut.o_line1_tag.value == 0
    assert dut.o_line2_tag.value == 0
    await NextTimeStep()


@cocotb.test()
async def test_delay_and_zero_padding(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    n_cycles = 5 * IMG_WIDTH
    pixels = [(i * 7 + 3) % 256 for i in range(n_cycles)]

    history = []
    for t, pix in enumerate(pixels):
        out = await _step(dut, valid=1, pixel=pix, tag=0)
        history.append(pix)

        exp_curr = pix
        exp_line1 = history[t - IMG_WIDTH] if t >= IMG_WIDTH else 0
        exp_line2 = history[t - 2 * IMG_WIDTH] if t >= 2 * IMG_WIDTH else 0

        assert out["valid"] == 1
        assert out["curr"] == exp_curr
        assert out["line1"] == exp_line1
        assert out["line2"] == exp_line2


@cocotb.test()
async def test_ignores_invalid_cycles(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    random.seed(1234)

    n_real_pixels = 4 * IMG_WIDTH
    history = []
    real_t = 0
    for _ in range(n_real_pixels):
        for _ in range(random.randint(0, 2)):
            out = await _step(dut, valid=0, pixel=0xFF, tag=1)
            assert out["valid"] == 0

        pix = (real_t * 13 + 5) % 256
        out = await _step(dut, valid=1, pixel=pix, tag=0)

        history.append(pix)
        exp_line1 = history[real_t - IMG_WIDTH] if real_t >= IMG_WIDTH else 0
        exp_line2 = history[real_t - 2 * IMG_WIDTH] if real_t >= 2 * IMG_WIDTH else 0

        assert out["valid"] == 1
        assert out["curr"] == pix
        assert out["line1"] == exp_line1
        assert out["line2"] == exp_line2
        real_t += 1


@cocotb.test()
async def test_midstream_reset(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    for t in range(10):
        await _step(dut, valid=1, pixel=50 + t, tag=0)

    for _ in range(3):
        out = await _step(dut, valid=0, pixel=0, tag=0, rst_n=0)
        assert out["curr"] == 0
        assert out["line1"] == 0
        assert out["line2"] == 0
        assert out["curr_tag"] == 0
        assert out["line1_tag"] == 0
        assert out["line2_tag"] == 0

    history = []
    for t in range(4 * IMG_WIDTH):
        out = await _step(dut, valid=1, pixel=200 + t, tag=0, rst_n=1)
        history.append(200 + t)
        exp_line1 = history[t - IMG_WIDTH] if t >= IMG_WIDTH else 0
        exp_line2 = history[t - 2 * IMG_WIDTH] if t >= 2 * IMG_WIDTH else 0
        assert out["curr"] == 200 + t
        assert out["line1"] == exp_line1
        assert out["line2"] == exp_line2


@cocotb.test()
async def test_tag_constant_within_frame_always_matches(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    n_cycles = 6 * IMG_WIDTH
    for t in range(n_cycles):
        out = await _step(dut, valid=1, pixel=(t * 11 + 1) % 256, tag=1)
        assert out["curr_tag"] == 1, f"t={t}"
        assert out["line1_tag"] == 1, f"t={t}"
        assert out["line2_tag"] == 1, f"t={t}"


@cocotb.test()
async def test_tag_lockstep_across_3_frame_boundaries(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    frame_len = 3 * IMG_WIDTH
    frame_tags = [0, 1, 0]
    hist_pix, hist_tag = [], []
    gt = 0

    for tag in frame_tags:
        for _ in range(frame_len):
            pix = (gt * 7 + 3) % 256
            out = await _step(dut, valid=1, pixel=pix, tag=tag)
            hist_pix.append(pix)
            hist_tag.append(tag)

            assert out["curr_tag"] == tag, f"gt={gt}"
            if gt >= IMG_WIDTH:
                assert out["line1_tag"] == hist_tag[gt - IMG_WIDTH], f"gt={gt}"
            if gt >= 2 * IMG_WIDTH:
                assert out["line2_tag"] == hist_tag[gt - 2 * IMG_WIDTH], f"gt={gt}"
            gt += 1


@cocotb.test()
async def test_tag_survives_frame_boundary_in_memory(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    frame1_len = 3 * IMG_WIDTH
    frame2_len = 3 * IMG_WIDTH
    hist_pix, hist_tag = [], []

    for t in range(frame1_len):
        pix = (t * 3 + 1) % 256
        out = await _step(dut, valid=1, pixel=pix, tag=0)
        hist_pix.append(pix)
        hist_tag.append(0)
        assert out["curr_tag"] == 0

    for t in range(frame2_len):
        gt = frame1_len + t
        pix = (t * 5 + 2) % 256
        out = await _step(dut, valid=1, pixel=pix, tag=1)
        hist_pix.append(pix)
        hist_tag.append(1)

        exp_line1_tag = hist_tag[gt - IMG_WIDTH]
        exp_line2_tag = hist_tag[gt - 2 * IMG_WIDTH]

        assert out["curr_tag"] == 1
        assert out["line1_tag"] == exp_line1_tag, f"t(global)={gt}"
        assert out["line2_tag"] == exp_line2_tag, f"t(global)={gt}"


@cocotb.test()
async def test_rearm_prevents_residual_tag_leak(dut):
    """Contraste direto com test_tag_survives_frame_boundary_in_memory
    (que demonstra o vazamento SEM i_rearm): aqui, i_rearm e pulsado no
    1o ciclo de cada frame (mesmo padrao que sobel_multicycle.sv vai
    usar) - o_line1_tag/o_line2_tag NUNCA devem mostrar a tag do frame
    ANTERIOR apos a fronteira; durante os IMG_WIDTH+1/IMG_WIDTH
    primeiros ciclos do novo frame, devem refletir a tag ATUAL (zero-
    padding herdando i_tag, mesmo raciocinio da borda superior do
    frame 1) - nunca o residuo real do frame antigo ainda fisicamente
    presente na memoria circular."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    frame1_len = 3 * IMG_WIDTH
    frame2_len = 3 * IMG_WIDTH

    for t in range(frame1_len):
        pix = (t * 3 + 1) % 256
        await _step(dut, valid=1, pixel=pix, tag=0, rearm=(t == 0))

    for t in range(frame2_len):
        pix = (t * 5 + 2) % 256
        out = await _step(dut, valid=1, pixel=pix, tag=1, rearm=(t == 0))

        assert out["curr_tag"] == 1, f"t(frame2)={t}"
        assert out["line1_tag"] == 1, (
            f"t(frame2)={t}: com i_rearm, line1_tag NUNCA deveria mostrar "
            f"a tag do frame anterior (0) - obtido={out['line1_tag']}"
        )
        assert out["line2_tag"] == 1, (
            f"t(frame2)={t}: com i_rearm, line2_tag NUNCA deveria mostrar "
            f"a tag do frame anterior (0) - obtido={out['line2_tag']}"
        )


def test_line_buffer_2line_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_line_buffer_2line")

    run(
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "line_buffer_2line.sv"),
        ],
        includes=[os.path.join(proj_root, "include")],
        toplevel="line_buffer_2line",
        module="test_line_buffer_2line",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


if __name__ == "__main__":
    test_line_buffer_2line_runner()
