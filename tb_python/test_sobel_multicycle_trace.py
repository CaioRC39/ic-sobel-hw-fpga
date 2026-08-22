"""Instrumentacao diagnostica (Alternativa A, confirmada pelo usuario -
ver RESUMO_ESTADO_PROJETO.md, secao 'Pendente / em andamento agora', e
CLAUDE.md secao 15.11.2: evidencia real ANTES de qualquer alternativa de
correcao) para o bug real encontrado por test_four_consecutive_frames em
tb_python/test_sobel_multicycle.py: a janela row0 de QUALQUER frame chega
com i_line1 (linha central) sistematicamente errada em sobel_multicycle.sv,
mascarado ate agora porque as imagens de teste anteriores saturavam em 255
dos dois jeitos.

NAO E um teste de regressao permanente - e instrumentacao pontual, acesso
hierarquico via cocotb, SEM tocar em nenhum .sv ja fechado (window_3x3.sv
ja esta validado isoladamente em test_window_3x3.py, 100% PASS). Nao deve
ser adicionado ao fluxo normal de `make cocotb` de forma silenciosa - rodar
isolado (ver instrucoes no final deste arquivo) e remover/arquivar apos o
diagnostico, seguindo o padrao de "$display/trace temporario" ja prescrito
em CLAUDE.md secao 15.11.1.

Reproduz o cenario MINIMO do bug: 1 UNICO frame (RESUMO_ESTADO_PROJETO.md
ja registra que o bug aparece no 1o frame, nao so em fronteiras multiplas),
mesmos parametros de test_sobel_multicycle.py (IMG_WIDTH=4, IMG_HEIGHT=3),
sem stall externo (stall_prob=0.0) - isola a variavel de integracao
propria do modulo (gate_fsm_ok/accept_sample/consume_sample), sem
confundir com stall induzido pelo testbench.

Metodologia: compara CADA janela emitida por window_3x3 (lida via
dut.u_window.o_window, acesso hierarquico) contra a MESMA funcao de
referencia ja usada em tb_python/test_window_3x3.py
(_build_reference_windows) - nao uma nova reconstrucao do calculo, para
nao introduzir uma 2a fonte de verdade que poderia divergir da ja
validada. So imprime contexto (col_cnt_r, phantom_pending_r, i_valid,
sinais de gating) ao redor dos ciclos onde a janela capturada DIVERGE da
esperada - saida curta e orientada a diagnostico (CLAUDE.md secao 14.3),
nao um log ciclo-a-ciclo completo do frame inteiro.
"""

import os

import numpy as np

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge
from _cocotb_helpers import run_isolated

DATA_WIDTH = 8
COEFF_WIDTH = 3
ACC_WIDTH = 11
IMG_WIDTH = 4
IMG_HEIGHT = 3

HIST_LEN = 12  # ALTERADO AQUI: 6 cortava os ciclos 1-4, exatamente onde
# esta o pulso suspeito de ser descartado (ver evidencia de
# lb_warmup1_cnt na resposta anterior) - 12 cobre do reset ate o 1o
# mismatch real (ciclo 10) por completo, sem precisar adivinhar.


def _build_reference_windows(image: np.ndarray):
    """Identica a tb_python/test_window_3x3.py::_build_reference_windows -
    reutilizada de proposito, nao reimplementada, para nao introduzir uma
    2a fonte de verdade sobre o que e uma janela 'correta'."""
    h, w = image.shape
    padded = np.pad(image, 1, mode="constant", constant_values=0)
    windows = []
    for out_row in range(h - 1):  # window_3x3 nao cobre a borda inferior, ver ARQUITETURA_MULTICICLO.md 4.2
        for col in range(w):
            win = padded[out_row:out_row + 3, col:col + 3]
            windows.append(win.astype(int).tolist())
    return windows


def _unpack_window(raw: int):
    """Identica a tb_python/test_window_3x3.py::_unpack_window."""
    mask = (1 << DATA_WIDTH) - 1
    window = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
    for r in range(3):
        for c in range(3):
            k = 3 * r + c
            shift = (8 - k) * DATA_WIDTH
            window[r][c] = (raw >> shift) & mask
    return window


def _print_context(history, mismatch_idx, expected, got, cyc):
    print(f"\n=== MISMATCH na janela #{mismatch_idx} (ciclo {cyc}) ===")
    print(f"esperado: {expected}")
    print(f"obtido:   {got}")
    print(f"contexto (ultimos {len(history)} ciclos, incluindo este):")
    header = (
        "  cyc   i_valid i_pixel o_ready win_ready fsm_ready gate_ok accept consume lb_valid_in "
        "win_valid win_valid_real col_cnt phantom lb_warm1 lb_warmup1_cnt lb_line1 win_o_valid"
    )
    print(header)
    for h in history:
        print(
            f"  {h['cyc']:4d}  {h['i_valid']:7d} {h['i_pixel']:7d} {h['o_ready']:7d} "
            f"{h['win_ready']:9d} {h['fsm_ready']:9d} {h['gate_fsm_ok']:7d} "
            f"{h['accept_sample']:6d} {h['consume_sample']:7d} {h['lb_valid_in']:11d} "
            f"{h['win_valid']:9d} {h['win_valid_real']:14d} {h['col_cnt']:7d} "
            f"{h['phantom']:7d} {h['lb_warm1']:8d} {h['lb_warmup1_cnt']:15d} "
            f"{h['lb_line1']:8d} {h['win_o_valid']:11d}"
        )


@cocotb.test()
async def test_trace_row0_window_mismatch(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    # Mesma imagem/parametros de test_small_image_golden em
    # tb_python/test_sobel_multicycle.py - nao inventa um novo padrao.
    image = (np.arange(1, IMG_HEIGHT * IMG_WIDTH + 1) * 17 % 256).reshape(IMG_HEIGHT, IMG_WIDTH)
    expected_windows = _build_reference_windows(image)
    flat = image.flatten().tolist()

    idx = 0
    captured_windows = []
    history = []

    max_cycles = 50 * len(flat) + 2000
    cyc = 0
    while True:
        await ReadOnly()
        ready = int(dut.o_ready.value)
        w_valid = int(dut.win_valid.value)
        w_valid_real = int(dut.win_valid_real.value)
        col_cnt = int(dut.u_window.col_cnt_r.value)
        phantom = int(dut.u_window.phantom_pending_r.value)
        discard_cnt = int(dut.discard_cnt_r.value)
        warmup_done = int(dut.warmup_done_r.value)
        lb_curr = int(dut.u_line_buffer.o_curr.value)
        lb_line1 = int(dut.u_line_buffer.o_line1.value)
        lb_line2 = int(dut.u_line_buffer.o_line2.value)
        # ALTERADO AQUI: sinais internos de warm-up do estagio 1 do
        # line_buffer - para confirmar/refutar, com evidencia direta, se
        # o limiar de "aquecido" (WarmThresh=IMG_WIDTH+1, ver
        # ARQUITETURA_MULTICICLO.md 4.1) se comporta dentro de
        # sobel_multicycle exatamente como test_line_buffer_2line.py ja
        # validou no modulo isolado (o_line1 real a partir do pulso de
        # indice IMG_WIDTH, 0-based) ou se diverge por 1 pulso.
        lb_warm1 = int(dut.u_line_buffer.warm1.value)
        lb_warmup1_cnt = int(dut.u_line_buffer.warmup1_cnt_r.value)
        # ALTERADO AQUI: captura direta da cadeia de gating de
        # sobel_multicycle.sv - ate agora so inferimos indiretamente via
        # win_valid/o_ready. Evidencia do log anterior (lb_warmup1_cnt=3
        # apos o 4o pulso externo, esperado seria 4) aponta para 1 pulso
        # sendo descartado nesta cadeia - precisamos ver qual sinal
        # especifico (win_ready? fsm_ready? gate_fsm_ok?) cai para 0
        # exatamente no ciclo do pulso perdido.
        win_ready_s = int(dut.win_ready.value)
        fsm_ready_s = int(dut.fsm_ready.value)
        gate_fsm_ok_s = int(dut.gate_fsm_ok.value)
        accept_sample_s = int(dut.accept_sample.value)
        consume_sample_s = int(dut.consume_sample.value)
        lb_valid_in_s = int(dut.lb_valid_in.value)
        win_o_valid = int(dut.u_window.o_valid.value)
        win_window = _unpack_window(int(dut.u_window.o_window.value)) if win_o_valid else None
        cur_i_valid = int(dut.i_valid.value)
        cur_i_pixel = int(dut.i_pixel.value)
        await NextTimeStep()

        row = dict(
            cyc=cyc, i_valid=cur_i_valid, i_pixel=cur_i_pixel, o_ready=ready,
            win_valid=w_valid, win_valid_real=w_valid_real,
            col_cnt=col_cnt, phantom=phantom,
            discard_cnt=discard_cnt, warmup_done=warmup_done,
            lb_curr=lb_curr, lb_line1=lb_line1, lb_line2=lb_line2,
            lb_warm1=lb_warm1, lb_warmup1_cnt=lb_warmup1_cnt,
            win_ready=win_ready_s, fsm_ready=fsm_ready_s, gate_fsm_ok=gate_fsm_ok_s,
            accept_sample=accept_sample_s, consume_sample=consume_sample_s,
            lb_valid_in=lb_valid_in_s,
            win_o_valid=win_o_valid,
        )
        history.append(row)
        if len(history) > HIST_LEN:
            history.pop(0)

        if win_o_valid:
            raw_idx = len(captured_windows)
            captured_windows.append(win_window)
            # ALTERADO AQUI: descarta as primeiras IMG_WIDTH janelas RAW -
            # sao a "linha -1" virtual (top-border, zero-padding), o
            # MESMO deslocamento que test_window_3x3.py ja aplica
            # (`captured = captured[IMG_WIDTH:]`) e que warmup_done_r em
            # sobel_multicycle.sv existe para descartar. Comparar
            # captured_windows[0] direto com expected_windows[0] (como a
            # 1a versao deste script fazia) gera falsos positivos nessas
            # primeiras IMG_WIDTH janelas - nao e um bug do RTL, e erro
            # de alinhamento do proprio script de instrumentacao.
            real_idx = raw_idx - IMG_WIDTH
            if 0 <= real_idx < len(expected_windows):
                expected = expected_windows[real_idx]
                if win_window != expected:
                    _print_context(history, real_idx, expected, win_window, cyc)

        present_now = ready and idx < len(flat)
        dut.i_valid.value = 1 if present_now else 0
        dut.i_pixel.value = flat[idx] if present_now else 0
        if present_now:
            idx += 1

        await RisingEdge(dut.clk)
        cyc += 1
        if cyc > max_cycles:
            raise TimeoutError("simulacao excedeu o numero maximo de ciclos esperado")
        # ALTERADO AQUI: precisa capturar IMG_WIDTH janelas virtuais +
        # todas as reais esperadas, nao so len(expected_windows) - a
        # condicao antiga cortava a cauda de janelas reais (a 1a versao
        # deste script so capturou 10 janelas RAW quando precisava de
        # IMG_WIDTH+len(expected_windows)=4+8=12 para cobrir tudo).
        if idx >= len(flat) and len(captured_windows) >= len(expected_windows) + IMG_WIDTH:
            break

    dut.i_valid.value = 0

    # ALTERADO AQUI: mesmo deslocamento IMG_WIDTH aplicado na comparacao
    # durante o loop - real_windows sao as janelas RAW de indice
    # [IMG_WIDTH : IMG_WIDTH+len(expected_windows)], a fatia que de fato
    # corresponde as saidas geometricas reais (out_row 0..IMG_HEIGHT-2).
    real_windows = captured_windows[IMG_WIDTH:IMG_WIDTH + len(expected_windows)]
    n_mismatches = sum(1 for got, exp in zip(real_windows, expected_windows) if got != exp)
    print(
        f"\n=== RESUMO: {len(captured_windows)} janelas RAW capturadas "
        f"({IMG_WIDTH} descartadas como virtuais/'linha -1', mesma convencao de "
        f"test_window_3x3.py), {len(real_windows)} reais comparadas, "
        f"{len(expected_windows)} esperadas, {n_mismatches} divergentes ==="
    )
    assert n_mismatches == 0, (
        f"{n_mismatches}/{len(expected_windows)} janelas REAIS (pos-descarte de topo) de "
        f"window_3x3 divergem da referencia dentro de sobel_multicycle.sv - ver contexto acima"
    )


def test_trace_row0_window_mismatch_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_sobel_multicycle_trace")

    # ALTERADO AQUI: run_isolated (nao run() puro) - este arquivo agora
    # tem 2 corrotinas @cocotb.test(); sem isolar, esta chamada tambem
    # executaria test_confirm_rearm_skips_pulse_second_frame junto (ver
    # ARQUITETURA_MULTICICLO.md secao 4, "Quarta pegadinha").
    run_isolated(
        "test_trace_row0_window_mismatch",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "line_buffer_2line.sv"),
            os.path.join(proj_root, "rtl", "common", "window_3x3.sv"),
            os.path.join(proj_root, "rtl", "common", "abs_saturate.sv"),
            os.path.join(proj_root, "rtl", "common", "magnitude_l1.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "mac_unit.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "kernel_rom.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "mac_control_fsm.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "sobel_multicycle.sv"),
        ],
        includes=[os.path.join(proj_root, "include")],
        toplevel="sobel_multicycle",
        module="test_sobel_multicycle_trace",
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


# ---------------------------------------------------------------------
# ALTERADO AQUI: 2o teste, independente do primeiro - confirmacao da
# causa raiz "por outro angulo" (pedido explicito do usuario, ver
# CLAUDE.md 15.9 item 1: nunca propor a proxima correcao so por
# dedicao de codigo, sempre buscar evidencia real adicional antes).
#
# O 1o teste (acima) mostrou que warmup1_cnt_r nao incrementa no ciclo
# em que i_rearm=1 (1o pixel do frame) - hipotese: o if(i_rearm)/
# else-if(!warm1) em line_buffer_2line.sv sao mutuamente exclusivos,
# entao o pulso REAL que chega no mesmo ciclo do rearm nunca e contado.
#
# Mas no 1o frame, warmup1_cnt_r PARTE DE 0 (valor de reset) - um
# ceptico poderia argumentar que "nao incrementar nesse ciclo" e
# indistinguivel de coincidencia com o proprio reset (0 antes, 0
# depois, sem provar que um incremento foi de fato SUPRIMIDO).
#
# Este teste ataca o MESMO mecanismo por um angulo onde essa
# ambiguidade nao existe: alimenta 2 frames consecutivos e observa a
# fronteira frame1->frame2, onde warmup1_cnt_r chega JA SATURADO EM 5
# (fim do 1o frame) - uma queda ali so pode ser o reset via i_rearm,
# nunca coincidencia com reset de simulacao.
#
# ALTERADO AQUI (correcao de metodologia, apos 1a tentativa travar por
# timeout): a 1a versao deste teste tentava ler frame_start_pulse
# diretamente via ReadOnly() apos RisingEdge - mas frame_start_pulse
# (e i_rearm, que o recebe) e um FIO COMBINACIONAL derivado de
# feed_cnt_r=='0, nao um registrador. Ele so vale 1 ENQUANTO
# feed_cnt_r==0 - e feed_cnt_r muda NA MESMA borda que esse pulso
# deveria gatilhar. Por construcao, ele nunca e observavel via
# ReadOnly() DEPOIS da borda que afeta (ja mudou de valor no mesmo
# instante em que a borda acontece). Esse erro de timing (nao um
# defeito do RTL) fez rearm_events ficar em 0 o tempo todo, e o teste
# rodou ate o timeout esperando por um 3o frame que nunca existiria -
# confirmado pelo heartbeat de diagnostico (o DUT ficou corretamente
# parado em feed_cnt_r=0/o_ready=1, so aguardando um pixel que o driver
# nunca mais enviaria).
#
# Correcao: detectar o MESMO evento observando warmup1_cnt_r (um
# registrador de verdade, `_r`, mesma convencao de timing ja validada
# no 1o teste) em vez do fio. Em operacao normal, warmup1_cnt_r so pode
# ficar igual ou aumentar 1 por pulso - NUNCA diminuir. Qualquer QUEDA
# (valor menor que o da passagem anterior) so pode ser causada pelo
# reset sincrono via i_rearm - captura-la e captura-la o proprio rearm
# sem precisar ler o fio combinacional.
@cocotb.test()
async def test_confirm_rearm_skips_pulse_second_frame(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    image1 = (np.arange(1, IMG_HEIGHT * IMG_WIDTH + 1) * 17 % 256).reshape(IMG_HEIGHT, IMG_WIDTH)
    image2 = (np.arange(50, 50 + IMG_HEIGHT * IMG_WIDTH) * 23 % 256).reshape(IMG_HEIGHT, IMG_WIDTH)
    flat = image1.flatten().tolist() + image2.flatten().tolist()

    idx = 0
    cyc = 0
    max_cycles = 50 * len(flat) + 2000
    prev_warmup1_cnt = 0
    drop_events = []

    while True:
        await ReadOnly()
        ready = int(dut.o_ready.value)
        cur_i_valid = int(dut.i_valid.value)
        cur_i_pixel = int(dut.i_pixel.value)
        warmup1_cnt = int(dut.u_line_buffer.warmup1_cnt_r.value)
        await NextTimeStep()

        if warmup1_cnt < prev_warmup1_cnt:
            drop_events.append(dict(
                cyc=cyc, i_valid=cur_i_valid, i_pixel=cur_i_pixel,
                before=prev_warmup1_cnt, after=warmup1_cnt,
            ))

        prev_warmup1_cnt = warmup1_cnt

        present_now = ready and idx < len(flat)
        dut.i_valid.value = 1 if present_now else 0
        dut.i_pixel.value = flat[idx] if present_now else 0
        if present_now:
            idx += 1

        await RisingEdge(dut.clk)
        cyc += 1
        if cyc > max_cycles:
            raise TimeoutError("simulacao excedeu o numero maximo de ciclos esperado")
        # ALTERADO AQUI: com a deteccao corrigida (baseada em registrador),
        # 1 unico evento de queda ja e suficiente - nao precisamos mais
        # de 2, e nao precisamos mais esperar idx esgotar.
        if len(drop_events) >= 1:
            break

    dut.i_valid.value = 0

    print(f"\n=== EVENTOS DE QUEDA em warmup1_cnt_r capturados: {len(drop_events)} ===")
    for i, ev in enumerate(drop_events):
        print(
            f"  queda #{i} no ciclo {ev['cyc']}: warmup1_cnt_r {ev['before']} -> {ev['after']} "
            f"(i_valid deste ciclo={ev['i_valid']}, i_pixel={ev['i_pixel']})"
        )

    assert len(drop_events) >= 1, (
        f"esperava >=1 queda em warmup1_cnt_r (fronteira frame1->frame2), obtive "
        f"{len(drop_events)} - a fronteira de frame pode nao ter sido alcancada"
    )

    ev = drop_events[0]
    assert ev["before"] == 5, (
        f"esperava warmup1_cnt_r=5 (saturado, fim do frame 1, WarmThresh=IMG_WIDTH+1) "
        f"imediatamente antes da queda, obtido={ev['before']} - premissa do teste nao "
        f"se sustenta, resultado abaixo nao e conclusivo"
    )
    print(
        f"\n=== CONFIRMACAO (angulo independente do 1o teste): na fronteira "
        f"frame1->frame2 (ciclo {ev['cyc']}), warmup1_cnt_r caiu de {ev['before']} "
        f"(saturado, NAO e valor de reset) para {ev['after']}, no MESMO ciclo em que "
        f"i_valid={ev['i_valid']} (i_pixel={ev['i_pixel']}). Se o pulso real deste ciclo "
        f"tivesse sido contado junto com o rearm, warmup1_cnt_r depois seria 1 (0 do "
        f"rearm + 1 do incremento) quando i_valid=1; ficar em 0 confirma que o "
        f"if/else-if mutuamente exclusivo em line_buffer_2line.sv descarta esse pulso. ==="
    )
    if ev["i_valid"] == 1:
        assert ev["after"] == 0, (
            f"warmup1_cnt_r apos a queda = {ev['after']} com i_valid=1 no mesmo ciclo "
            f"(a hipotese previa 0); se saiu 1, a causa raiz proposta esta ERRADA - o "
            f"pulso FOI contado normalmente mesmo com i_rearm ativo - descartar a "
            f"hipotese e reabrir a investigacao"
        )
    else:
        print(
            "AVISO: i_valid=0 no ciclo exato da queda - a hipotese especifica "
            "('o pulso do proprio ciclo do rearm e descartado') nao pode ser testada "
            "diretamente neste evento; o mecanismo de reset foi confirmado, mas a "
            "coincidencia com um pulso real precisa de outra captura."
        )


def test_confirm_rearm_skips_pulse_second_frame_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_sobel_multicycle_trace_rearm")

    run_isolated(
        "test_confirm_rearm_skips_pulse_second_frame",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "line_buffer_2line.sv"),
            os.path.join(proj_root, "rtl", "common", "window_3x3.sv"),
            os.path.join(proj_root, "rtl", "common", "abs_saturate.sv"),
            os.path.join(proj_root, "rtl", "common", "magnitude_l1.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "mac_unit.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "kernel_rom.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "mac_control_fsm.sv"),
            os.path.join(proj_root, "rtl", "multicycle", "sobel_multicycle.sv"),
        ],
        includes=[os.path.join(proj_root, "include")],
        toplevel="sobel_multicycle",
        module="test_sobel_multicycle_trace",
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
    test_trace_row0_window_mismatch_runner()
    test_confirm_rearm_skips_pulse_second_frame_runner()

# ---------------------------------------------------------------------
# COMO RODAR (nao faz parte da suite normal - rodar ISOLADO, com -s para
# ver os prints, que o pytest esconde por padrao):
#
#   cd tb_python
#   python3 -m pytest test_sobel_multicycle_trace.py -v -s
#
# Isso roda os 2 testes deste arquivo:
#   1. test_trace_row0_window_mismatch_runner - localiza a divergencia
#      (janela por janela, 1 frame).
#   2. test_confirm_rearm_skips_pulse_second_frame_runner - confirma a
#      causa raiz por um angulo independente (queda em warmup1_cnt_r na
#      fronteira frame1->frame2, onde ele ja esta saturado em 5, nao em
#      0 por reset - elimina a ambiguidade de coincidencia com reset).
#
# Cole de volta APENAS:
#   1. Todo bloco "=== MISMATCH ... ===" do 1o teste, se aparecer.
#   2. A linha "=== RESUMO: ... ===" do 1o teste.
#   3. O bloco "=== EVENTOS DE QUEDA ... ===" e o bloco
#      "=== CONFIRMACAO ... ===" do 2o teste, se aparecerem.
#   4. Se o 2o teste passar (assert nao disparar), isso TAMBEM e um
#      resultado real a colar - diga que passou; nao precisa do log
#      inteiro do pytest em nenhum dos dois casos.
# ---------------------------------------------------------------------