"""Teste de regressao do CONTRATO A da interface de entrada de sobel_multicycle:
a transferencia ocorre quando i_valid && o_ready no MESMO ciclo; o produtor pode levantar
i_valid e MANTER i_valid/i_pixel estaveis ate ver o_ready=1.

Verifica: saida identica ao golden, o_status == 000 (OR acumulado dentro do laco), 0 $error
(guarda P15 de run_isolated), e que a condicao valid&&!ready FOI exercitada em cada lote
(blocked > 0) - "sem falha" so vale com esse numero positivo.

LIMITE DECLARADO (nao e testado aqui, e medido em diagnosticos/probe_r1_handshake.py, modo fire):
um produtor que pulsa i_valid por 1 ciclo IGNORANDO o_ready perde o pixel em silencio
(o_status=000). O modulo nao consegue distinguir isso de um produtor que espera.

METODO (licao de fase): NENHUM await entre lotes e nenhuma leitura apos NextTimeStep. Um
ReadOnly+NextTimeStep extra entre lotes desloca o driver em meio ciclo e o faz escrever i_valid
no instante da borda, perdendo o 1o pixel quando o 1o sorteio do lote apresenta pixel logo.
Os pares incluem seed 42 (1o sorteio 0.639 >= stall 0.3) de proposito.
"""
import os
import random

import numpy as np
import pytest

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge

from _cocotb_helpers import run_isolated
from test_sobel_multicycle import _reference_sobel_l1

DATA_WIDTH, COEFF_WIDTH, ACC_WIDTH, N_FRAMES = 8, 3, 11, 4
PAIRS = [(0.0, 0), (0.3, 1), (0.3, 42)]


def _images(w, h):
    # baixo contraste real: pixels em [0,12] => |Gx|+|Gy| <= 96 < 255 (sem saturacao)
    return [((np.arange(h * w) * (3 + f) + f * 7) % 13).reshape(h, w) for f in range(N_FRAMES)]


async def _drive_hold(dut, flat, n_expected, stall, seed):
    """valid levantado e mantido (dado estavel) ate valid&&ready decidido no mesmo ponto de
    amostragem. o_ready nao depende de i_valid; ambos refletem o estado do ciclo corrente."""
    rnd = random.Random(seed)
    idx, pend, cyc = 0, False, 0
    collected = []
    st = {"transfers": 0, "blocked": 0, "status": 0}
    max_cycles = 60 * len(flat) + 4000
    while True:
        await ReadOnly()
        ready = int(dut.o_ready.value)
        st["status"] |= int(dut.o_status.value)
        if int(dut.o_valid.value):
            collected.append(int(dut.o_pixel.value))
        await NextTimeStep()

        valid, data = 0, 0
        if not pend and idx < len(flat) and rnd.random() >= stall:
            pend = True
        if pend:
            valid, data = 1, flat[idx]
            if ready:
                st["transfers"] += 1
                pend = False
                idx += 1
            else:
                st["blocked"] += 1          # valid=1 com o_ready=0, dado mantido

        dut.i_valid.value = valid
        dut.i_pixel.value = data
        await RisingEdge(dut.clk)
        cyc += 1
        assert cyc <= max_cycles, "timeout: saidas nao completaram"
        if idx >= len(flat) and not pend and len(collected) >= n_expected:
            break
    dut.i_valid.value = 0
    return collected, st


@cocotb.test()
async def hold_probe(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    w = int(os.environ["TEST_IMG_WIDTH"])
    h = int(os.environ["TEST_IMG_HEIGHT"])

    for batch, (stall, seed) in enumerate(PAIRS):       # sem await entre lotes
        images = _images(w, h)
        expected = [p for im in images for p in _reference_sobel_l1(im)]
        assert sum(1 for v in expected if v == 255) == 0, "massa saturou: teste invalido"
        flat = np.vstack(images).flatten().tolist()

        collected, st = await _drive_hold(dut, flat, len(expected), stall, seed)
        tag = f"W={w} H={h} lote={batch} stall={stall} seed={seed}"
        print(f"=== HOLD {tag}: transfers={st['transfers']}/{len(flat)} "
              f"blocked(valid&&!ready)={st['blocked']} len(outs)={len(collected)}/{len(expected)} "
              f"o_status={st['status']:03b} ===")
        assert st["transfers"] == len(flat), f"{tag}: nem todos os pixels foram aceitos"
        assert st["blocked"] > 0, f"{tag}: VAZIO - valid&&!ready nunca ocorreu"
        assert collected == expected, f"{tag}: saida diverge do golden"
        assert st["status"] == 0, f"{tag}: o_status={st['status']:03b} (esperado 000)"


def _runner(w, h):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    run_isolated(
        "hold_probe",
        verilog_sources=[os.path.join(root, "rtl", d, f) for d, f in [
            ("common", "line_buffer_2line.sv"), ("common", "window_3x3.sv"),
            ("common", "line_window_skid.sv"), ("common", "abs_saturate.sv"),
            ("common", "magnitude_l1.sv"), ("multicycle", "mac_unit.sv"),
            ("multicycle", "kernel_rom.sv"), ("multicycle", "mac_control_fsm.sv"),
            ("multicycle", "skid_fifo2.sv"), ("multicycle", "sobel_multicycle.sv")]],
        includes=[os.path.join(root, "include")],
        toplevel="sobel_multicycle",
        module="test_valid_hold_handshake",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": w, "IMG_HEIGHT": h,
                    "COEFF_WIDTH": COEFF_WIDTH, "ACC_WIDTH": ACC_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=os.path.join(root, "sim", f"sim_build_valid_hold_w{w}_h{h}"),
        extra_env={"TEST_IMG_WIDTH": str(w), "TEST_IMG_HEIGHT": str(h)},
    )


@pytest.mark.parametrize("w,h", [(4, 3), (6, 2)], ids=lambda v: str(v))
def test_valid_hold_handshake(w, h):
    _runner(w, h)