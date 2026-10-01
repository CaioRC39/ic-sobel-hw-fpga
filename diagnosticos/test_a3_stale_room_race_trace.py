"""Instrumentacao diagnostica (NAO faz parte da suite normal - mesmo
padrao de docs/MANIFESTO_SCRIPTS_DIAG_F-16.md e CLAUDE.md 14.3/15.9/
15.11.2) para confirmar ou refutar a HIPOTESE (ainda NAO fato) levantada
apos a 2a falha consecutiva da Alternativa A3 (test_small_image_with_
external_stalls e test_four_consecutive_frames, ambos falhando DEPOIS
da correcao do bug do ciclo fantasma ja aplicada):

    skid_room (o_room de skid_fifo2) e calculado combinacionalmente
    sobre skid_count_r, um REGISTRADOR que so reflete o efeito de um
    push 1 ciclo DEPOIS dele acontecer. Se 2 aceites em window_3x3
    ocorrerem em ciclos proximos o suficiente, o 2o aceite pode ler um
    skid_room desatualizado (ainda sem contabilizar o push do 1o
    aceite), permitindo mais aceites do que a capacidade real de
    u_skid - overflow.

Metodologia: reproduz EXATAMENTE o cenario que disparou o overflow no
repositorio real (mesma imagem de test_small_image_with_external_stalls,
stall_prob=0.3, seed=42) e traca, ciclo a ciclo (via on_cycle no laco
JA VALIDADO _feed_image_and_collect - nunca um laco de conducao proprio,
licao de processo ja registrada em RESUMO_ESTADO_PROJETO.md), os sinais
exatos da decisao de aceite: u_window.i_valid (o aceite real), u_skid.
i_push, u_skid.skid_count_r, u_skid.o_room, win_ready e u_skid.o_overflow.
Imprime uma janela de contexto ao redor do 1o overflow observado - se a
hipotese estiver correta, o padrao esperado e: skid_room=1 no MESMO
ciclo em que um push do aceite anterior ainda nao foi refletido em
skid_count_r, permitindo um win_i_valid=1 indevido logo em seguida.
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

HIST = 12  # ciclos de contexto ANTES do 1o overflow
POST = 6  # ciclos extras impressos DEPOIS do 1o overflow


@cocotb.test()
async def test_a3_stale_room_race_trace(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    # Mesma imagem/estimulo EXATO de test_small_image_with_external_stalls
    # (tb_python/test_sobel_multicycle.py) - o cenario real que disparou
    # o overflow no repositorio do usuario.
    image = (np.arange(1, IMG_HEIGHT * IMG_WIDTH + 1) * 17 % 256).reshape(IMG_HEIGHT, IMG_WIDTH)

    history = []
    printing_left = 0
    overflow_count = 0

    def fmt(h):
        return (f"  {h['cyc']:4d} win_i_valid={h['win_i_valid']} skid_push={h['skid_push']} "
                f"skid_count={h['skid_count']} skid_room={h['skid_room']} "
                f"win_ready={h['win_ready']} overflow={h['overflow']}")

    def on_cycle(cyc, i_valid, i_pixel):
        nonlocal printing_left, overflow_count
        row = dict(
            cyc=cyc,
            win_i_valid=int(dut.u_window.i_valid.value),
            skid_push=int(dut.u_skid.i_push.value),
            skid_count=int(dut.u_skid.skid_count_r.value),
            skid_room=int(dut.u_skid.o_room.value),
            win_ready=int(dut.win_ready.value),
            overflow=int(dut.u_skid.o_overflow.value),
        )
        history.append(row)
        if len(history) > HIST:
            history.pop(0)

        if row["overflow"]:
            overflow_count += 1
            if overflow_count == 1:
                print(f"\n=== 1o OVERFLOW no ciclo {cyc} - contexto "
                      f"({len(history)} ciclos ate aqui) ===")
                for h in history:
                    print(fmt(h))
                printing_left = POST
        elif printing_left > 0:
            print(fmt(row))
            printing_left -= 1

    try:
        await _feed_image_and_collect(dut, image, stall_prob=0.3, seed=42, on_cycle=on_cycle)
    except TimeoutError:
        pass  # esperado - ver docstring, o overflow ja documentado impede a coleta completa

    print(f"\n=== RESUMO: overflow_count={overflow_count} ===")


def test_a3_stale_room_race_trace_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_a3_stale_room_race_trace")

    run_isolated(
        "test_a3_stale_room_race_trace",
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
        module="test_a3_stale_room_race_trace",
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
    test_a3_stale_room_race_trace_runner()

# ---------------------------------------------------------------------
# COMO RODAR (no repositorio REAL):
#
#   cd tb_python
#   python3 -m pytest test_a3_stale_room_race_trace.py -v -s
#
# Colar de volta na conversa:
#   1. O bloco "=== 1o OVERFLOW no ciclo ... ===" completo (a tabela
#      inteira, incluindo os POST=6 ciclos extras depois).
#   2. A linha "=== RESUMO: overflow_count=... ===".
#
# Se skid_room=1 aparecer no mesmo ciclo (ou 1 ciclo antes) de um
# skid_push=1 que ainda nao esta refletido em skid_count, e logo depois
# um win_i_valid=1 extra aparecer antes de skid_count realmente subir -
# isso confirma a hipotese da leitura desatualizada (stale) do registrador.
# Se o padrao for outro, a hipotese cai e preciso olhar de novo.
# ---------------------------------------------------------------------
