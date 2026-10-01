"""Instrumentacao diagnostica (NAO faz parte da suite normal - mesmo
padrao de docs/MANIFESTO_SCRIPTS_DIAG_F-16.md e CLAUDE.md 14.3/15.11.2)
para medir, na configuracao ATUAL de sobel_multicycle.sv (com
line_window_skid.sv integrado no caminho line_buffer_2line ->
line_window_skid -> window_3x3 -> u_skid=skid_fifo2 -> mac_control_fsm),
o maior numero de ciclos CONSECUTIVOS em que u_skid.i_push=1.

Objetivo: confirmar ou refutar a hipotese registrada em
RESUMO_ESTADO_PROJETO.md ("Achado novo... overflow de skid_fifo2 apos
integrar line_window_skid") de que a insercao de line_window_skid
alterou o padrao de rajada de win_valid a ponto de ultrapassar a
capacidade de 2 (profundidade de skid_fifo2) que foi dimensionada com
base no baseline SEM line_window_skid (maximo medido = 2, ver secao
"Achado adicional... skid buffer" do mesmo documento).

Escopo desta medicao: APENAS a configuracao atual, isolada - sem
reconstruir a configuracao antiga (sem line_window_skid) para
comparacao direta neste mesmo teste (decisao explicita do usuario,
"Siga somente com a medicao da configuracao atual isoladamente"). O
numero absoluto medido aqui e comparado, no texto, contra o baseline JA
DOCUMENTADO (2) - nao contra uma nova execucao da config antiga.

Metodologia (reaproveita _feed_image_and_collect ja validado, NUNCA um
laco de conducao proprio - Licao de processo registrada em
RESUMO_ESTADO_PROJETO.md, secao "Sessao de depuracao adicional
2026-08-15", item 1): a config atual e conhecida por travar por
TimeoutError (overflow de u_skid impede a coleta completa dos pixels
esperados, ver log ja colado na conversa) - por isso este teste espera
e CAPTURA essa TimeoutError como resultado esperado desta medicao (nao
como falha do proprio script), e reporta as estatisticas acumuladas ate
o ponto em que a simulacao foi interrompida pelo orcamento de ciclos do
proprio helper.
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


@cocotb.test()
async def test_uskid_push_burst_current_config(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    # Mesma imagem (IMG_WIDTH=4, IMG_HEIGHT=3) ja usada no baseline
    # documentado ("Achado adicional... skid buffer") - permite
    # comparacao textual direta contra o numero ja registrado (2),
    # sem introduzir uma variavel nova (imagem diferente) na medicao.
    image = (np.arange(1, IMG_HEIGHT * IMG_WIDTH + 1) * 17 % 256).reshape(IMG_HEIGHT, IMG_WIDTH)

    stats = {
        "max_consecutive_push": 0,
        "cur_run": 0,
        "total_push_events": 0,
        "first_overflow_cycle": None,
        "total_overflow_events": 0,
        "run_history": [],  # tamanho de cada rajada fechada (para ver a distribuicao, nao so o pico)
    }

    def on_cycle(cyc, i_valid, i_pixel):
        push = int(dut.u_skid.i_push.value)
        overflow = int(dut.u_skid.o_overflow.value)

        if push:
            stats["total_push_events"] += 1
            stats["cur_run"] += 1
        else:
            if stats["cur_run"] > 0:
                stats["run_history"].append(stats["cur_run"])
            stats["cur_run"] = 0
        stats["max_consecutive_push"] = max(stats["max_consecutive_push"], stats["cur_run"])

        if overflow:
            stats["total_overflow_events"] += 1
            if stats["first_overflow_cycle"] is None:
                stats["first_overflow_cycle"] = cyc

    timed_out = False
    collected = None
    try:
        collected = await _feed_image_and_collect(dut, image, stall_prob=0.0, seed=0,
                                                    on_cycle=on_cycle)
    except TimeoutError:
        # Esperado nesta config (ver docstring) - o overflow de u_skid
        # ja documentado impede a coleta completa. Nao e falha deste
        # script de medicao; a medicao em si (stats acumulados via
        # on_cycle) ja aconteceu normalmente ate o orcamento de ciclos
        # do helper se esgotar.
        timed_out = True

    if stats["cur_run"] > 0:
        stats["run_history"].append(stats["cur_run"])

    print(f"\n=== MEDICAO: maior burst consecutivo de u_skid.i_push "
          f"(config ATUAL, com line_window_skid) ===")
    print(f"timed_out (esperado nesta config)={timed_out}")
    print(f"collected (pixels coletados antes do timeout, se houve)={collected}")
    print(f"total_push_events={stats['total_push_events']}")
    print(f"max_consecutive_push={stats['max_consecutive_push']}")
    print(f"run_history (tamanho de cada rajada fechada, em ordem)={stats['run_history']}")
    print(f"first_overflow_cycle={stats['first_overflow_cycle']}")
    print(f"total_overflow_events={stats['total_overflow_events']}")

    baseline_max = 2
    if stats["max_consecutive_push"] > baseline_max:
        veredito = (
            f"HIPOTESE CONFIRMADA: burst maximo medido ({stats['max_consecutive_push']}) "
            f"excede o baseline ja documentado sem line_window_skid ({baseline_max}) - "
            f"consistente com line_window_skid alterar o padrao de rajada de win_valid "
            f"a ponto de estourar a capacidade de skid_fifo2 (profundidade 2)."
        )
    elif stats["max_consecutive_push"] <= baseline_max and stats["total_overflow_events"] > 0:
        veredito = (
            f"HIPOTESE NAO CONFIRMADA PELO BURST MAXIMO ({stats['max_consecutive_push']} <= "
            f"{baseline_max}), MAS overflow real ocorreu mesmo assim "
            f"({stats['total_overflow_events']} disparo(s), 1o no ciclo "
            f"{stats['first_overflow_cycle']}) - a causa pode nao ser o TAMANHO do burst "
            f"isolado, e sim FREQUENCIA/proximidade de rajadas (ex: 2 rajadas de tamanho 2 "
            f"muito proximas, sem ciclo de dreno suficiente entre elas) ou outro mecanismo "
            f"nao capturado por esta metrica especifica - requer investigacao adicional, "
            f"nao descarta o problema."
        )
    else:
        veredito = (
            f"Nenhum overflow observado dentro do orcamento de ciclos medido "
            f"(burst maximo={stats['max_consecutive_push']}, overflow_events=0) - "
            f"inconclusivo com esta janela de medicao; pode requerer mais ciclos/imagem "
            f"maior para reproduzir o overflow ja visto em test_sobel_multicycle.py."
        )

    print(f"\n=== VEREDITO: {veredito} ===")


def test_uskid_push_burst_current_config_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_uskid_push_burst_current_config")

    run_isolated(
        "test_uskid_push_burst_current_config",
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
        module="test_uskid_push_burst_current_config",
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
    test_uskid_push_burst_current_config_runner()

# ---------------------------------------------------------------------
# COMO RODAR (no repositorio REAL, nao neste ambiente de chat):
#
#   cd tb_python
#   python3 -m pytest test_uskid_push_burst_current_config.py -v -s
#
# Colar de volta na conversa:
#   1. O bloco "=== MEDICAO: ... ===" completo.
#   2. A linha "=== VEREDITO: ... ===".
#
# Nota: verilog_sources acima assume que line_window_skid.sv esta em
# rtl/common/ (mesma pasta indicada no achado registrado em
# RESUMO_ESTADO_PROJETO.md - "novo modulo common/"). Se no seu
# repositorio real ele estiver em outro caminho, ajuste a lista antes
# de rodar.
# ---------------------------------------------------------------------