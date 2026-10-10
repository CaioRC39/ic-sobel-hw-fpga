"""Testbench cocotb para rtl/multicycle/skid_fifo2.sv.

DATA_WIDTH usado aqui e o MESMO da instanciacao real em
sobel_multicycle.sv (9*DATA_WIDTH do pixel = 9*8 = 72 bits) - nao um
valor generico menor, seguindo a licao ja registrada em
docs/ARQUITETURA_MULTICICLO.md (secao 4.3, abs_saturate.sv): parametros
que "funcionam" para uma combinacao especifica nao provam que a logica
esta genericamente correta; testar com o parametro REAL de uso evita
essa armadilha.

Padrao de driving do helper _step: estimulo -> Timer(1ns) -> leitura
COMBINACIONAL (antes da borda que fecha o ciclo) -> RisingEdge ->
NextTimeStep. Diferente do padrao "RisingEdge -> ReadOnly -> captura"
usado nos demais testbenches deste projeto (mac_control_fsm, line_
buffer_2line etc.) - la faz sentido porque as saidas checadas sao elas
mesmas REGISTRADAS (o_valid/o_pixel derivam de state_r), entao "ler
logo apos a borda que as tornou validas" e o momento certo. Aqui
o_data = skid_mem_r[skid_rd_ptr_r] e puramente COMBINACIONAL sobre um
ponteiro que a PROPRIA borda de pop avanca - ler depois dessa borda ja
mostraria o proximo item, nao o que foi de fato consumido (bug real
encontrado nesta sessao ao integrar este teste, ver commit/historico:
a 1a versao usava RisingEdge->ReadOnly e reportava, por exemplo,
0xC2 onde deveria ser 0xC1 apos um overflow - diagnosticado com trace
hierarquico direto dos registradores internos antes de corrigir o
teste, nao o RTL)."""

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge, Timer

from _cocotb_helpers import run_isolated

DATA_WIDTH = 9 * 8


async def _reset(dut):
    dut.rst_n.value = 0
    dut.i_push.value = 0
    dut.i_push_data.value = 0
    dut.i_downstream_ready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def _step(dut, push: int, push_data: int = 0, ready: int = 0):
    """Aplica o estimulo deste ciclo e le o_valid/o_data/o_overflow de
    forma COMBINACIONAL, ANTES da borda de clock que fecha este ciclo -
    nao depois. o_data = skid_mem_r[skid_rd_ptr_r] e puramente
    combinacional sobre um registrador (skid_rd_ptr_r) que so avanca NA
    PROPRIA borda que consome aquele item (pop) - ler DEPOIS dessa
    borda ja mostraria o PROXIMO item (rd_ptr ja incrementado), nao o
    que foi de fato consumido neste ciclo. Mesma convencao (ler o
    estado combinacional vigente ANTES de deixar a proxima borda
    acontecer) ja usada nos testbenches puramente combinacionais deste
    projeto (test_abs_saturate.py, test_magnitude_l1.py) - aqui
    adaptada para um modulo com clock: Timer(1ns) apos o estimulo,
    ainda dentro do MESMO ciclo, antes do RisingEdge que o fecha."""
    dut.i_push.value = push
    dut.i_push_data.value = push_data
    dut.i_downstream_ready.value = ready
    await Timer(1, unit="ns")
    v = int(dut.o_valid.value)
    out = {
        "valid": v,
        "data": int(dut.o_data.value) if v else None,
        "overflow": int(dut.o_overflow.value),
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
    assert dut.o_overflow.value == 0
    await NextTimeStep()


@cocotb.test()
async def test_single_push_then_ready(dut):
    """1 item empurrado com o consumidor ainda nao pronto; so deve
    aparecer em o_data/o_valid depois que i_downstream_ready=1 - nunca
    no mesmo ciclo do push (sem bypass combinacional, ver cabecalho do
    RTL)."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    out = await _step(dut, push=1, push_data=0xAA, ready=0)
    assert out["valid"] == 0, "sem bypass: push sozinho nao deveria produzir valid no mesmo ciclo"

    out = await _step(dut, push=0, ready=1)
    assert out["valid"] == 1
    assert out["data"] == 0xAA

    out = await _step(dut, push=0, ready=1)
    assert out["valid"] == 0, "buffer deveria estar vazio apos consumir o unico item"


@cocotb.test()
async def test_fill_to_2_and_drain_in_order(dut):
    """Enche os 2 slots (sem consumidor pronto) e depois drena os 2 em
    ordem FIFO estrita (primeiro a entrar, primeiro a sair)."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    await _step(dut, push=1, push_data=0x11, ready=0)
    await _step(dut, push=1, push_data=0x22, ready=0)

    out = await _step(dut, push=0, ready=1)
    assert out["valid"] == 1 and out["data"] == 0x11

    out = await _step(dut, push=0, ready=1)
    assert out["valid"] == 1 and out["data"] == 0x22

    out = await _step(dut, push=0, ready=1)
    assert out["valid"] == 0


@cocotb.test()
async def test_push_pop_simultaneous_not_full(dut):
    """count==1 (nao cheio) + push e pop no MESMO ciclo: a saida deste
    ciclo deve ser o item ANTIGO (o que ja estava na cabeca), nunca o
    que acabou de ser empurrado - e a ordem deve continuar correta nos
    ciclos seguintes."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    await _step(dut, push=1, push_data=0x01, ready=0)  # count vai a 1

    out = await _step(dut, push=1, push_data=0x02, ready=1)  # push+pop simultaneos, count=1
    assert out["valid"] == 1
    assert out["data"] == 0x01, "deveria sair o item antigo (0x01), nao o recem-empurrado (0x02)"
    assert out["overflow"] == 0

    out = await _step(dut, push=0, ready=1)
    assert out["valid"] == 1
    assert out["data"] == 0x02, "0x02 (empurrado durante o push+pop) deveria sair em seguida"


@cocotb.test()
async def test_race_push_pop_simultaneous_when_full(dut):
    """O CASO CRITICO desta tarefa (ressalva registrada em
    RESUMO_ESTADO_PROJETO.md sobre a corrida do esboco externo): buffer
    CHEIO (2 itens) + push de um 3o item + pop no MESMO ciclo. Isto NAO
    e overflow (o pop libera a vaga no mesmo ciclo) - a escrita deve ser
    aceita, a ordem FIFO deve ser preservada integralmente (B1, B2, B3,
    nessa ordem), e o_overflow NUNCA deve subir durante este cenario.
    Reproduz exatamente o roteiro validado na reproducao isolada
    (skid_fifo2.sv, tb_skid_fifo2.sv) antes desta integracao em cocotb."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    await _step(dut, push=1, push_data=0xB1, ready=0)  # count=1
    await _step(dut, push=1, push_data=0xB2, ready=0)  # count=2 (cheio)

    # push B3 com o buffer CHEIO, E ready=1 no MESMO ciclo -> aceito,
    # sem overflow, saida deste ciclo = B1 (o mais antigo).
    out = await _step(dut, push=1, push_data=0xB3, ready=1)
    assert out["overflow"] == 0, "push+pop simultaneos com buffer cheio NAO e overflow"
    assert out["valid"] == 1
    assert out["data"] == 0xB1

    out = await _step(dut, push=0, ready=1)
    assert out["valid"] == 1 and out["data"] == 0xB2

    out = await _step(dut, push=0, ready=1)
    assert out["valid"] == 1 and out["data"] == 0xB3, (
        "B3 (empurrado durante a corrida com o buffer cheio) precisa sair intacto e na ordem certa"
    )

    out = await _step(dut, push=0, ready=1)
    assert out["valid"] == 0


@cocotb.test()
async def test_overflow_contract_violation(dut):
    """CAMINHO ERRADO: buffer CHEIO, push de um 3o item SEM pop
    simultaneo (ready=0) - viola o contrato de interface do modulo
    (cabecalho do RTL). o_overflow deve subir e o item deve ser
    descartado com seguranca, SEM corromper os 2 itens ja armazenados -
    confirmado drenando o buffer depois e conferindo que so os 2
    primeiros itens saem, na ordem certa, sem residuo do item
    descartado. A checagem do $error de fato disparar acontece no
    executor dedicado (ver capture_errors() abaixo)."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    await _step(dut, push=1, push_data=0xC1, ready=0)  # count=1
    await _step(dut, push=1, push_data=0xC2, ready=0)  # count=2 (cheio)

    out = await _step(dut, push=1, push_data=0xC3, ready=0)  # cheio, SEM pop -> overflow real
    assert out["overflow"] == 1, "buffer cheio + push sem pop deveria sinalizar overflow"
    assert out["valid"] == 0, "ready=0 neste ciclo - nao deveria haver valid"

    out = await _step(dut, push=0, ready=1)
    assert out["valid"] == 1 and out["data"] == 0xC1
    assert out["overflow"] == 0

    out = await _step(dut, push=0, ready=1)
    assert out["valid"] == 1 and out["data"] == 0xC2, (
        "apos C1, deveria sair C2 - NUNCA C3 (que foi descartado no overflow)"
    )

    out = await _step(dut, push=0, ready=1)
    assert out["valid"] == 0, "buffer deveria estar vazio - C3 nunca deveria ter entrado"


def test_skid_fifo2_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_skid_fifo2")

    run_isolated(
        "test_reset_state,test_single_push_then_ready,"
        "test_fill_to_2_and_drain_in_order,test_push_pop_simultaneous_not_full,"
        "test_race_push_pop_simultaneous_when_full",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "multicycle", "skid_fifo2.sv"),
        ],
        includes=[os.path.join(proj_root, "include")],
        toplevel="skid_fifo2",
        module="test_skid_fifo2",
        parameters={"DATA_WIDTH": DATA_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


def test_skid_fifo2_overflow_runner():
    """Executor dedicado (mesmo padrao de test_window_3x3.py /
    test_kernel_rom.py) - roda separado para nao poluir o log da
    execucao normal com linhas 'ERROR:' esperadas, e confirma a
    contagem EXATA de disparos do $error de contrato."""
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_skid_fifo2_overflow")

    run_isolated(
        "test_overflow_contract_violation",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "multicycle", "skid_fifo2.sv"),
        ],
        includes=[os.path.join(proj_root, "include")],
        toplevel="skid_fifo2",
        module="test_skid_fifo2",
        parameters={"DATA_WIDTH": DATA_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
        expect_errors=1,
    )


if __name__ == "__main__":
    test_skid_fifo2_runner()
    test_skid_fifo2_overflow_runner()
