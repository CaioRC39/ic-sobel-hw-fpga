"""Teste diagnostico dedicado (NAO faz parte da suite normal, mesmo
padrao de instrumentacao pontual ja usado no projeto - ver
docs/MANIFESTO_SCRIPTS_DIAG_F-16.md e CLAUDE.md 14.3/15.11.2) para
fechar, com evidencia real (nao deducao por leitura de codigo/grep), o
"Ponto 1 em aberto" registrado no achado novo de
RESUMO_ESTADO_PROJETO.md ("overflow de skid_fifo2 apos integrar
line_window_skid pela 1a vez"):

    o_curr/o_curr_tag de rtl/common/line_buffer_2line.sv sao HOJE
    wire puro (assign o_curr = i_pixel, latencia 0) ou saida
    REGISTRADA (curr_pix_r/curr_tag_r, atualizados so sob
    if (i_valid), latencia 1 ciclo)?

O teste anterior (test_line_buffer_2line.py::test_delay_and_zero_padding
etc.) NAO distingue os dois casos, porque so alimenta i_pixel em ciclos
com i_valid=1 - nunca varia i_pixel durante um gap (i_valid=0), que e
exatamente a condicao onde wire e registro divergem.

Metodo: alimenta 1 pulso valido, depois insere >=3 ciclos de gap
(i_valid=0) variando i_pixel/i_tag livremente a cada ciclo do gap.
- Se o_curr/o_curr_tag SAO wire puro: acompanham i_pixel/i_tag
  imediatamente durante o gap (sem nenhuma latencia de clock).
- Se SAO registrados sob if(i_valid): permanecem PARADOS no valor do
  ultimo pulso valido durante todo o gap, so atualizando no proximo
  ciclo com i_valid=1.

Isolado (so line_buffer_2line, sem window_3x3/sobel_multicycle por
perto) - elimina qualquer variavel de integracao, mede exatamente o
que o modulo em si faz.
"""

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge

from _cocotb_helpers import run_isolated

DATA_WIDTH = 8
IMG_WIDTH = 4


async def _reset(dut):
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    dut.i_tag.value = 0
    dut.i_rearm.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def _step(dut, valid: int, pixel: int, tag: int = 0, rearm: int = 0):
    dut.i_valid.value = valid
    dut.i_pixel.value = pixel
    dut.i_tag.value = tag
    dut.i_rearm.value = rearm
    await RisingEdge(dut.clk)
    await ReadOnly()
    out = {
        "curr": int(dut.o_curr.value),
        "curr_tag": int(dut.o_curr_tag.value),
    }
    await NextTimeStep()
    return out


@cocotb.test()
async def test_curr_holds_during_gap_if_registered(dut):
    """Evidencia direta e decisiva: alimenta 1 pulso valido (pixel=99,
    tag=1), depois 4 ciclos de gap variando i_pixel/i_tag para valores
    BEM diferentes (0xAA/0, 0x55/1, 0x33/0, 0x77/1) - nenhum deles
    igual ao ultimo valor valido (99/1), evitando falso-negativo por
    coincidencia numerica."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    # 1 pulso valido - este e o valor que o_curr/o_curr_tag DEVERIAM
    # manter durante o gap seguinte, se forem registrados.
    out_valid_pulse = await _step(dut, valid=1, pixel=99, tag=1)
    last_valid_curr = out_valid_pulse["curr"]
    last_valid_curr_tag = out_valid_pulse["curr_tag"]
    print(f"[pulso valido] o_curr={last_valid_curr} o_curr_tag={last_valid_curr_tag} "
          f"(deveria ser 99/1)")
    assert last_valid_curr == 99, "sanity check falhou: nem o passthrough basico funciona"
    assert last_valid_curr_tag == 1

    # 4 ciclos de gap (i_valid=0), variando i_pixel/i_tag a cada ciclo -
    # nenhum valor coincide com 99/1.
    gap_stimuli = [(0xAA, 0), (0x55, 1), (0x33, 0), (0x77, 1)]
    gap_results = []
    for pix, tag in gap_stimuli:
        out = await _step(dut, valid=0, pixel=pix, tag=tag)
        gap_results.append(out)

    print("\n=== o_curr/o_curr_tag durante o gap (i_valid=0), enquanto "
          "i_pixel/i_tag mudam livremente ===")
    print("  i_pixel_estimulo i_tag_estimulo  ->  o_curr o_curr_tag")
    for (pix, tag), out in zip(gap_stimuli, gap_results):
        print(f"  {pix:16d} {tag:14d}  ->  {out['curr']:6d} {out['curr_tag']:10d}")

    all_held_curr = all(r["curr"] == last_valid_curr for r in gap_results)
    all_held_curr_tag = all(r["curr_tag"] == last_valid_curr_tag for r in gap_results)
    any_followed_curr = any(r["curr"] == pix for (pix, tag), r in zip(gap_stimuli, gap_results))

    if all_held_curr and all_held_curr_tag:
        veredito = "REGISTRADO (curr_pix_r/curr_tag_r sob if(i_valid), latencia 1 ciclo)"
    elif any_followed_curr:
        veredito = "WIRE PURO (o_curr acompanha i_pixel imediatamente, mesmo com i_valid=0)"
    else:
        veredito = "INDETERMINADO - padrao nao bate com nenhum dos 2 casos esperados, ver log acima"

    print(f"\n=== VEREDITO (evidencia real, nao deducao): {veredito} ===")

    # O teste em si NAO falha em nenhum dos 2 casos - e puramente
    # diagnostico (mede o comportamento atual, nao impõe um esperado).
    # O veredito impresso acima e o resultado que interessa colar de
    # volta na conversa.


def test_curr_latency_confirmation_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_curr_latency_confirmation")

    run_isolated(
        "test_curr_holds_during_gap_if_registered",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "line_buffer_2line.sv"),
        ],
        includes=[os.path.join(proj_root, "include")],
        toplevel="line_buffer_2line",
        module="test_curr_latency_confirmation",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


if __name__ == "__main__":
    test_curr_latency_confirmation_runner()

# ---------------------------------------------------------------------
# COMO RODAR (no repositorio REAL, nao neste ambiente de chat - ver
# nota em CLAUDE.md 14.3 sobre distinguir evidencia real de reproducao):
#
#   cd tb_python
#   python3 -m pytest test_curr_latency_confirmation.py -v -s
#
# Colar de volta na conversa:
#   1. O bloco "=== o_curr/o_curr_tag durante o gap ... ===" completo.
#   2. A linha "=== VEREDITO ... ===".
# Isso fecha o Ponto 1 com evidencia real, sem ambiguidade.
# ---------------------------------------------------------------------