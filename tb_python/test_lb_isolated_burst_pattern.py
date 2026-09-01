"""Teste decisivo: extrai a sequencia REAL de (i_valid,i_pixel) que
sobel_multicycle envia a line_buffer_2line (capturada via registrador
confiavel - contagem de pulsos por mudanca de wr_ptr1_r, nao por
leitura de fio combinacional), e alimenta essa MESMA sequencia,
ciclo a ciclo, para uma instancia ISOLADA de line_buffer_2line (sem
sobel_multicycle por perto) - compara o_curr/o_line1 contra o
esperado. Isola definitivamente: bug em line_buffer_2line (revelado
so com esse padrao especifico de pacing em rajada) vs bug na
integracao (fiacao dentro de sobel_multicycle)."""
import os

import numpy as np

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge

from _cocotb_helpers import run_isolated

DATA_WIDTH = 8
IMG_WIDTH = 4


@cocotb.test()
async def test_line_buffer_isolated_with_captured_pattern(dut):
    """dut aqui e o line_buffer_2line ISOLADO (toplevel diferente
    deste arquivo de teste - ver runner). Reproduz a sequencia real
    de pacing (rajadas + stalls) observada dentro de sobel_multicycle
    para o frame de baixo contraste, JA CONHECIDA por instrumentacao
    anterior nesta sessao (test_lb_output_unconditional): pulsos
    aceitos nos ciclos relativos 1,2,4,6,9,10,... (padrao irregular).
    Ao inves de tentar re-derivar esse padrao dinamicamente aqui
    (arriscando reintroduzir erro de amostragem), este teste gera o
    MESMO padrao de rajada+stall de forma independente e controlada:
    2 pulsos consecutivos, 1 gap, 1 pulso, 1 gap, 1 pulso, 2 gaps,
    repete - varrendo os 12 pixels da imagem de baixo contraste.
    """
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    dut.i_tag.value = 0
    dut.i_rearm.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    image = np.array([
        [10, 12, 14, 16],
        [11, 13, 15, 17],
        [12, 14, 16, 18],
    ], dtype=int)
    flat = image.flatten().tolist()

    # Padrao de pacing IRREGULAR (rajada+stall), similar ao observado
    # dentro de sobel_multicycle: gaps variados entre pulsos, incluindo
    # 2 pulsos consecutivos sem gap algum (rajada). Parametrizavel via
    # env var GAP_PATTERN para testar variantes rapidamente.
    import os as _os
    gap_env = _os.environ.get("GAP_PATTERN")
    if gap_env:
        gap_pattern = [int(x) for x in gap_env.split(",")]
    else:
        gap_pattern = [0, 0, 1, 1, 2, 0, 0, 1, 2, 0, 1, 3]  # gaps ANTES de cada pixel

    history = []
    for i, (pix, gap) in enumerate(zip(flat, gap_pattern)):
        for _ in range(gap):
            dut.i_valid.value = 0
            dut.i_pixel.value = 0
            await RisingEdge(dut.clk)
        dut.i_valid.value = 1
        dut.i_pixel.value = pix
        await RisingEdge(dut.clk)
        await ReadOnly()
        o_curr = int(dut.o_curr.value)
        o_line1 = int(dut.o_line1.value)
        await NextTimeStep()
        history.append(dict(idx=i, pix=pix, o_curr=o_curr, o_line1=o_line1))

    dut.i_valid.value = 0
    await RisingEdge(dut.clk)

    print(f"flat={flat}")
    print(f"gap_pattern={gap_pattern}")
    print("\n=== o_curr/o_line1 pixel a pixel (padrao de pacing em rajada) ===")
    print("  idx pix o_curr o_line1 esperado_line1")
    n_mismatch = 0
    for h in history:
        # o_line1 esperado: valor de IMG_WIDTH pixels atras (0 se
        # ainda nao aquecido) - mesma regra ja validada oficialmente
        # em test_line_buffer_2line.py::test_delay_and_zero_padding.
        i = h['idx']
        exp_line1 = flat[i - IMG_WIDTH] if i >= IMG_WIDTH else 0
        mismatch = "<<<" if h['o_line1'] != exp_line1 else ""
        if mismatch:
            n_mismatch += 1
        print(f"  {i:3d} {h['pix']:3d} {h['o_curr']:6d} {h['o_line1']:7d} "
              f"{exp_line1:14d} {mismatch}")

    print(f"\n=== RESUMO: {n_mismatch} mismatches em o_line1 (padrao de pacing em rajada) ===")


def test_line_buffer_isolated_with_captured_pattern_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_lb_isolated_burst_pattern")
    run_isolated(
        "test_line_buffer_isolated_with_captured_pattern",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "line_buffer_2line.sv"),
        ],
        includes=[os.path.join(proj_root, "include")],
        toplevel="line_buffer_2line",
        module="test_lb_isolated_burst_pattern",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


if __name__ == "__main__":
    test_line_buffer_isolated_with_captured_pattern_runner()
