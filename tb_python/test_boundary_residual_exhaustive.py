"""Diagnostico exaustivo (Rodada 2) - NAO faz parte da suite normal,
NAO altera RTL. Motivado pelo achado da Rodada 1
(test_frame3_idx7_diagnostic.py): apos corrigir o deslocamento de 1
ciclo entre Stream A (win_reg) e Stream B (win_valid_real) - que era
um artefato do PROPRIO script de diagnostico, nao do RTL (mesma
familia de erro ja catalogada em ARQUITETURA_MULTICICLO.md secao 4,
"Sexta pegadinha") - o conteudo das 3 primeiras janelas capturadas
"como sendo do frame 3" bate EXATAMENTE com a linha de padding
inferior do FRAME 2 (tag=1, valores identicos a image2[1,:] e
image2[2,:]).

Isso levanta uma duvida mais serie do que "residuo comum de
fronteira": pode ser DUPLICACAO de emissao (a mesma janela sendo
contada 2x - uma como parte legitima dos 12 outputs do frame 2, outra
de novo no stream do frame 3), nao apenas "atraso". Este arquivo
resolve essa e outras duvidas com CONTAGENS EXATAS, nao leitura visual
de log.

4 testes, cada um fechando 1 duvida especifica:

  test_A_total_win_valid_real_count
    Conta TODO evento win_valid_real ao longo dos 4 frames, num UNICO
    stream continuo (sem reset por frame) - se o total for exatamente
    48 (=4x12), NAO ha duplicacao de emissao (o RTL empurra a
    quantidade certa de janelas pro skid ao longo de toda a execucao;
    o problema, se existir, e de CONTEUDO/ORDEM, nao de contagem). Se
    for >48, confirma duplicacao real. Tambem lista, em ordem, TODO
    evento com seu frame_tag_r/win_tag e window - permite ver
    diretamente se ha 2 eventos consecutivos com CONTEUDO IDENTICO
    (assinatura de duplicacao) em vez de so tags iguais.

  test_B_boundary_signal_trace
    Trace ciclo-a-ciclo (nao so nos pulsos win_valid) ao redor de CADA
    uma das 3 transicoes de frame_tag_r (deteccao por mudanca de
    REGISTRADOR real, nao fio combinacional - mesma tecnica ja
    validada no projeto), mostrando feed_cnt_r, o_ready, win_valid,
    win_valid_real, geom, win_tag e o conteudo da janela quando
    aplicavel. Response direta para: o_ready volta a 1 (liberando o
    proximo frame) ANTES do residuo do frame anterior terminar de
    sair? As 3 fronteiras tem o MESMO padrao, ou a 1a (1->2, que nao
    produz erro de saida) e estruturalmente diferente da 2a/3a (que
    produzem)?

  test_C_geom_filtered_vs_stale_tag_count
    Separa e conta, em CADA fronteira, os 2 mecanismos DIFERENTES que
    podem estar em jogo: (i) win_valid=1 com geom=0 (janela IMPURA,
    corretamente filtrada por o_window_valid_geom - mecanismo ja
    documentado desde a investigacao do F-16/Alternativa 1) vs (ii)
    win_valid_real=1 (geom=1, aceita) mas win_tag != frame_tag_r no
    MESMO ciclo (janela PURA mas de frame errado - o mecanismo novo
    encontrado na Rodada 1). Confirma que sao fenomenos distintos, com
    contagem propria cada um.

  test_D_exact_output_pixel_attribution
    Para o frame 3 especificamente, mapeia CADA um dos 12
    win_valid_real (na ordem, que e a ordem de consumo da FIFO
    skid_fifo2 - preserva ordem) para a posicao (linha,coluna) que ele
    EFETIVAMENTE ocupa na saida de 12 pixels do frame 3, e imprime,
    lado a lado, win_tag/frame_tag_r/geom/window/pixel_final. Fecha,
    de uma vez, exatamente QUAL evento produziu o pixel errado
    (idx=7) e se o win_tag dele bate ou nao com frame_tag_r=0
    (tag esperada do frame 3).
"""

import os

import numpy as np

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from _cocotb_helpers import run_isolated
from test_sobel_multicycle import _feed_image_and_collect, _reference_sobel_l1

DATA_WIDTH = 8
COEFF_WIDTH = 3
ACC_WIDTH = 11
IMG_WIDTH = 4
IMG_HEIGHT = 3


def _unpack_window(raw: int, data_width: int):
    mask = (1 << data_width) - 1
    window = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
    for r in range(3):
        for c in range(3):
            k = 3 * r + c
            shift = (8 - k) * data_width
            window[r][c] = (raw >> shift) & mask
    return window


def _images():
    return [
        (np.arange(1, IMG_HEIGHT * IMG_WIDTH + 1) * 17 % 256).reshape(IMG_HEIGHT, IMG_WIDTH),
        (np.arange(50, 50 + IMG_HEIGHT * IMG_WIDTH) * 23 % 256).reshape(IMG_HEIGHT, IMG_WIDTH),
        (np.arange(7, 7 + IMG_HEIGHT * IMG_WIDTH) * 31 % 256).reshape(IMG_HEIGHT, IMG_WIDTH),
        (np.arange(100, 100 + IMG_HEIGHT * IMG_WIDTH) * 41 % 256).reshape(IMG_HEIGHT, IMG_WIDTH),
    ]


async def _do_reset(dut):
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


# ---------------------------------------------------------------------
# Teste A
# ---------------------------------------------------------------------
@cocotb.test()
async def test_A_total_win_valid_real_count(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _do_reset(dut)

    images = _images()
    global_events = []  # (global_idx, cyc, frame_python_idx, frame_tag_r, win_tag, window)

    for frame_idx, image in enumerate(images):
        def on_cycle(cyc, i_valid, i_pixel, _fidx=frame_idx):
            if int(dut.win_valid_real.value):
                raw = int(dut.u_window.o_window.value)
                win = _unpack_window(raw, DATA_WIDTH)
                ftag = int(dut.frame_tag_r.value)
                wtag = int(dut.win_tag.value)
                global_events.append((len(global_events), cyc, _fidx + 1, ftag, wtag, win))

        await _feed_image_and_collect(dut, image, stall_prob=0.0, seed=frame_idx,
                                       on_cycle=on_cycle)

    total = len(global_events)
    expected_total = 4 * IMG_WIDTH * IMG_HEIGHT
    print(f"\n=== TESTE A: total de win_valid_real ao longo dos 4 frames ===")
    print(f"total_observado={total}  esperado(4x12)={expected_total}")
    if total != expected_total:
        print(f"*** DIVERGENCIA DE CONTAGEM: {total - expected_total:+d} eventos a mais/menos ***")
    else:
        print("Contagem BATE - nao ha duplicacao/perda de emissao no total geral.")

    print("\n--- lista completa, em ordem, de TODO evento win_valid_real ---")
    print("  gidx cyc frame_py frame_tag_r win_tag  window")
    for (gidx, cyc, fpy, ftag, wtag, win) in global_events:
        mism = "  <-- win_tag != frame_tag_r" if wtag != ftag else ""
        print(f"  {gidx:4d} {cyc:4d}    {fpy}        {ftag}         {wtag}   {win}{mism}")

    # Deteccao de CONTEUDO IDENTICO entre eventos consecutivos (assinatura
    # de duplicacao de emissao, distinta de "so a tag bate por
    # coincidencia").
    print("\n--- verificacao de conteudo DUPLICADO (2 eventos com window identica) ---")
    dup_found = False
    for i in range(1, len(global_events)):
        if global_events[i][5] == global_events[i - 1][5]:
            dup_found = True
            print(f"  DUPLICATA: gidx={i-1} e gidx={i} tem window IDENTICA: "
                  f"{global_events[i][5]}")
    if not dup_found:
        print("  Nenhuma duplicata de conteudo entre eventos consecutivos.")


# ---------------------------------------------------------------------
# Teste B
# ---------------------------------------------------------------------
@cocotb.test()
async def test_B_boundary_signal_trace(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _do_reset(dut)

    images = _images()
    HIST, POST = 10, 40
    history = []
    printing_left = 0
    prev_ftag = 0
    toggle_count = 0

    def fmt(h):
        return (f"  {h['cyc']:5d} i_valid={h['i_valid']} o_ready={h['o_ready']} "
                f"feed_cnt={h['feed_cnt']:3d} ftag={h['ftag']} win_valid={h['wv']} "
                f"win_valid_real={h['wvr']} geom={str(h['geom']):4s} win_tag={str(h['wtag']):4s} "
                f"window={h['win']}")

    for frame_idx, image in enumerate(images):
        def on_cycle(cyc, i_valid, i_pixel, _fidx=frame_idx):
            nonlocal prev_ftag, toggle_count, printing_left
            ftag = int(dut.frame_tag_r.value)
            wv = int(dut.win_valid.value)
            wvr = int(dut.win_valid_real.value)
            geom = int(dut.u_window.o_window_valid_geom.value) if wv else None
            wtag = int(dut.win_tag.value) if wv else None
            win = (_unpack_window(int(dut.u_window.o_window.value), DATA_WIDTH)
                   if wv else None)
            row = dict(cyc=cyc, i_valid=i_valid, o_ready=int(dut.o_ready.value),
                       feed_cnt=int(dut.feed_cnt_r.value), ftag=ftag, wv=wv, wvr=wvr,
                       geom=geom, wtag=wtag, win=win)
            history.append(row)
            if len(history) > HIST:
                history.pop(0)

            toggled = (ftag != prev_ftag)
            prev_ftag = ftag
            if toggled:
                toggle_count += 1
                print(f"\n=== TOGGLE #{toggle_count} de frame_tag_r no ciclo {cyc} "
                      f"(novo valor={ftag}) - fronteira frame {_fidx}->{_fidx+1} "
                      f"(1-indexed) ===")
                for h in history:
                    print(fmt(h))
                printing_left = POST
            elif printing_left > 0:
                print(fmt(row))
                printing_left -= 1

        await _feed_image_and_collect(dut, image, stall_prob=0.0, seed=frame_idx,
                                       on_cycle=on_cycle)

    print(f"\n=== RESUMO TESTE B: {toggle_count} toggles de frame_tag_r observados "
          f"(esperado: 3, para 4 frames) ===")


# ---------------------------------------------------------------------
# Teste C
# ---------------------------------------------------------------------
@cocotb.test()
async def test_C_geom_filtered_vs_stale_tag_count(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _do_reset(dut)

    images = _images()
    per_frame_geom_zero = [0, 0, 0, 0]
    per_frame_stale_tag = [0, 0, 0, 0]
    per_frame_win_valid = [0, 0, 0, 0]
    per_frame_win_valid_real = [0, 0, 0, 0]

    for frame_idx, image in enumerate(images):
        def on_cycle(cyc, i_valid, i_pixel, _fidx=frame_idx):
            wv = int(dut.win_valid.value)
            if not wv:
                return
            per_frame_win_valid[_fidx] += 1
            geom = int(dut.u_window.o_window_valid_geom.value)
            if geom == 0:
                per_frame_geom_zero[_fidx] += 1
            wvr = int(dut.win_valid_real.value)
            if wvr:
                per_frame_win_valid_real[_fidx] += 1
                wtag = int(dut.win_tag.value)
                ftag = int(dut.frame_tag_r.value)
                if wtag != ftag:
                    per_frame_stale_tag[_fidx] += 1

        await _feed_image_and_collect(dut, image, stall_prob=0.0, seed=frame_idx,
                                       on_cycle=on_cycle)

    print("\n=== TESTE C: 2 mecanismos de filtragem, contados separadamente por frame ===")
    print("  frame  win_valid  win_valid_real  geom=0(impura,filtrada)  "
          "win_tag!=frame_tag_r(pura,mas de outro frame)")
    for i in range(4):
        print(f"  {i+1:5d}  {per_frame_win_valid[i]:9d}  {per_frame_win_valid_real[i]:14d}  "
              f"{per_frame_geom_zero[i]:23d}  {per_frame_stale_tag[i]:44d}")


# ---------------------------------------------------------------------
# Teste D
# ---------------------------------------------------------------------
@cocotb.test()
async def test_D_exact_output_pixel_attribution(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _do_reset(dut)

    images = _images()
    target_frame = 2  # frame 3, 0-indexed

    for frame_idx, image in enumerate(images):
        events = []  # so relevante para target_frame

        def on_cycle(cyc, i_valid, i_pixel, _fidx=frame_idx):
            if _fidx != target_frame:
                return
            if int(dut.win_valid_real.value):
                raw = int(dut.u_window.o_window.value)
                win = _unpack_window(raw, DATA_WIDTH)
                ftag = int(dut.frame_tag_r.value)
                wtag = int(dut.win_tag.value)
                events.append((cyc, ftag, wtag, win))

        collected = await _feed_image_and_collect(dut, image, stall_prob=0.0, seed=frame_idx,
                                                    on_cycle=on_cycle)

        if frame_idx == target_frame:
            expected = _reference_sobel_l1(image)
            print(f"\n=== TESTE D: frame {frame_idx+1}/4 - atribuicao exata "
                  f"evento->posicao_de_saida ===")
            print(f"collected={collected}")
            print(f"expected ={expected}")
            print(f"len(events capturados)={len(events)}  len(collected)={len(collected)}")
            print("  posicao_saida(idx) linha col  cyc  frame_tag_r win_tag  pixel_obtido "
                  "pixel_esperado  window")
            n = min(len(events), len(collected), len(expected))
            for i in range(n):
                cyc, ftag, wtag, win = events[i]
                row, col = divmod(i, IMG_WIDTH)
                got = collected[i]
                exp = expected[i]
                mark = "  <<<< MISMATCH >>>>" if got != exp else ""
                tagmark = "  [win_tag != frame_tag_r]" if wtag != ftag else ""
                print(f"  {i:17d}    {row}    {col}  {cyc:4d}     {ftag}         {wtag}"
                      f"      {got:3d}          {exp:3d}         {win}{mark}{tagmark}")


def _runner(testname):
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", f"sim_build_boundary_residual_{testname}")
    run_isolated(
        testname,
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
        module="test_boundary_residual_exhaustive",
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


def test_A_total_win_valid_real_count_runner():
    _runner("test_A_total_win_valid_real_count")


def test_B_boundary_signal_trace_runner():
    _runner("test_B_boundary_signal_trace")


def test_C_geom_filtered_vs_stale_tag_count_runner():
    _runner("test_C_geom_filtered_vs_stale_tag_count")


def test_D_exact_output_pixel_attribution_runner():
    _runner("test_D_exact_output_pixel_attribution")


if __name__ == "__main__":
    test_A_total_win_valid_real_count_runner()
    test_B_boundary_signal_trace_runner()
    test_C_geom_filtered_vs_stale_tag_count_runner()
    test_D_exact_output_pixel_attribution_runner()

# ---------------------------------------------------------------------
# COMO RODAR (no repositorio REAL - CLAUDE.md 14.3, distinguir evidencia
# real de reproducao):
#
#   cp test_boundary_residual_exhaustive.py <repo>/tb_python/
#   cd <repo>/tb_python
#   python3 -m pytest test_boundary_residual_exhaustive.py -v -s
#
# (roda os 4 testes A-D em sequencia; cada um e independente - pode
# rodar so 1 de cada vez, ex:
#   python3 -m pytest test_boundary_residual_exhaustive.py::test_A_total_win_valid_real_count_runner -v -s
# )
#
# Colar de volta na conversa, NA INTEGRA (nao resumido - os detalhes
# finos sao o que decide entre as hipoteses):
#   1. TESTE A: o bloco "=== TESTE A ..." completo, incluindo a lista
#      linha a linha e a verificacao de duplicata.
#   2. TESTE B: os 3 blocos "=== TOGGLE #N ..." completos (cada um tem
#      ~50 linhas de trace - sim, e longo, mas e exatamente o que
#      decide se o_ready libera o proximo frame cedo demais).
#   3. TESTE C: a tabela completa (4 linhas).
#   4. TESTE D: a tabela completa (12 linhas, frame 3).
#
# NADA neste script altera RTL - e puramente observacional.
# ---------------------------------------------------------------------
