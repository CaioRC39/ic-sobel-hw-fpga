"""Evidencia dedicada da Alternativa A3 (RESUMO_ESTADO_PROJETO.md,
achado 'overflow de skid_fifo2 apos integrar line_window_skid pela
1a vez'). NAO faz parte da suite normal - roda isolado, mesmo padrao
de tb_python/test_skid_fifo2.py::test_skid_fifo2_overflow_runner
(capture_errors() em volta de run_isolated(), no processo pytest, nao
dentro da corrotina - ver docs/ARQUITETURA_MULTICICLO.md secao 4,
'Segunda pegadinha').

Cobre 2 coisas na MESMA execucao:

1. CORRETUDE + AUSENCIA DE OVERFLOW: reproduz os mesmos 4 frames de
   test_four_consecutive_frames (tb_python/test_sobel_multicycle.py) -
   a mesma sequencia que antes desta correcao disparava overflow de
   u_skid ja no 1o frame (ciclo 15, ver medicao anterior). capture_errors
   pega QUALQUER $error do logger 'cocotb' (nao filtra por origem) -
   entao tambem cobriria um eventual overflow de u_lw_skid.o_overflow,
   nao so de u_skid.

2. EVIDENCIA DE THROUGHPUT: conta ciclos totais por frame (via on_cycle,
   reaproveitando _feed_image_and_collect ja validado - NUNCA um laco de
   conducao proprio, licao de processo ja registrada) e compara contra
   a estimativa teorica de docs/ARQUITETURA_MULTICICLO.md secao 6.2
   (~15 ciclos/pixel). Isso NAO e uma assercao (o modelo teorico e
   aproximado, nao teria que bater exatamente) - e so impresso, para
   voce julgar se o overhead observado bate com a estimativa de <1%
   discutida na conversa.
"""

import os

import numpy as np

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from _cocotb_helpers import capture_errors, run_isolated
from test_sobel_multicycle import _feed_image_and_collect, _reference_sobel_l1

DATA_WIDTH = 8
COEFF_WIDTH = 3
ACC_WIDTH = 11
IMG_WIDTH = 4
IMG_HEIGHT = 3


@cocotb.test()
async def test_a3_four_frames_no_overflow(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    images = [
        (np.arange(1, IMG_HEIGHT * IMG_WIDTH + 1) * 17 % 256).reshape(IMG_HEIGHT, IMG_WIDTH),
        (np.arange(50, 50 + IMG_HEIGHT * IMG_WIDTH) * 23 % 256).reshape(IMG_HEIGHT, IMG_WIDTH),
        (np.arange(7, 7 + IMG_HEIGHT * IMG_WIDTH) * 31 % 256).reshape(IMG_HEIGHT, IMG_WIDTH),
        (np.arange(100, 100 + IMG_HEIGHT * IMG_WIDTH) * 41 % 256).reshape(IMG_HEIGHT, IMG_WIDTH),
    ]

    # Estimativa teorica (docs/ARQUITETURA_MULTICICLO.md secao 6.2) -
    # nao inclui o preenchimento inicial do pipeline (line_buffer +
    # window + os 2 skids), que para IMG_WIDTH/IMG_HEIGHT pequenos pesa
    # proporcionalmente mais - overhead real esperado > 0 mesmo SEM
    # nenhuma regressao de A3, so por causa disso. So para referencia.
    baseline_cycles = 15 * IMG_WIDTH * (IMG_HEIGHT + 1)

    for frame_idx, image in enumerate(images):
        cycle_counter = {"n": 0}

        def on_cycle(cyc, i_valid, i_pixel):
            cycle_counter["n"] += 1

        collected = await _feed_image_and_collect(dut, image, stall_prob=0.0, seed=frame_idx,
                                                    on_cycle=on_cycle)
        expected = _reference_sobel_l1(image)
        assert collected == expected, (
            f"frame {frame_idx + 1}/4: conteudo divergiu da referencia - a Alternativa A3 "
            f"deveria alterar so o TIMING de entrega a window_3x3, nunca a corretude"
        )

        total = cycle_counter["n"]
        overhead_pct = 100.0 * (total - baseline_cycles) / baseline_cycles
        print(f"[frame {frame_idx + 1}/4] ciclos_totais={total} "
              f"baseline_teorico={baseline_cycles} overhead={overhead_pct:.2f}%")


def test_a3_four_frames_no_overflow_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_a3_room_gating_evidence")

    with capture_errors() as capture:
        run_isolated(
            "test_a3_four_frames_no_overflow",
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
            module="test_a3_room_gating_evidence",
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

    assert capture.count == 0, (
        f"esperava ZERO disparos de $error (overflow de u_skid OU de u_lw_skid) apos a "
        f"Alternativa A3 - obtido {capture.count}. Ver log acima para a origem exata."
    )


if __name__ == "__main__":
    test_a3_four_frames_no_overflow_runner()

# ---------------------------------------------------------------------
# COMO RODAR (no repositorio REAL, apos aplicar os 2 diffs em
# skid_fifo2.sv e sobel_multicycle.sv):
#
#   cd tb_python
#   python3 -m pytest test_a3_room_gating_evidence.py -v -s
#
# Colar de volta na conversa:
#   1. As 4 linhas "[frame N/4] ciclos_totais=... overhead=...%".
#   2. PASSED ou FAILED (e, se FAILED, a mensagem de assert completa).
#
# Recomendo tambem rodar a suite normal (make cocotb) para confirmar
# que test_sobel_multicycle.py inteiro volta a passar (estava
# provavelmente quebrado em TODOS os testes, nao so
# test_four_consecutive_frames - a mesma imagem de test_small_image_golden
# ja disparava overflow no ciclo 15, antes desta correcao).
# ---------------------------------------------------------------------
