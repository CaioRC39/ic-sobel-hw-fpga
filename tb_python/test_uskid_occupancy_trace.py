"""Instrumentacao diagnostica (NAO faz parte da suite normal - mesmo
padrao de docs/MANIFESTO_SCRIPTS_DIAG_F-16.md e CLAUDE.md 14.3/15.11.2)
para medir a OCUPACAO REAL de u_skid.skid_count_r (skid_fifo2, entre
window_3x3 e mac_control_fsm) ciclo a ciclo, ao longo do tempo - nao
so o tamanho de rajadas consecutivas de i_push, ja medido em
test_uskid_push_burst_current_config.py e test_uskid_push_burst_scaling.py.

Objetivo especifico (RESUMO_ESTADO_PROJETO.md, ultimo paragrafo do
Achado 'overflow de skid_fifo2 apos integrar line_window_skid'):
confirmar ou refutar a hipotese de ACUMULO LIQUIDO antes do 1o pop
possivel - i.e., que skid_count_r cresce de forma aproximadamente
monotonica (mais pushes que pops) durante o periodo de aquecimento de
mac_control_fsm (~15 ciclos ate o 1o resultado, ver
docs/ARQUITETURA_MULTICICLO.md secao 6.2), independente do tamanho de
qualquer rajada isolada ser pequeno (2-4, ja medido) - i.e., overflow
por ACUMULO GRADUAL, nao por um unico pico de rajada.

Isso e uma hipotese DIFERENTE da hipotese original ("burst grande
demais") ja REFUTADA pela medicao de escala (test_uskid_push_burst_scaling.py:
burst maximo NAO escala com IMG_WIDTH, fica pequeno - 2 a 4 - em toda a
faixa testada, mas overflow ocorre em todas as larguras mesmo assim).

Metodologia (reaproveita _feed_image_and_collect ja validado, NUNCA um
laco de conducao proprio - licao de processo ja registrada em
RESUMO_ESTADO_PROJETO.md, secao 'Sessao de depuracao adicional
2026-08-15', item 1): mede POR CICLO (nao so nos ciclos de push) o
valor de u_skid.skid_count_r, o proprio push (u_skid.i_push), o pop
real (u_skid.skid_pop, sinal combinacional interno ja existente no
RTL) e se fsm_ready ja esta em 1 (sinal de que mac_control_fsm esta em
S_IDLE e pode aceitar - antes disso nenhum pop e possivel por
construcao). A config testada (IMG_WIDTH=4, IMG_HEIGHT=3) e a MESMA do
baseline ja documentado - permite comparacao direta com os numeros ja
registrados (burst maximo=4, 1o overflow no ciclo 15), sem introduzir
uma variavel nova.
"""

import os

import numpy as np

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from _cocotb_helpers import run_isolated
from test_sobel_multicycle import _feed_image_and_collect

DATA_WIDTH = 8
COEFF_WIDTH = 3
ACC_WIDTH = 11
IMG_WIDTH = 4
IMG_HEIGHT = 3

SKID_DEPTH = 2  # profundidade real de skid_fifo2 (parametro fixo do modulo)


@cocotb.test()
async def test_uskid_occupancy_trace(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    # Mesma imagem (IMG_WIDTH=4, IMG_HEIGHT=3) do baseline ja
    # documentado (test_uskid_push_burst_current_config.py) - permite
    # comparacao textual direta contra os numeros ja registrados.
    image = (np.arange(1, IMG_HEIGHT * IMG_WIDTH + 1) * 17 % 256).reshape(IMG_HEIGHT, IMG_WIDTH)

    trace = []  # (cyc, count, push, pop, overflow, fsm_ready, out_valid)
    first_push_cycle = None
    first_pop_cycle = None
    first_fsm_ready_cycle = None
    max_count_seen = 0
    first_overflow_cycle = None

    def on_cycle(cyc, i_valid, i_pixel):
        nonlocal first_push_cycle, first_pop_cycle, first_fsm_ready_cycle
        nonlocal max_count_seen, first_overflow_cycle

        count = int(dut.u_skid.skid_count_r.value)
        push = int(dut.u_skid.i_push.value)
        pop = int(dut.u_skid.skid_pop.value)
        overflow = int(dut.u_skid.o_overflow.value)
        fsm_ready = int(dut.fsm_ready.value)
        out_valid = int(dut.o_valid.value)

        trace.append((cyc, count, push, pop, overflow, fsm_ready, out_valid))

        if push and first_push_cycle is None:
            first_push_cycle = cyc
        if pop and first_pop_cycle is None:
            first_pop_cycle = cyc
        if fsm_ready and first_fsm_ready_cycle is None:
            # fsm_ready comeca em 1 (S_IDLE, pos-reset) - o que importa
            # aqui e a PRIMEIRA vez que ele cai para 0 e volta a 1 DEPOIS
            # de ja ter processado algo, entao registramos so como
            # referencia contextual, nao como "1o pop possivel" (isso e
            # medido diretamente por first_pop_cycle acima).
            first_fsm_ready_cycle = cyc
        max_count_seen = max(max_count_seen, count)
        if overflow and first_overflow_cycle is None:
            first_overflow_cycle = cyc

    timed_out = False
    collected = None
    try:
        collected = await _feed_image_and_collect(dut, image, stall_prob=0.0, seed=0,
                                                    on_cycle=on_cycle)
    except TimeoutError:
        # Esperado nesta config (overflow ja documentado impede coleta
        # completa) - a medicao (trace) ja aconteceu normalmente ate o
        # orcamento de ciclos do helper se esgotar.
        timed_out = True

    print(f"\n=== MEDICAO: ocupacao de u_skid.skid_count_r ciclo a ciclo "
          f"(IMG_WIDTH={IMG_WIDTH}, IMG_HEIGHT={IMG_HEIGHT}, SKID_DEPTH={SKID_DEPTH}) ===")
    print(f"timed_out={timed_out}  collected={collected}")
    print(f"first_push_cycle={first_push_cycle}")
    print(f"first_pop_cycle={first_pop_cycle}")
    print(f"first_overflow_cycle={first_overflow_cycle}")
    print(f"max_count_seen={max_count_seen} (capacidade={SKID_DEPTH})")

    # Trecho critico: do 1o push ate um pouco depois do 1o overflow (ou
    # ate o fim do trace, se nao houve overflow) - suficiente para ver
    # a trajetoria de count_r sem despejar o trace inteiro.
    lo = max(0, (first_push_cycle or 0) - 2)
    hi = (first_overflow_cycle + 5) if first_overflow_cycle is not None else min(len(trace), lo + 40)
    print(f"\n=== TRECHO CRITICO (ciclos {lo} a {hi}) ===")
    print("  cyc count push pop overflow fsm_ready out_valid")
    for (cyc, count, push, pop, overflow, fsm_ready, out_valid) in trace:
        if lo <= cyc <= hi:
            print(f"  {cyc:4d} {count:5d} {push:4d} {pop:3d} {overflow:8d} "
                  f"{fsm_ready:9d} {out_valid:9d}")

    # Veredito: a hipotese de "acumulo liquido antes do 1o pop" preve
    # que first_pop_cycle e None (ou muito posterior a
    # first_overflow_cycle) - ou seja, o overflow acontece porque
    # NENHUM pop ainda foi possivel, nao porque uma rajada isolada
    # excedeu SKID_DEPTH de uma vez so.
    print(f"\n=== VEREDITO ===")
    if first_overflow_cycle is None:
        print("Nenhum overflow observado dentro do orcamento de ciclos medido - "
              "inconclusivo com esta janela de medicao.")
    elif first_pop_cycle is None or first_pop_cycle > first_overflow_cycle:
        print(
            f"HIPOTESE CONFIRMADA: o 1o overflow (ciclo {first_overflow_cycle}) ocorre "
            f"{'sem NENHUM pop ainda ter acontecido' if first_pop_cycle is None else f'antes do 1o pop real (ciclo {first_pop_cycle})'} "
            f"- consistente com acumulo LIQUIDO de pushes sem nenhum dreno, nao com uma "
            f"rajada isolada maior que SKID_DEPTH={SKID_DEPTH} de uma vez so."
        )
    else:
        print(
            f"HIPOTESE NAO CONFIRMADA: ja houve pop real no ciclo {first_pop_cycle}, "
            f"antes do 1o overflow (ciclo {first_overflow_cycle}) - o overflow nao pode ser "
            f"explicado so por 'nenhum dreno ainda' - requer olhar a trajetoria de count_r "
            f"no trecho critico acima para outra explicacao (ex: pops esporadicos demais "
            f"para acompanhar o ritmo de push)."
        )


def test_uskid_occupancy_trace_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_uskid_occupancy_trace")

    run_isolated(
        "test_uskid_occupancy_trace",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "line_buffer_2line.sv"),
            os.path.join(proj_root, "rtl", "common", "window_3x3.sv"),
            os.path.join(proj_root, "rtl", "common", "line_window_skid.sv"),
            os.path.join(proj_root, "rtl", "common", "abs_saturate.sv"),
            os.path.join(proj_root, "rtl", "common", "magnitude_l1.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "mac_unit.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "kernel_rom.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "mac_control_fsm.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "skid_fifo2.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "sobel_multicycle.sv"),
        ],
        includes=[os.path.join(proj_root, "include")],
        toplevel="sobel_multicycle",
        module="test_uskid_occupancy_trace",
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
    test_uskid_occupancy_trace_runner()

# ---------------------------------------------------------------------
# COMO RODAR (no repositorio REAL, nao neste ambiente de chat - ver
# CLAUDE.md 14.3 sobre distinguir evidencia real de reproducao):
#
#   cd tb_python
#   python3 -m pytest test_uskid_occupancy_trace.py -v -s
#
# Colar de volta na conversa:
#   1. O bloco "=== MEDICAO: ... ===" completo.
#   2. O bloco "=== TRECHO CRITICO ... ===" completo.
#   3. O bloco "=== VEREDITO ===" completo.
#
# Nota: assume skid_fifo2.sv com os registradores internos nomeados
# skid_count_r e o sinal combinacional skid_pop, EXATAMENTE como estao
# em rtl/multicycle/skid_fifo2.sv (Project Knowledge) - se o nome de
# algum sinal interno tiver sido alterado no seu repositorio real desde
# entao, ajuste os 2 acessos hierarquicos em on_cycle() antes de rodar.
# ---------------------------------------------------------------------
