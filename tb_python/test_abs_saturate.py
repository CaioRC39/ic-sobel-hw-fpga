"""Testbench cocotb para o modulo rtl/common/abs_saturate.sv.

Modulo puramente combinacional (sem clk) - as verificacoes usam
`await Timer(1, unit="ns")` para deixar a logica combinacional
assentar apos mudar as entradas, em vez de RisingEdge/ReadOnly (que so
fazem sentido para logica sincrona).
"""

import os

import cocotb
from cocotb.triggers import Timer

from _cocotb_helpers import run_isolated

IN_WIDTH = 11
OUT_WIDTH = 8


def _reference(value: int, in_width: int, out_width: int) -> int:
    abs_val = abs(value)
    max_out = (1 << out_width) - 1
    return min(abs_val, max_out)


async def _check(dut, value: int):
    dut.i_value.value = value
    await Timer(1, unit="ns")
    got = int(dut.o_value.value)
    exp = _reference(value, IN_WIDTH, OUT_WIDTH)
    assert got == exp, f"i_value={value}: esperado={exp} obtido={got}"


@cocotb.test()
async def test_positive_no_saturation(dut):
    for value in [0, 1, 50, 127, 200]:
        await _check(dut, value)


@cocotb.test()
async def test_negative_no_saturation(dut):
    for value in [-1, -50, -127, -200]:
        await _check(dut, value)


@cocotb.test()
async def test_positive_saturation(dut):
    for value in [256, 300, 500, 1020]:
        await _check(dut, value)
        assert int(dut.o_value.value) == 255


@cocotb.test()
async def test_negative_saturation(dut):
    for value in [-256, -300, -500, -1020]:
        await _check(dut, value)
        assert int(dut.o_value.value) == 255


@cocotb.test()
async def test_boundary_exact_255_256(dut):
    """O limite exato de saturacao: 255 nao deveria saturar, 256 ja
    deveria."""
    await _check(dut, 255)
    assert int(dut.o_value.value) == 255
    await _check(dut, -255)
    assert int(dut.o_value.value) == 255
    await _check(dut, 256)
    assert int(dut.o_value.value) == 255  # satura, mas o valor real (256) ja passou do limite
    await _check(dut, -256)
    assert int(dut.o_value.value) == 255


@cocotb.test()
async def test_project_actual_range(dut):
    """Varre TODO o intervalo real que o mac_unit pode produzir
    (+-1020, ver docs/ARQUITETURA_MULTICICLO.md secao 5.1) - nao so
    alguns pontos isolados."""
    for value in range(-1020, 1021):
        await _check(dut, value)


def test_abs_saturate_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_abs_saturate")

    # Nota: o parametro testcase= do cocotb-test 0.2.6 NAO restringe a
    # execucao com cocotb 2.0.1 (ele define a env var antiga "TESTCASE",
    # mas o cocotb 2.0 espera "COCOTB_TESTCASE", com prefixo - ver nota
    # metodologica em docs/ARQUITETURA_MULTICICLO.md).
    run_isolated(
        "test_positive_no_saturation,test_negative_no_saturation,"
        "test_positive_saturation,test_negative_saturation,"
        "test_boundary_exact_255_256,test_project_actual_range",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "abs_saturate.sv"),
        ],
        includes=[os.path.join(proj_root, "include")],
        toplevel="abs_saturate",
        module="test_abs_saturate",
        parameters={"IN_WIDTH": IN_WIDTH, "OUT_WIDTH": OUT_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


@cocotb.test()
async def test_two_complement_extreme_edge_case(dut):
    """Caso extremo de complemento de 2: o valor mais negativo
    representavel (-8 em 4 bits) nao tem um positivo correspondente na
    MESMA largura (o maximo seria +7). Este teste usa IN_WIDTH=4 (via
    executor dedicado abaixo) especificamente para alcancar esse valor
    - o intervalo real do projeto (+-1020 em 11 bits) nunca chega
    nesse extremo, entao precisa de um teste em separado para validar
    a margem de 1 bit extra (ver comentario no cabecalho do RTL)."""
    dut.i_value.value = -8  # o minimo representavel em 4 bits com sinal
    await Timer(1, unit="ns")
    got = int(dut.o_value.value)
    assert got == 8, f"|-8| deveria ser 8, obtido {got} (a margem de 1 bit falhou?)"

    dut.i_value.value = -7
    await Timer(1, unit="ns")
    assert int(dut.o_value.value) == 7


def test_abs_saturate_two_complement_edge_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_abs_saturate_edge")

    run_isolated(
        "test_two_complement_extreme_edge_case",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "abs_saturate.sv"),
        ],
        includes=[os.path.join(proj_root, "include")],
        toplevel="abs_saturate",
        module="test_abs_saturate",
        parameters={"IN_WIDTH": 4, "OUT_WIDTH": 8},  # OUT_WIDTH=8 folgado, nao interfere no teste
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


if __name__ == "__main__":
    test_abs_saturate_runner()
    test_abs_saturate_two_complement_edge_runner()
