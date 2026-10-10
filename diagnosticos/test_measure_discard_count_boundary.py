"""Teste minimo, dedicado (NAO faz parte da suite normal, NAO altera
RTL) para responder, com evidencia real e sem suposicao, a pergunta
que decide a formula da Alternativa A (RESUMO_ESTADO_PROJETO.md,
proximo bloqueador): o numero de pulsos win_valid_real "residuais"
(win_tag != frame_tag_r) observado em CADA fronteira de frame - medido
como 3, de forma consistente, nas 3 fronteiras com IMG_WIDTH=4 (ver
Teste A/C da rodada anterior de diagnostico) - e uma CONSTANTE
ESTRUTURAL (ligada a profundidade fixa dos buffers elasticos
line_window_skid/skid_fifo2, independente da geometria da imagem) ou
ESCALA com IMG_WIDTH (o que faria "3" ser so uma coincidencia de
IMG_WIDTH-1=3 neste caso de teste pequeno, e completamente errado para
IMG_WIDTH=640, o alvo real de producao)?

Metodologia: mede o residuo de forma AUTOMATICA (nunca hardcoded) -
para cada toggle de frame_tag_r (deteccao por registrador real, mesma
tecnica ja validada no projeto), conta quantos eventos win_valid_real
CONSECUTIVOS, a partir do 1o evento apos o toggle, tem win_tag
diferente do frame_tag_r vigente, ate o 1o evento onde eles batem -
esse numero e o residuo daquela fronteira. Roda a MESMA sequencia
logica (4 frames, 3 formulas de geracao de imagem identicas as ja
usadas em test_four_consecutive_frames, generalizadas para IMG_WIDTH
qualquer) em 2 larguras distintas (4 e 8), IMG_HEIGHT fixo em 3 -
isola IMG_WIDTH como a UNICA variavel, mesmo padrao ja usado em
test_uskid_push_burst_scaling.py.

Reusa _feed_image_and_collect ja validado (nunca um laco de conducao
proprio - licao de processo ja registrada no projeto).
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
IMG_HEIGHT = 3  # fixo - isola IMG_WIDTH como unica variavel


def _images(img_width: int):
    hw = IMG_HEIGHT * img_width
    return [
        (np.arange(1, hw + 1) * 17 % 256).reshape(IMG_HEIGHT, img_width),
        (np.arange(50, 50 + hw) * 23 % 256).reshape(IMG_HEIGHT, img_width),
        (np.arange(7, 7 + hw) * 31 % 256).reshape(IMG_HEIGHT, img_width),
        (np.arange(100, 100 + hw) * 41 % 256).reshape(IMG_HEIGHT, img_width),
    ]


@cocotb.test()
async def test_measure_discard_count_per_boundary(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    img_width = int(os.environ.get("TEST_IMG_WIDTH", "4"))
    print(f"\n>>> Medindo residuo de fronteira com IMG_WIDTH={img_width}, "
          f"IMG_HEIGHT={IMG_HEIGHT} (lido de TEST_IMG_WIDTH)")

    images = _images(img_width)

    # Stream GLOBAL, continuo, sem reset por frame - so assim a deteccao
    # de toggle e a contagem de residuo por fronteira ficam corretas
    # (mesmo principio ja usado no Teste A/B da rodada anterior).
    global_events = []  # (frame_idx, cyc, frame_tag_r, win_tag, pos)
    prev_ftag_holder = {"v": 0}
    toggle_cycles = []
    # por frame, guardar posição ordinal: 0,1,2,...
    pos_holder = {"v": 0}

    for frame_idx, image in enumerate(images):
        # captura fidx por default arg: evita o clássico bug de closure tardio
        def on_cycle(cyc, i_valid, i_pixel, fidx=frame_idx):
            ftag = int(dut.frame_tag_r.value)
            if ftag != prev_ftag_holder["v"]:
                toggle_cycles.append((len(global_events), cyc, ftag))
            prev_ftag_holder["v"] = ftag
            if int(dut.win_valid_real.value):
                wtag = int(dut.win_tag.value)
                global_events.append((fidx, cyc, ftag, wtag, pos_holder["v"]))
            pos_holder["v"] += 1

        await _feed_image_and_collect(dut, image, stall_prob=0.0, seed=frame_idx,
                                       on_cycle=on_cycle)

    print(f"total_win_valid_real_events={len(global_events)} "
          f"(esperado 4x{IMG_HEIGHT}x{img_width}={4*IMG_HEIGHT*img_width})")
    print(f"toggles_de_frame_tag_r={len(toggle_cycles)} (esperado 3, para 4 frames)")

    # Para cada toggle, localiza o indice do 1o evento GLOBAL cujo ciclo
    # e >= ciclo do toggle, e conta quantos eventos CONSECUTIVOS a partir
    # dali tem win_tag != frame_tag_r vigente (residuo daquela fronteira).
    residual_counts = []
    for (gidx_hint, toggle_cyc, new_ftag) in toggle_cycles:
        start_idx = gidx_hint
        if start_idx >= len(global_events):
            print(f"  fronteira em cyc={toggle_cyc}: nenhum evento apos o toggle")
            continue

        count = 0
        i = start_idx
        while i < len(global_events) and global_events[i][3] != new_ftag:
            count += 1
            i += 1
        residual_counts.append(count)
        print(f"  fronteira em cyc={toggle_cyc} (novo frame_tag_r={new_ftag}): "
              f"residuo medido={count} pulsos")

    # --- Diagnostico por frame: ok vs residual ---
    per_frame = {f: {"ok": 0, "res": 0} for f in range(len(images))}
    for (fidx, cyc, ftag, wtag, _pos) in global_events:
        if wtag == ftag:
            per_frame[fidx]["ok"] += 1
        else:
            per_frame[fidx]["res"] += 1

    esperado_por_frame = IMG_HEIGHT * img_width
    print(f"\n--- Diagnostico por frame (esperado ok={esperado_por_frame} por frame) ---")
    total_ok = total_res = 0
    for f in range(len(images)):
        ok = per_frame[f]["ok"]
        res = per_frame[f]["res"]
        total_ok += ok
        total_res += res
        flag = "" if ok == esperado_por_frame else "  <-- DESVIO"
        print(f"  frame {f}: ok={ok}  res={res}{flag}")
    print(f"  TOTAL: ok={total_ok}  res={total_res}  "
          f"(ok_esperado_total={len(images)*esperado_por_frame})")
    print(f"  soma_ok+res={total_ok+total_res}  "
          f"total_observado={len(global_events)}  "
          f"{'OK' if total_ok+total_res == len(global_events) else 'INCONSISTENTE'}")

    # --- Onde, dentro do frame, estao os pulsos 'ok' extras ---
    for f in (2, 3):   # frames de 2a ocorrencia de cada tag (0->2, 1->3)
        oks_pos = sorted(p for (fidx, cyc, ftag, wtag, p) in global_events
                         if fidx == f and wtag == ftag)
        if len(oks_pos) != esperado_por_frame:
            extras = len(oks_pos) - esperado_por_frame
            print(f"\n  frame {f}: {len(oks_pos)} pulsos 'ok' "
                  f"({extras:+d} vs esperado {esperado_por_frame})")
            cycs = [cyc for (fidx, cyc, ftag, wtag, p) in global_events
                    if fidx == f and wtag == ftag]
            print(f"    posicoes 'ok': {oks_pos}")
            print(f"    ciclos:       {cycs}")
            print(f"    deltas:       {[cycs[i+1]-cycs[i] for i in range(len(cycs)-1)]}")
        else:
            print(f"\n  frame {f}: {len(oks_pos)} pulsos 'ok' (= esperado)")
    
    print(f"\n=== RESUMO IMG_WIDTH={img_width}: residuos por fronteira = {residual_counts} ===")
    if len(set(residual_counts)) == 1:
        print(f"CONSISTENTE: todas as fronteiras desta largura tem o MESMO residuo "
              f"({residual_counts[0]}).")
    else:
        print(f"INCONSISTENTE: fronteiras desta largura tem residuos DIFERENTES entre si "
              f"({residual_counts}) - a formula do limiar precisaria ser mais cuidadosa "
              f"que uma constante unica.")

    print(f"\n>>> Para decidir constante-vs-escala-com-IMG_WIDTH, compare este resumo "
          f"com o resumo da OUTRA largura testada (rode o outro runner e compare os "
          f"valores de 'residuos por fronteira' entre as 2 execucoes).")


def _runner(width: int):
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", f"sim_build_discard_count_w{width}")
    run_isolated(
        "test_measure_discard_count_per_boundary",
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
        module="test_measure_discard_count_boundary",
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


def test_measure_discard_count_w4_runner():
    _runner(4)

def test_measure_discard_count_w6_runner():
    _runner(6)

def test_measure_discard_count_w8_runner():
    _runner(8)


if __name__ == "__main__":
    test_measure_discard_count_w4_runner()
    test_measure_discard_count_w6_runner()
    test_measure_discard_count_w8_runner()

# ---------------------------------------------------------------------
# COMO RODAR (no repositorio REAL):
#
#   cp test_measure_discard_count_boundary.py <repo>/tb_python/
#   cd <repo>/tb_python
#   python3 -m pytest test_measure_discard_count_boundary.py -v -s
#
# (roda as 2 larguras em sequencia; pode rodar 1 de cada vez, ex:
#   python3 -m pytest test_measure_discard_count_boundary.py::test_measure_discard_count_w8_runner -v -s
# )
#
# Colar de volta na conversa OS 2 blocos "=== RESUMO IMG_WIDTH=... ==="
# completos (w4 e w8) - a comparacao entre os 2 e o que decide a formula:
#
#   - Se os residuos por fronteira forem IGUAIS nas 2 larguras (ex:
#     [3,3,3] em w4 E em w8) -> residuo e CONSTANTE ESTRUTURAL
#     (provavelmente ligado a DEPTH=2 de line_window_skid + DEPTH=2 de
#     skid_fifo2) -> a Alternativa A deve usar um numero fixo pequeno,
#     NAO IMG_WIDTH-dependente.
#   - Se os residuos escalarem com a largura (ex: 3 em w4, 7 em w8,
#     compativel com IMG_WIDTH-1) -> a formula certa e IMG_WIDTH-1 (ou
#     equivalente), e so ai seria seguro usar isso em IMG_WIDTH=640.
# ---------------------------------------------------------------------
