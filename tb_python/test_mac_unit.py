"""Testbench cocotb para o modulo rtl/multicycle/mac_unit.sv.

Nota de metodologia (mais uma para a colecao - ver secao 4 de
docs/ARQUITETURA_MULTICICLO.md para as anteriores): o_acc e uma porta
`signed`. `int(dut.o_acc.value)` daria a interpretacao SEM sinal (ex:
-5 apareceria como 2043 numa porta de 11 bits) - o jeito certo de ler
um valor negativo de volta e `dut.o_acc.value.signed_integer`.
"""

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge
from cocotb_test.simulator import run

DATA_WIDTH = 8
COEFF_WIDTH = 3
ACC_WIDTH = 11

# Os mesmos coeficientes nao-nulos de Gx/Gy definidos na especificacao
# da FSM (ver docs/ARQUITETURA_MULTICICLO.md, secao 6.2) - indices e
# valores conferidos manualmente contra o kernel Sobel padrao.
GX_COEFFS = [-1, 1, -2, 2, -1, 1]  # indices 0,2,3,5,6,8 do kernel 3x3
GY_COEFFS = [-1, -2, -1, 1, 2, 1]  # indices 0,1,2,6,7,8 do kernel 3x3


async def _reset(dut):
    dut.rst_n.value = 0
    dut.i_clear.value = 0
    dut.i_mac_en.value = 0
    dut.i_pixel.value = 0
    dut.i_coeff.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def _step(dut, clear: int = 0, mac_en: int = 0, pixel: int = 0, coeff: int = 0):
    dut.i_clear.value = clear
    dut.i_mac_en.value = mac_en
    dut.i_pixel.value = pixel
    dut.i_coeff.value = coeff
    await RisingEdge(dut.clk)
    await ReadOnly()
    acc = dut.o_acc.value.signed_integer
    await NextTimeStep()
    return acc


@cocotb.test()
async def test_reset_state(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    await ReadOnly()
    assert dut.o_acc.value.signed_integer == 0
    await NextTimeStep()


@cocotb.test()
async def test_each_coefficient(dut):
    """Testa cada um dos 4 coeficientes isoladamente (1 MAC, partindo
    de acumulador zerado), comparando contra o resultado aritmetico
    esperado (pixel * coeficiente)."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    cases = [
        (100, 1, 100),
        (100, -1, -100),
        (100, 2, 200),
        (100, -2, -200),
        (0, 2, 0),
        (255, -2, -510),  # maior produto individual possivel em magnitude
    ]
    for pixel, coeff, expected in cases:
        await _reset(dut)
        acc = await _step(dut, clear=0, mac_en=1, pixel=pixel, coeff=coeff)
        assert acc == expected, f"pixel={pixel} coeff={coeff}: esperado={expected} obtido={acc}"


@cocotb.test()
async def test_accumulation_sequence(dut):
    """Varios passos de MAC em sequencia devem somar corretamente -
    nao so 1 passo isolado."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    steps = [(50, 1), (50, 1), (50, -2), (10, 2)]  # 50 +50 -100 +20 = 20
    running = 0
    for pixel, coeff in steps:
        running += pixel * coeff
        acc = await _step(dut, clear=0, mac_en=1, pixel=pixel, coeff=coeff)
        assert acc == running, f"apos passo pixel={pixel} coeff={coeff}: esperado={running} obtido={acc}"


async def _run_kernel_sequence(dut, window_flat, coeffs):
    """window_flat: 6 valores de pixel na MESMA ordem dos indices nao
    nulos do kernel (ver GX_COEFFS/GY_COEFFS). Retorna o acumulador
    final apos o S_LOAD_WIN (clear) + os 6 passos de MAC."""
    await _step(dut, clear=1, mac_en=0)  # equivalente ao estado S_LOAD_WIN da FSM
    acc = None
    for pixel, coeff in zip(window_flat, coeffs):
        acc = await _step(dut, clear=0, mac_en=1, pixel=pixel, coeff=coeff)
    return acc


@cocotb.test()
async def test_full_gx_sequence(dut):
    """Simula a sequencia real que a mac_control_fsm vai fazer para Gx:
    S_LOAD_WIN (clear) seguido de 6 passos de MAC - compara contra o
    produto escalar calculado em Python com os mesmos coeficientes."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    # janela 3x3 sintetica (so os 6 pixels que Gx realmente usa, na
    # ordem dos indices 0,2,3,5,6,8): esquerda/direita de cada linha
    window = [10, 30, 40, 60, 70, 90]
    expected = sum(p * c for p, c in zip(window, GX_COEFFS))
    acc = await _run_kernel_sequence(dut, window, GX_COEFFS)
    assert acc == expected, f"Gx: esperado={expected} obtido={acc}"


@cocotb.test()
async def test_full_gy_sequence(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    window = [10, 20, 30, 70, 80, 90]  # indices 0,1,2,6,7,8
    expected = sum(p * c for p, c in zip(window, GY_COEFFS))
    acc = await _run_kernel_sequence(dut, window, GY_COEFFS)
    assert acc == expected, f"Gy: esperado={expected} obtido={acc}"


@cocotb.test()
async def test_boundary_max_min(dut):
    """Confirma que o pior caso (+-1020, derivado em
    docs/ARQUITETURA_MULTICICLO.md) cabe corretamente nos 11 bits, sem
    saturar/estourar silenciosamente."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    # pior caso positivo de Gx: 0 nos pixels de coeficiente negativo,
    # 255 nos de coeficiente positivo -> (+1+2+1)*255 = 1020
    await _reset(dut)
    window_max = [255 if c > 0 else 0 for c in GX_COEFFS]
    expected_max = sum(p * c for p, c in zip(window_max, GX_COEFFS))
    assert expected_max == 1020, f"sanity check da massa de teste falhou: {expected_max}"
    acc = await _run_kernel_sequence(dut, window_max, GX_COEFFS)
    assert acc == 1020, f"pior caso positivo: esperado=1020 obtido={acc}"

    # pior caso negativo: o oposto
    await _reset(dut)
    window_min = [255 if c < 0 else 0 for c in GX_COEFFS]
    expected_min = sum(p * c for p, c in zip(window_min, GX_COEFFS))
    assert expected_min == -1020, f"sanity check da massa de teste falhou: {expected_min}"
    acc = await _run_kernel_sequence(dut, window_min, GX_COEFFS)
    assert acc == -1020, f"pior caso negativo: esperado=-1020 obtido={acc}"


@cocotb.test()
async def test_mac_en_gating(dut):
    """Com i_mac_en=0, o acumulador deve permanecer parado, mesmo com
    i_pixel/i_coeff variando (a FSM fica parada em outros estados entre
    os passos uteis de MAC)."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    acc = await _step(dut, clear=0, mac_en=1, pixel=100, coeff=1)
    assert acc == 100
    for _ in range(5):
        acc = await _step(dut, clear=0, mac_en=0, pixel=200, coeff=-2)  # deveria ser ignorado
        assert acc == 100, f"acumulador mudou com mac_en=0: {acc}"


@cocotb.test()
async def test_clear_priority_over_mac_en(dut):
    """Se clear e mac_en vierem juntos no mesmo ciclo (nao deveria
    acontecer no uso normal da FSM), clear tem prioridade - o produto
    daquele ciclo e descartado, nao usado como novo valor inicial."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    await _step(dut, clear=0, mac_en=1, pixel=100, coeff=1)  # acc=100
    acc = await _step(dut, clear=1, mac_en=1, pixel=50, coeff=2)  # clear+mac_en juntos
    assert acc == 0, f"clear deveria vencer mac_en: obtido={acc} (esperava 0, nao {50*2})"


@cocotb.test()
async def test_unexpected_coefficient_handled_safely(dut):
    """CAMINHO ERRADO: a mac_control_fsm promete nunca enviar i_coeff
    fora de {-2,-1,1,2} (o zero e filtrado antes de chegar aqui - ver
    docs/ARQUITETURA_MULTICICLO.md secao 6.2), mas o RTL tem um
    'default' no case do coeficiente pensado para cobrir esse caso com
    seguranca (produto=0, sem propagar X), caso essa promessa seja
    violada por engano em algum lugar futuro do projeto. Este teste
    confirma que esse 'default' realmente funciona como documentado -
    sem ele, a asssercao ficaria sem prova, so um comentario no RTL."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    for bad_coeff in [0, 3, -3, -4]:  # fora do conjunto valido {-2,-1,1,2}
        acc = await _step(dut, clear=1, mac_en=0, pixel=0, coeff=0)  # zera antes de cada caso
        acc = await _step(dut, clear=0, mac_en=1, pixel=100, coeff=bad_coeff)
        assert acc == 0, (
            f"i_coeff={bad_coeff} (fora do conjunto valido) deveria dar produto=0 "
            f"(via 'default'), obtido={acc}"
        )


def test_mac_unit_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_mac_unit")

    run(
        verilog_sources=[
            os.path.join(proj_root, "rtl", "multicycle", "mac_unit.sv"),
        ],
        includes=[os.path.join(proj_root, "include")],
        toplevel="mac_unit",
        module="test_mac_unit",
        parameters={
            "DATA_WIDTH": DATA_WIDTH,
            "COEFF_WIDTH": COEFF_WIDTH,
            "ACC_WIDTH": ACC_WIDTH,
        },
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


if __name__ == "__main__":
    test_mac_unit_runner()
