"""Testbench cocotb para rtl/common/line_window_skid.sv.

Ate agora este modulo so era exercitado indiretamente via sobel_multicycle
(ponta solta registrada na Fase 2: CLAUDE.md 15.2/15.3 exigem teste dedicado
para todo modulo com contrato violavel).

Padrao de leitura IDENTICO a test_skid_fifo2.py: estimulo -> Timer(1ns) ->
leitura COMBINACIONAL (antes da borda que fecha o ciclo) -> RisingEdge ->
NextTimeStep. Motivo: o_valid/o_data dependem de count_r/rd_ptr_r, que a
PROPRIA borda observada atualiza, e o_room/o_overflow dependem das entradas
do ciclo corrente (i_push, i_downstream_ready).

Observacao de projeto (documentada no cabecalho do RTL, nao e bug novo): ao
contrario de skid_fifo2, este modulo NAO protege a escrita contra overflow.
Por isso o teste de overflow so confere o ALARME (o_overflow + exatamente 1
$error) e NAO afirma nada sobre o conteudo da fila depois da violacao.
"""

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge, Timer

from _cocotb_helpers import run_isolated

DATA_WIDTH = 8
DEPTH = 2

FIELDS = ("curr", "line1", "line2", "curr_tag", "line1_tag", "line2_tag")


def _item(n: int):
    """Item distinto por n, com TODOS os 6 campos diferentes entre si
    (se a fiacao trocar dois campos, o teste pega)."""
    return {
        "curr": 0x10 + n,
        "line1": 0x30 + n,
        "line2": 0x50 + n,
        "curr_tag": n & 1,
        "line1_tag": (n >> 1) & 1,
        "line2_tag": 1 - (n & 1),
    }


async def _reset(dut):
    dut.rst_n.value = 0
    dut.i_push.value = 0
    dut.i_downstream_ready.value = 0
    for f in FIELDS:
        getattr(dut, f"i_{f}").value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def _step(dut, push: int, item=None, ready: int = 0):
    dut.i_push.value = push
    item = item or _item(0)
    for f in FIELDS:
        getattr(dut, f"i_{f}").value = item[f]
    dut.i_downstream_ready.value = ready
    await Timer(1, unit="ns")
    valid = int(dut.o_valid.value)
    out = {
        "valid": valid,
        "room": int(dut.o_room.value),
        "overflow": int(dut.o_overflow.value),
        "item": {f: int(getattr(dut, f"o_{f}").value) for f in FIELDS} if valid else None,
    }
    await RisingEdge(dut.clk)
    await NextTimeStep()
    return out


@cocotb.test()
async def test_reset_state(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    await ReadOnly()
    assert dut.o_valid.value == 0
    assert dut.o_room.value == 1
    assert dut.o_overflow.value == 0
    await NextTimeStep()


@cocotb.test()
async def test_single_item_all_fields_in_order(dut):
    """1 item com os 6 campos distintos: aparece so DEPOIS do push (sem
    bypass), com todos os campos intactos, e some depois do pop."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    out = await _step(dut, push=1, item=_item(1), ready=0)
    assert out["valid"] == 0, "sem bypass: push no mesmo ciclo nao deveria aparecer em o_valid"

    out = await _step(dut, push=0, ready=0)
    assert out["valid"] == 1 and out["item"] == _item(1), f"campos trocados/corrompidos: {out['item']}"

    out = await _step(dut, push=0, ready=0)  # sem ready: item permanece (o_valid nao depende de ready)
    assert out["valid"] == 1 and out["item"] == _item(1)

    out = await _step(dut, push=0, ready=1)  # pop
    assert out["valid"] == 1 and out["item"] == _item(1)

    out = await _step(dut, push=0, ready=1)
    assert out["valid"] == 0, "fila deveria estar vazia depois do pop"


@cocotb.test()
async def test_fill_to_depth_and_drain_in_order(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    await _step(dut, push=1, item=_item(1), ready=0)
    await _step(dut, push=1, item=_item(2), ready=0)

    out = await _step(dut, push=0, ready=1)
    assert out["item"] == _item(1)
    out = await _step(dut, push=0, ready=1)
    assert out["item"] == _item(2)
    out = await _step(dut, push=0, ready=1)
    assert out["valid"] == 0


@cocotb.test()
async def test_o_room_formula(dut):
    """o_room = (count + i_push - pop) < DEPTH, com o pop DO MESMO ciclo
    (formula v2). Verifica cada combinacao relevante nos estados
    count=0, 1 e 2."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    # count=0
    out = await _step(dut, push=0, ready=0)
    assert out["room"] == 1, "count=0, sem push: ha espaco"

    # leva a count=1 (o push deste ciclo; room lido ANTES da borda)
    out = await _step(dut, push=1, item=_item(1), ready=0)
    assert out["room"] == 1, "count=0 + push=1 -> 1 < 2: ha espaco"

    # count=1
    out = await _step(dut, push=0, ready=0)
    assert out["room"] == 1, "count=1, sem push: 1 < 2"
    # (nao consome o ciclo: repete a leitura com push=1 e depois leva a count=2)
    out = await _step(dut, push=1, item=_item(2), ready=0)
    assert out["room"] == 0, "count=1 + push=1, sem pop -> 2 nao e < 2: sem espaco"

    # count=2
    out = await _step(dut, push=0, ready=0)
    assert out["room"] == 0, "count=2, sem pop: cheio"
    out = await _step(dut, push=1, item=_item(3), ready=1)
    assert out["room"] == 0, "count=2 + push=1 - pop=1 -> 2: sem espaco"
    assert out["overflow"] == 0, "push+pop simultaneos com buffer cheio NAO e overflow"

    # drena: ainda ha 2 itens (1 saiu, 1 entrou); count=2 e ready=1, sem push -> room=1
    out = await _step(dut, push=0, ready=1)
    assert out["room"] == 1, "count=2, pop=1, sem push -> 1 < 2: ha espaco (olha a frente)"


@cocotb.test()
async def test_push_pop_simultaneous_when_full_keeps_order(dut):
    """buffer CHEIO + push + pop no MESMO ciclo: aceito, sem overflow, ordem
    FIFO preservada (1, 2, 3)."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    await _step(dut, push=1, item=_item(1), ready=0)
    await _step(dut, push=1, item=_item(2), ready=0)

    out = await _step(dut, push=1, item=_item(3), ready=1)
    assert out["overflow"] == 0
    assert out["item"] == _item(1)

    out = await _step(dut, push=0, ready=1)
    assert out["item"] == _item(2)
    out = await _step(dut, push=0, ready=1)
    assert out["item"] == _item(3), "item empurrado durante a corrida com buffer cheio saiu errado"
    out = await _step(dut, push=0, ready=1)
    assert out["valid"] == 0


@cocotb.test()
async def test_overflow_contract_violation(dut):
    """CAMINHO ERRADO: buffer cheio + push SEM pop. O_overflow deve subir;
    exatamente 1 $error e conferido no executor dedicado. NADA e afirmado
    sobre o conteudo depois (o modulo nao protege a escrita - ver docstring)."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    await _step(dut, push=1, item=_item(1), ready=0)
    await _step(dut, push=1, item=_item(2), ready=0)

    out = await _step(dut, push=1, item=_item(3), ready=0)
    assert out["overflow"] == 1, "cheio + push sem pop deveria sinalizar overflow"

    out = await _step(dut, push=0, ready=0)
    assert out["overflow"] == 0, "sem push, nao ha overflow"


def _runner(testcase, sim_name, expect_errors=0):
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return dict(
        testcase=testcase,
        verilog_sources=[os.path.join(proj_root, "rtl", "common", "line_window_skid.sv")],
        includes=[os.path.join(proj_root, "include")],
        toplevel="line_window_skid",
        module="test_line_window_skid",
        parameters={"DATA_WIDTH": DATA_WIDTH, "DEPTH": DEPTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=os.path.join(proj_root, "sim", sim_name),
        expect_errors=expect_errors,
    )


def test_line_window_skid_runner():
    run_isolated(
        **_runner(
            "test_reset_state,test_single_item_all_fields_in_order,"
            "test_fill_to_depth_and_drain_in_order,test_o_room_formula,"
            "test_push_pop_simultaneous_when_full_keeps_order",
            "sim_build_line_window_skid",
        )
    )


def test_line_window_skid_overflow_runner():
    """Executor dedicado: nao polui o log normal com 'ERROR:' esperado e
    confirma (via expect_errors) a contagem EXATA de disparos do $error."""
    run_isolated(**_runner("test_overflow_contract_violation", "sim_build_line_window_skid_ovf",
                           expect_errors=1))


if __name__ == "__main__":
    test_line_window_skid_runner()
    test_line_window_skid_overflow_runner()
