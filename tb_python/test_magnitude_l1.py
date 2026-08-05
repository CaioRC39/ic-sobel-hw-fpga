"""Testbench cocotb para o modulo rtl/common/magnitude_l1.sv.

Modulo puramente combinacional (sem clk) - mesmo padrao de
tb_python/test_abs_saturate.py (Timer em vez de RisingEdge/ReadOnly).
"""

import os

import cocotb
from cocotb.triggers import Timer
from cocotb_test.simulator import run

DATA_WIDTH = 8


def _reference(gx: int, gy: int, width: int) -> int:
    return min(gx + gy, (1 << width) - 1)


async def _check(dut, gx: int, gy: int):
    dut.i_abs_gx.value = gx
    dut.i_abs_gy.value = gy
    await Timer(1, unit="ns")
    got = int(dut.o_magnitude.value)
    exp = _reference(gx, gy, DATA_WIDTH)
    assert got == exp, f"gx={gx} gy={gy}: esperado={exp} obtido={got}"


@cocotb.test()
async def test_no_saturation(dut):
    for gx, gy in [(0, 0), (10, 20), (100, 100), (127, 128), (0, 255), (255, 0)]:
        await _check(dut, gx, gy)


@cocotb.test()
async def test_saturation(dut):
    for gx, gy in [(200, 200), (255, 255), (150, 106), (255, 1)]:
        await _check(dut, gx, gy)
        assert int(dut.o_magnitude.value) == 255


@cocotb.test()
async def test_boundary_exact_255_256(dut):
    await _check(dut, 200, 55)  # soma = 255, exatamente no limite - NAO deveria saturar
    assert int(dut.o_magnitude.value) == 255
    await _check(dut, 200, 56)  # soma = 256, passou do limite - deveria saturar (mas ainda da 255)
    assert int(dut.o_magnitude.value) == 255
    await _check(dut, 199, 55)  # soma = 254, abaixo do limite
    assert int(dut.o_magnitude.value) == 254


@cocotb.test()
async def test_exhaustive_small_range(dut):
    """Varre TODAS as combinacoes de gx/gy de 0 a 63 (4096 casos) -
    exaustivo o suficiente para pegar qualquer erro de largura de bit
    sem varrer o espaco completo de 8 bits (256*256=65536, desnecessario
    para um somador simples)."""
    for gx in range(0, 64):
        for gy in range(0, 64):
            await _check(dut, gx, gy)


def test_magnitude_l1_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_magnitude_l1")

    run(
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "magnitude_l1.sv"),
        ],
        includes=[os.path.join(proj_root, "include")],
        toplevel="magnitude_l1",
        module="test_magnitude_l1",
        parameters={"DATA_WIDTH": DATA_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


if __name__ == "__main__":
    test_magnitude_l1_runner()
