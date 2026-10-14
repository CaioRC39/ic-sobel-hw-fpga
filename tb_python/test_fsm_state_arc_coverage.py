"""Cobertura FUNCIONAL explicita da FSM de rtl/multicycle/mac_control_fsm.sv.

Motivo (Fase 4): o --coverage do Verilator nao tem categoria de FSM (nao
conta estados/arcos). Este teste mede diretamente o que importa:
  - 16/16 estados visitados;
  - 17/17 arcos (estado -> proximo estado) observados;
  - NENHUM estado ou arco fora do esperado (ilegais).

Exclusao justificada: o braco `default` do case (estados 16..31 do enum de 5
bits) e inalcancavel em operacao normal; nenhuma ferramenta o cobre sem forcar
o estado. Qualquer visita a ele aparece aqui como estado ilegal e falha.

Amostragem: UM unico laco (driver) amostra state_r a cada ciclo no padrao do
projeto (RisingEdge -> ReadOnly -> ler -> NextTimeStep). Nao ha coroutine de
monitor separada: duas coroutines acordando no mesmo ReadOnly nao tem ordem
garantida e poderiam perder a ultima amostra.
"""

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge

from _cocotb_helpers import run_isolated
from test_mac_control_fsm import _pack_window, _reset

DATA_WIDTH = 8
COEFF_WIDTH = 3
ACC_WIDTH = 11

STATE_NAMES = {
    0: "S_IDLE", 1: "S_LOAD_WIN",
    2: "S_MAC_GX_0", 3: "S_MAC_GX_1", 4: "S_MAC_GX_2",
    5: "S_MAC_GX_3", 6: "S_MAC_GX_4", 7: "S_MAC_GX_5",
    8: "S_SAVE_GX",
    9: "S_MAC_GY_0", 10: "S_MAC_GY_1", 11: "S_MAC_GY_2",
    12: "S_MAC_GY_3", 13: "S_MAC_GY_4", 14: "S_MAC_GY_5",
    15: "S_OUTPUT",
}
S_IDLE, S_OUTPUT = 0, 15

EXPECTED_STATES = set(STATE_NAMES)
# IDLE->IDLE, IDLE->LOAD, 14 arcos sequenciais (1->2 ... 14->15), OUTPUT->IDLE = 17
EXPECTED_ARCS = {(0, 0), (0, 1)} | {(s, s + 1) for s in range(1, 15)} | {(15, 0)}
ONE_PASS = list(range(1, 16)) + [0]  # LOAD ... OUTPUT, IDLE

WINDOWS = [
    [[10, 20, 30], [40, 50, 60], [70, 80, 90]],
    [[12, 200, 45], [78, 3, 250], [99, 150, 6]],
]


def _name(s):
    return STATE_NAMES.get(s, f"ILEGAL({s})")


def _fsm_coverage_gaps(seq):
    """seq: sequencia de estados, um por ciclo, JA incluindo o estado inicial."""
    states = set(seq)
    arcs = set(zip(seq, seq[1:]))
    return {
        "missing_states": EXPECTED_STATES - states,
        "illegal_states": states - EXPECTED_STATES,
        "missing_arcs": EXPECTED_ARCS - arcs,
        "illegal_arcs": arcs - EXPECTED_ARCS,
    }


def _fmt_arcs(arcs):
    return sorted(f"{_name(a)}->{_name(b)}" for a, b in arcs)


# ----------------------------------------------------------------------
# Canario da propria verificacao (Python puro, sem simulador)
# ----------------------------------------------------------------------
def test_arc_checker_detects_missing_and_illegal():
    full = [0, 0] + ONE_PASS  # contem IDLE->IDLE
    g = _fsm_coverage_gaps(full)
    assert all(not v for v in g.values()), f"sequencia ideal deveria fechar 100%: {g}"
    assert len(EXPECTED_ARCS) == 17 and len(EXPECTED_STATES) == 16

    # sem nenhum ciclo ocioso: falta so o auto-laco do IDLE
    g = _fsm_coverage_gaps([0] + ONE_PASS)
    assert g["missing_arcs"] == {(0, 0)} and not g["illegal_arcs"]

    # estado 4 pulado (3 -> 5): 1 estado faltando, 2 arcos faltando, 1 arco ilegal
    skipped = [0, 0] + [s for s in ONE_PASS if s != 4]
    g = _fsm_coverage_gaps(skipped)
    assert g["missing_states"] == {4}
    assert g["missing_arcs"] == {(3, 4), (4, 5)}
    assert g["illegal_arcs"] == {(3, 5)}

    # estado inalcancavel visitado (20)
    g = _fsm_coverage_gaps(full + [20, 0])
    assert g["illegal_states"] == {20}


# ----------------------------------------------------------------------
# Teste de simulacao
# ----------------------------------------------------------------------
async def _tick(dut):
    """1 ciclo: amostra (state_r, o_valid) de forma estavel apos a borda."""
    await RisingEdge(dut.clk)
    await ReadOnly()
    sample = (int(dut.state_r.value), int(dut.o_valid.value))
    await NextTimeStep()
    return sample


@cocotb.test()
async def test_fsm_state_arc_coverage(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    # Estado inicial pos-reset (mesmo padrao de test_reset_state do projeto)
    await ReadOnly()
    initial = int(dut.state_r.value)
    await NextTimeStep()
    assert initial == S_IDLE, f"pos-reset esperado S_IDLE, obtido {_name(initial)}"

    seq = [initial]
    valids = []

    async def step():
        state, o_valid = await _tick(dut)
        seq.append(state)
        valids.append((state, o_valid))

    for _ in range(3):  # ociosos: exercita IDLE->IDLE
        await step()

    for window in WINDOWS:
        # i_valid so com a FSM em IDLE (contrato); 1o ciclo = IDLE -> LOAD_WIN
        dut.i_valid.value = 1
        dut.i_window.value = _pack_window(window)
        await step()
        dut.i_valid.value = 0
        dut.i_window.value = 0
        for _ in range(15):  # LOAD_WIN ... OUTPUT, e a volta a IDLE
            await step()

    for _ in range(3):  # ociosos de novo, apos uma operacao completa
        await step()

    gaps = _fsm_coverage_gaps(seq)
    n_states = len(EXPECTED_STATES - gaps["missing_states"])
    n_arcs = len(EXPECTED_ARCS - gaps["missing_arcs"])
    dut._log.info(f"FSM: estados {n_states}/16, arcos {n_arcs}/17, ciclos amostrados={len(seq)}")

    assert not gaps["illegal_states"], (
        f"estados ILEGAIS visitados: {sorted(_name(s) for s in gaps['illegal_states'])}"
    )
    assert not gaps["illegal_arcs"], f"arcos ILEGAIS: {_fmt_arcs(gaps['illegal_arcs'])}"
    assert not gaps["missing_states"], (
        f"estados NAO visitados: {sorted(_name(s) for s in gaps['missing_states'])}"
    )
    assert not gaps["missing_arcs"], f"arcos NAO observados: {_fmt_arcs(gaps['missing_arcs'])}"

    # Sequencia exata de cada passagem (LOAD_WIN=1 ocorre 1x por janela)
    starts = [i for i, s in enumerate(seq) if s == 1]
    assert len(starts) == len(WINDOWS), (
        f"esperava {len(WINDOWS)} passagens por S_LOAD_WIN, obtive {len(starts)}"
    )
    for k, i in enumerate(starts):
        got = seq[i:i + 16]
        assert got == ONE_PASS, (
            f"passagem {k}: sequencia {[_name(s) for s in got]} != esperada "
            f"{[_name(s) for s in ONE_PASS]}"
        )

    # state_r e o sinal real: o_valid sobe exatamente em S_OUTPUT (e so la)
    for state, o_valid in valids:
        assert (o_valid == 1) == (state == S_OUTPUT), (
            f"o_valid={o_valid} com state_r={_name(state)}: state_r nao reflete a operacao real"
        )
    assert sum(1 for _, v in valids if v) == len(WINDOWS)


def test_fsm_state_arc_coverage_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_fsm_state_arc_coverage")

    run_isolated(
        "test_fsm_state_arc_coverage",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "abs_saturate.sv"),
            os.path.join(proj_root, "rtl", "common", "magnitude_l1.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "mac_unit.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "kernel_rom.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "mac_control_fsm.sv"),
        ],
        includes=[os.path.join(proj_root, "include")],
        toplevel="mac_control_fsm",
        module="test_fsm_state_arc_coverage",
        parameters={"DATA_WIDTH": DATA_WIDTH, "COEFF_WIDTH": COEFF_WIDTH, "ACC_WIDTH": ACC_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
        expect_errors=0,  # qualquer violacao de contrato na conducao falha alto
    )


if __name__ == "__main__":
    test_fsm_state_arc_coverage_runner()