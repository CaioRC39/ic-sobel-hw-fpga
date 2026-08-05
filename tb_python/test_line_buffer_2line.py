"""Testbench cocotb para o modulo rtl/common/line_buffer_2line.sv.

Modelo de referencia: como o modulo apenas atrasa o stream de entrada em
IMG_WIDTH e 2*IMG_WIDTH pulsos de i_valid (com zero-padding enquanto nao
"aquecido"), o valor esperado em cada instante pode ser calculado
diretamente em Python guardando o historico de pixels validos recebidos.

Nota de metodologia: usamos o padrao RisingEdge -> ReadOnly() ->
(captura) -> NextTimeStep() para amostrar as saidas. Isso evita uma
condicao de corrida de LEITURA especifica desta combinacao
Icarus+cocotb, na qual ler um sinal imediatamente apos RisingEdge pode
retornar o valor de ANTES do assentamento completo daquele ciclo -
confirmado isolando o efeito com um contador minimo e um dump de VCD
(o VCD, gerado pelo proprio simulador, mostra o valor correto no
timestamp certo; so a leitura "ao vivo" via cocotb ficava um ciclo
atrasada sem o ReadOnly). Nao e um bug do RTL.
"""

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
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def _step(dut, valid: int, pixel: int, rst_n: int = 1):
    """Aplica i_valid/i_pixel (e opcionalmente rst_n), avanca 1 ciclo e
    retorna as saidas assentadas (ver nota de metodologia no cabecalho
    do arquivo)."""
    dut.rst_n.value = rst_n
    dut.i_valid.value = valid
    dut.i_pixel.value = pixel
    await RisingEdge(dut.clk)
    await ReadOnly()
    out = {
        "valid": int(dut.o_valid.value),
        "curr": int(dut.o_curr.value),
        "line1": int(dut.o_line1.value),
        "line2": int(dut.o_line2.value),
    }
    await NextTimeStep()
    return out


@cocotb.test()
async def test_reset_state(dut):
    """Apos reset, as saidas devem estar zeradas."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    await ReadOnly()
    assert dut.o_curr.value == 0
    assert dut.o_line1.value == 0
    assert dut.o_line2.value == 0
    await NextTimeStep()


@cocotb.test()
async def test_delay_and_zero_padding(dut):
    """Stream continuo (sem gaps): valida o atraso de W e 2W ciclos e o
    zero-padding do topo da imagem, comparando contra um modelo de
    referencia em Python a cada ciclo."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    n_cycles = 5 * IMG_WIDTH  # o suficiente para "aquecer" os 2 estagios
    pixels = [(i * 7 + 3) % 256 for i in range(n_cycles)]

    history = []  # pixels validos ja recebidos, na ordem
    for t, pix in enumerate(pixels):
        out = await _step(dut, valid=1, pixel=pix)
        history.append(pix)

        exp_curr = pix
        exp_line1 = history[t - IMG_WIDTH] if t >= IMG_WIDTH else 0
        exp_line2 = history[t - 2 * IMG_WIDTH] if t >= 2 * IMG_WIDTH else 0

        assert out["valid"] == 1
        assert out["curr"] == exp_curr, f"t={t}: o_curr esperado={exp_curr} obtido={out['curr']}"
        assert out["line1"] == exp_line1, (
            f"t={t}: o_line1 esperado={exp_line1} obtido={out['line1']}"
        )
        assert out["line2"] == exp_line2, (
            f"t={t}: o_line2 esperado={exp_line2} obtido={out['line2']}"
        )


@cocotb.test()
async def test_ignores_invalid_cycles(dut):
    """Ciclos com i_valid=0 nao devem avancar o ponteiro da FIFO nem
    contaminar o historico - o modulo deve ficar 'congelado' nesses
    ciclos."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    random.seed(1234)

    n_real_pixels = 4 * IMG_WIDTH
    history = []
    real_t = 0
    for _ in range(n_real_pixels):
        # Insere de 0 a 2 ciclos invalidos antes de cada pixel real
        for _ in range(random.randint(0, 2)):
            out = await _step(dut, valid=0, pixel=0xFF)  # 0xFF = "lixo"
            assert out["valid"] == 0

        pix = (real_t * 13 + 5) % 256
        out = await _step(dut, valid=1, pixel=pix)

        history.append(pix)
        exp_line1 = history[real_t - IMG_WIDTH] if real_t >= IMG_WIDTH else 0
        exp_line2 = history[real_t - 2 * IMG_WIDTH] if real_t >= 2 * IMG_WIDTH else 0

        assert out["valid"] == 1
        assert out["curr"] == pix
        assert out["line1"] == exp_line1, f"real_t={real_t}"
        assert out["line2"] == exp_line2, f"real_t={real_t}"
        real_t += 1


@cocotb.test()
async def test_midstream_reset(dut):
    """Reset disparado no MEIO da operacao (com dado 'em transito' nos
    2 estagios) deve levar a um estado limpo, sem residuo do que rodou
    antes - o comportamento pos-reset deve ser identico a um reset
    inicial normal."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    # "suja" o estado: alimenta pixels normalmente por menos de 1 volta
    # completa do ponteiro circular
    for t in range(10):
        await _step(dut, valid=1, pixel=50 + t)

    # RESET NO MEIO - com dado real ainda "em transito" nos 2 estagios
    for _ in range(3):
        out = await _step(dut, valid=0, pixel=0, rst_n=0)
        assert out["curr"] == 0, "durante reset, o_curr deveria ser 0 (i_pixel=0 imposto)"
        assert out["line1"] == 0, f"durante reset, o_line1 deveria ser 0, obtido {out['line1']}"
        assert out["line2"] == 0, f"durante reset, o_line2 deveria ser 0, obtido {out['line2']}"

    # sai do reset e roda como se fosse a primeira vez - nao deve haver
    # NENHUM residuo do que rodou antes do reset (ponteiro, contador de
    # aquecimento, memoria "contaminada")
    history = []
    for t in range(4 * IMG_WIDTH):
        out = await _step(dut, valid=1, pixel=200 + t, rst_n=1)
        history.append(200 + t)
        exp_line1 = history[t - IMG_WIDTH] if t >= IMG_WIDTH else 0
        exp_line2 = history[t - 2 * IMG_WIDTH] if t >= 2 * IMG_WIDTH else 0
        assert out["curr"] == 200 + t
        assert out["line1"] == exp_line1, f"pos-reset t={t}: possivel residuo em line1"
        assert out["line2"] == exp_line2, f"pos-reset t={t}: possivel residuo em line2"


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
