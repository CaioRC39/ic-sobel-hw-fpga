"""Instrumentacao diagnostica (NAO faz parte da suite normal - mesmo
padrao de docs/MANIFESTO_SCRIPTS_DIAG_F-16.md e CLAUDE.md 14.3/15.11.2)
que estende test_uskid_push_burst_current_config.py: em vez de medir 1
unico IMG_WIDTH (4, o caso de teste pequeno ja usado em toda a suite),
repete a MESMA medicao (maior burst consecutivo de u_skid.i_push) para
5 larguras diferentes - 4, 16, 64, 320, 640 - a ultima sendo a
resolucao REAL documentada em toda a especificacao do projeto
(ESPECIFICACAO_SOBEL.md, ARQUITETURA_*.md: 640x480).

Objetivo: caracterizar se o burst maximo ESCALA com IMG_WIDTH (hipotese
levantada a partir da 1a medicao, onde o burst de tamanho 4 coincidiu
exatamente com IMG_WIDTH=4: "line_window_skid esta liberando uma linha
inteira de janelas de uma vez") - se confirmado, o burst maximo em
producao (640x480) seria proximo de 640, nao um numero pequeno e fixo -
informacao critica para dimensionar qualquer correcao futura
(profundidade de um skid maior, ou mecanismo de backpressure, em vez de
so aumentar skid_fifo2 para acomodar o caso de teste 4x3).

IMG_HEIGHT mantido FIXO em 3 para todas as larguras (mesma altura do
baseline ja documentado e da 1a medicao de burst) - isola IMG_WIDTH
como a UNICA variavel desta caracterizacao, evitando confundir "efeito
da largura" com "efeito da altura" na mesma rodada.

Full HD (1920x1080) NAO e tentado aqui - decisao explicita do usuario,
avaliando o custo de simulacao (~15 ciclos/pixel da FSM x milhoes de
pixels, sem contar que o overflow ja documentado faz a simulacao correr
ate o orcamento de seguranca do helper, nao ate completar o frame) como
inviavel para medicao direta. 640 (a resolucao real do projeto) e o teto
desta caracterizacao.

Cada largura exige uma elaboracao SEPARADA (IMG_WIDTH e parametro de
COMPILACAO do SystemVerilog, nao algo lido em runtime) - por isso ha 5
funcoes de runner distintas, cada uma com seu proprio sim_build e sua
propria lista de parameters=. A MESMA corrotina @cocotb.test() e
reaproveitada nas 5 - ela le a largura pretendida via variavel de
ambiente TEST_IMG_WIDTH (mesmo padrao ja usado no projeto para
GAP_PATTERN em test_lb_isolated_burst_pattern.py), gerando a imagem
numpy com a MESMA largura do parametro de elaboracao daquele build -
nao ha como errar esse alinhamento silenciosamente, porque um
descompasso causaria erro de elaboracao/shape do numpy, nao um
resultado silenciosamente errado.

Cada runner e uma funcao pytest SEPARADA (subprocesso proprio) - os
resultados NAO sao agregados automaticamente num resumo unico (o
cocotb-test nao devolve dados estruturados de volta ao processo
pytest, so levanta excecao em caso de falha) - e necessario rodar as 5
e colar os 5 blocos "=== MEDICAO ===" de volta na conversa para montar
a tabela comparativa.
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
IMG_HEIGHT = 3  # fixo em todas as larguras - ver docstring

WIDTHS_TO_TEST = [4, 16, 64, 320, 640]


@cocotb.test()
async def test_uskid_push_burst_param(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    img_width = int(os.environ.get("TEST_IMG_WIDTH", "4"))
    print(f"\n>>> Rodando com IMG_WIDTH={img_width} (lido de TEST_IMG_WIDTH), "
          f"IMG_HEIGHT={IMG_HEIGHT} (fixo)")

    # Mesma formula de geracao de imagem ja usada em toda a suite
    # (arange * multiplicador % 256) - so a largura muda.
    image = (np.arange(1, IMG_HEIGHT * img_width + 1) * 17 % 256).reshape(IMG_HEIGHT, img_width)

    stats = {
        "max_consecutive_push": 0,
        "cur_run": 0,
        "total_push_events": 0,
        "first_overflow_cycle": None,
        "total_overflow_events": 0,
        "run_history": [],
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
        # Esperado nesta config com IMG_WIDTH>=4 (ver
        # test_uskid_push_burst_current_config.py) - o overflow ja
        # documentado impede a coleta completa. Nao e falha desta
        # medicao; os stats ja foram acumulados normalmente ate o
        # orcamento de ciclos do helper se esgotar.
        timed_out = True

    if stats["cur_run"] > 0:
        stats["run_history"].append(stats["cur_run"])

    print(f"\n=== MEDICAO: IMG_WIDTH={img_width} IMG_HEIGHT={IMG_HEIGHT} ===")
    print(f"timed_out={timed_out}")
    print(f"collected={collected}")
    print(f"total_push_events={stats['total_push_events']}")
    print(f"max_consecutive_push={stats['max_consecutive_push']}")
    print(f"run_history (primeiras 20 rajadas)={stats['run_history'][:20]}")
    print(f"first_overflow_cycle={stats['first_overflow_cycle']}")
    print(f"total_overflow_events={stats['total_overflow_events']}")

    ratio = (stats["max_consecutive_push"] / img_width) if img_width else None
    print(f"max_consecutive_push / IMG_WIDTH = {ratio}")
    print(f"=== FIM MEDICAO IMG_WIDTH={img_width} ===")


def _make_runner(width: int):
    def _runner():
        proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sim_build = os.path.join(
            proj_root, "sim", f"sim_build_uskid_push_burst_scaling_w{width}"
        )

        run_isolated(
            "test_uskid_push_burst_param",
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
            module="test_uskid_push_burst_scaling",
            parameters={
                "DATA_WIDTH": DATA_WIDTH,
                "IMG_WIDTH": width,
                "IMG_HEIGHT": IMG_HEIGHT,
                "COEFF_WIDTH": COEFF_WIDTH,
                "ACC_WIDTH": ACC_WIDTH,
            },
            compile_args=["-g2012", "-Wall"],
            sim_build=sim_build,
            extra_env={"TEST_IMG_WIDTH": str(width)},
        )

    return _runner


# 5 funcoes de runner distintas (uma por largura) - pytest coleta cada
# uma separadamente (nome comeca com test_, termina com _runner, mesma
# convencao de todo o projeto).
test_uskid_push_burst_scaling_w4_runner = _make_runner(4)
test_uskid_push_burst_scaling_w16_runner = _make_runner(16)
test_uskid_push_burst_scaling_w64_runner = _make_runner(64)
test_uskid_push_burst_scaling_w320_runner = _make_runner(320)
test_uskid_push_burst_scaling_w640_runner = _make_runner(640)


if __name__ == "__main__":
    for w in WIDTHS_TO_TEST:
        _make_runner(w)()

# ---------------------------------------------------------------------
# COMO RODAR (no repositorio REAL, nao neste ambiente de chat):
#
#   cd tb_python
#   python3 -m pytest test_uskid_push_burst_scaling.py -v -s
#
# Isso roda as 5 larguras em sequencia (5 funcoes de teste pytest
# distintas). O tempo de simulacao cresce com IMG_WIDTH (mais pixels
# por linha = mais ciclos ate o orcamento de seguranca do helper se
# esgotar) - a largura 640 deve ser a mais demorada das 5, mas ainda
# assim tratavel (nao e Full HD).
#
# Colar de volta na conversa, PARA CADA UMA DAS 5 LARGURAS:
#   1. O bloco "=== MEDICAO: IMG_WIDTH=... ===" completo (ate "===FIM
#      MEDICAO...===").
#
# Se preferir rodar 1 largura de cada vez (mais rapido pra ver
# resultado parcial sem esperar as 5):
#
#   python3 -m pytest test_uskid_push_burst_scaling.py::test_uskid_push_burst_scaling_w640_runner -v -s
#
# (troque w640 pela largura desejada: w4, w16, w64, w320, w640)
# ---------------------------------------------------------------------
