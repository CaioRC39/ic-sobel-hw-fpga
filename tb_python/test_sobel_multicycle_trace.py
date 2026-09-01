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
            os.path.join(proj_root, "rtl", "multicycle", "skid_fifo2.sv"),
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

# ---------------------------------------------------------------------
# ALTERADO AQUI: instrumentacao nova, motivada pela evidencia de
# len(collected)=14 (esperado 12) no frame 3/4 de test_four_consecutive_frames
# apos aplicar Alternativa A + B1 - conta win_valid vs win_valid_real POR
# FRAME, para distinguir se ha janelas extras sendo aceitas (nao so
# conteudo errado numa janela existente). Ver CLAUDE.md 15.9/15.11 -
# evidencia real antes de qualquer novo diff em RTL.
# ---------------------------------------------------------------------
@cocotb.test()
async def test_trace_frame3_pulse_accounting(dut):
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

    for frame_idx, image in enumerate(images):
        flat = image.flatten().tolist()
        idx = 0
        win_valid_count = 0
        win_valid_real_count = 0
        events = []
        cyc = 0
        max_cycles = 50 * len(flat) + 2000
        collected_this_frame = 0
        target = IMG_WIDTH * IMG_HEIGHT
        while True:
            await ReadOnly()
            ready = int(dut.o_ready.value)
            w_valid = int(dut.win_valid.value)
            w_valid_real = int(dut.win_valid_real.value)
            warmup_done = int(dut.warmup_done_r.value)
            geom = int(dut.u_window.o_window_valid_geom.value) if w_valid else None
            out_valid = int(dut.o_valid.value)
            await NextTimeStep()

            if w_valid:
                win_valid_count += 1
                if w_valid_real:
                    win_valid_real_count += 1
                events.append((cyc, w_valid_real, warmup_done, geom))

            if out_valid:
                collected_this_frame += 1

            present_now = ready and idx < len(flat)
            dut.i_valid.value = 1 if present_now else 0
            dut.i_pixel.value = flat[idx] if present_now else 0
            if present_now:
                idx += 1

            await RisingEdge(dut.clk)
            cyc += 1
            if cyc > max_cycles:
                raise TimeoutError("timeout")
            if idx >= len(flat) and collected_this_frame >= target:
                break

        print(f"\n=== FRAME {frame_idx+1}/4: win_valid={win_valid_count} "
              f"win_valid_real={win_valid_real_count} collected={collected_this_frame} "
              f"(esperado={target}) ===")
        if win_valid_real_count != target:
            for (c, vr, wd, g) in events:
                print(f"  cyc={c} win_valid_real={vr} warmup_done_r={wd} geom={g}")


def test_trace_frame3_pulse_accounting_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_sobel_multicycle_trace_pulse")

    run_isolated(
        "test_trace_frame3_pulse_accounting",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "line_buffer_2line.sv"),
            os.path.join(proj_root, "rtl", "common", "window_3x3.sv"),
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
# ALTERADO AQUI: 2a rodada de instrumentacao, motivada pela evidencia de
# win_valid CRESCENTE por frame (12,12,14,16) apos Alternativa A + B1 -
# testa diretamente a hipotese de que window_3x3.col_cnt_r desalinha da
# fronteira real de linha entre frames (o modulo nao tem nocao de frame
# por design, ver ARQUITETURA_MULTICICLO.md 4.2). Loga col_cnt_r/
# phantom_pending_r exatamente no ciclo de frame_start_pulse de cada
# fronteira (1->2, 2->3, 3->4) - se col_cnt_r != 0 ali, confirma desync
# carregado do frame anterior.
# ---------------------------------------------------------------------
@cocotb.test()
async def test_trace_col_cnt_at_frame_boundaries(dut):
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

    cyc = 0
    max_cycles = 50 * sum(im.size for im in images) + 5000
    for frame_idx, image in enumerate(images):
        flat = image.flatten().tolist()
        idx = 0
        target = IMG_WIDTH * IMG_HEIGHT
        collected_this_frame = 0
        while True:
            await ReadOnly()
            ready = int(dut.o_ready.value)
            out_valid = int(dut.o_valid.value)
            fsp = int(dut.frame_start_pulse.value)
            col_cnt = int(dut.u_window.col_cnt_r.value)
            phantom = int(dut.u_window.phantom_pending_r.value)
            await NextTimeStep()

            if fsp:
                print(f"  [frame {frame_idx+1} inicio] cyc={cyc} col_cnt_r={col_cnt} "
                      f"phantom_pending_r={phantom}")

            if out_valid:
                collected_this_frame += 1

            present_now = ready and idx < len(flat)
            dut.i_valid.value = 1 if present_now else 0
            dut.i_pixel.value = flat[idx] if present_now else 0
            if present_now:
                idx += 1

            await RisingEdge(dut.clk)
            cyc += 1
            if cyc > max_cycles:
                raise TimeoutError("timeout")
            if idx >= len(flat) and collected_this_frame >= target:
                # Loga tambem o ESTADO FINAL de col_cnt_r ao fim do frame
                print(f"  [frame {frame_idx+1} fim]    cyc={cyc} col_cnt_r={col_cnt} "
                      f"phantom_pending_r={phantom} collected={collected_this_frame}")
                break


def test_trace_col_cnt_at_frame_boundaries_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_sobel_multicycle_trace_colcnt")

    run_isolated(
        "test_trace_col_cnt_at_frame_boundaries",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "line_buffer_2line.sv"),
            os.path.join(proj_root, "rtl", "common", "window_3x3.sv"),
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
            os.path.join(proj_root, "rtl", "multicycle", "skid_fifo2.sv"),
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

@cocotb.test()
async def test_trace_true_frame_boundary(dut):
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
    flat1 = image1.flatten().tolist()
    flat2 = image2.flatten().tolist()

    target = IMG_WIDTH * IMG_HEIGHT
    HIST, POST = 15, 20

    history = []
    printing_left = 0
    prev_frame_tag = 0
    toggle_count = 0

    idx1 = idx2 = 0
    feeding_frame2 = False
    collected1 = collected2 = 0

    cyc = 0
    max_cycles = 50 * (len(flat1) + len(flat2)) + 3000

    def fmt(h):
        return (f"  {h['cyc']:4d} {h['i_valid']:7d} {h['i_pixel']:7d} {h['ready']:5d} "
                f"{h['feed_cnt']:8d} {h['in_real']:7d} {h['accept']:6d} {h['consume']:7d} "
                f"{h['lb_vin']:6d} {h['w_valid']:7d} {h['w_valid_real']:13d} "
                f"{h['warmup_done']:11d} {h['col_cnt']:7d} {h['phantom']:7d} "
                f"{str(h['geom']):4s} {h['frame_tag']:9d} {h['out_valid']:8d} "
                f"{str(h['out_pixel']):8s}")

    while True:
        await ReadOnly()
        ready = int(dut.o_ready.value)
        out_valid = int(dut.o_valid.value)
        out_pixel = int(dut.o_pixel.value) if out_valid else None
        feed_cnt = int(dut.feed_cnt_r.value)
        in_real = int(dut.in_real_region.value)
        accept = int(dut.accept_sample.value)
        consume = int(dut.consume_sample.value)
        lb_vin = int(dut.lb_valid_in.value)
        w_valid = int(dut.win_valid.value)
        w_valid_real = int(dut.win_valid_real.value)
        warmup_done = int(dut.warmup_done_r.value)
        col_cnt = int(dut.u_window.col_cnt_r.value)
        phantom = int(dut.u_window.phantom_pending_r.value)
        geom = int(dut.u_window.o_window_valid_geom.value) if w_valid else None
        frame_tag = int(dut.frame_tag_r.value)
        cur_i_valid = int(dut.i_valid.value)
        cur_i_pixel = int(dut.i_pixel.value)
        await NextTimeStep()

        row = dict(cyc=cyc, i_valid=cur_i_valid, i_pixel=cur_i_pixel, ready=ready,
                    feed_cnt=feed_cnt, in_real=in_real, accept=accept, consume=consume,
                    lb_vin=lb_vin, w_valid=w_valid, w_valid_real=w_valid_real,
                    warmup_done=warmup_done, col_cnt=col_cnt, phantom=phantom, geom=geom,
                    frame_tag=frame_tag, out_valid=out_valid, out_pixel=out_pixel)
        history.append(row)
        if len(history) > HIST:
            history.pop(0)

        toggled = (frame_tag != prev_frame_tag)
        prev_frame_tag = frame_tag
        if toggled:
            toggle_count += 1
            print(f"\n=== TOGGLE #{toggle_count} de frame_tag_r no ciclo {cyc} "
                  f"(novo valor={frame_tag}) ===")
            print("  cyc i_valid i_pixel ready feed_cnt in_real accept consume lb_vin "
                  "w_valid w_valid_real warmup_done col_cnt phantom geom frame_tag out_valid out_pixel")
            for h in history:
                print(fmt(h))
            printing_left = POST
        elif printing_left > 0:
            print(fmt(row))
            printing_left -= 1

        if out_valid:
            if not feeding_frame2:
                collected1 += 1
            else:
                collected2 += 1

        if not feeding_frame2:
            present_now = ready and idx1 < len(flat1)
            dut.i_valid.value = 1 if present_now else 0
            dut.i_pixel.value = flat1[idx1] if present_now else 0
            if present_now:
                idx1 += 1
            if idx1 >= len(flat1) and collected1 >= target:
                feeding_frame2 = True
        else:
            present_now = ready and idx2 < len(flat2)
            dut.i_valid.value = 1 if present_now else 0
            dut.i_pixel.value = flat2[idx2] if present_now else 0
            if present_now:
                idx2 += 1

        await RisingEdge(dut.clk)
        cyc += 1
        if cyc > max_cycles:
            raise TimeoutError("timeout")
        if feeding_frame2 and idx2 >= len(flat2) and collected2 >= target:
            break

    dut.i_valid.value = 0
    print(f"\n=== RESUMO: collected1={collected1} collected2={collected2} "
          f"toggles_de_frame_tag_r={toggle_count} ===")


def test_trace_true_frame_boundary_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_sobel_multicycle_trace_boundary")

    run_isolated(
        "test_trace_true_frame_boundary",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "line_buffer_2line.sv"),
            os.path.join(proj_root, "rtl", "common", "window_3x3.sv"),
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
        module="test_sobel_multicycle_trace",
        parameters={
            "DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH, "IMG_HEIGHT": IMG_HEIGHT,
            "COEFF_WIDTH": COEFF_WIDTH, "ACC_WIDTH": ACC_WIDTH,
        },
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


@cocotb.test()
async def test_trace_all_boundaries_4frames(dut):
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
    flats = [im.flatten().tolist() for im in images]
    target = IMG_WIDTH * IMG_HEIGHT

    HIST, POST = 15, 25
    history = []
    printing_left = 0
    prev_frame_tag = 0
    toggle_count = 0

    frame_idx = 0
    idx = 0
    collected_this_frame = 0
    per_frame_collected = []
    per_frame_win_valid = [0, 0, 0, 0]
    per_frame_win_valid_real = [0, 0, 0, 0]

    cyc = 0
    max_cycles = 50 * sum(len(f) for f in flats) + 5000

    def fmt(h):
        return (f"  {h['cyc']:4d} {h['i_valid']:7d} {h['i_pixel']:7d} {h['ready']:5d} "
                f"{h['feed_cnt']:8d} {h['in_real']:7d} {h['accept']:6d} {h['consume']:7d} "
                f"{h['lb_vin']:6d} {h['lb_win_ivalid']:9d} {h['w_valid']:7d} "
                f"{h['w_valid_real']:13d} {h['warmup_done']:11d} {h['col_cnt']:7d} "
                f"{h['phantom']:7d} {str(h['geom']):4s} {h['frame_tag']:9d} "
                f"{h['out_valid']:8d} {str(h['out_pixel']):8s} {h['fidx']:4d}")

    while True:
        await ReadOnly()
        ready = int(dut.o_ready.value)
        out_valid = int(dut.o_valid.value)
        out_pixel = int(dut.o_pixel.value) if out_valid else None
        feed_cnt = int(dut.feed_cnt_r.value)
        in_real = int(dut.in_real_region.value)
        accept = int(dut.accept_sample.value)
        consume = int(dut.consume_sample.value)
        lb_vin = int(dut.lb_valid_in.value)
        lb_win_ivalid = int(dut.u_window.i_valid.value)
        w_valid = int(dut.win_valid.value)
        w_valid_real = int(dut.win_valid_real.value)
        warmup_done = int(dut.warmup_done_r.value)
        col_cnt = int(dut.u_window.col_cnt_r.value)
        phantom = int(dut.u_window.phantom_pending_r.value)
        geom = int(dut.u_window.o_window_valid_geom.value) if w_valid else None
        frame_tag = int(dut.frame_tag_r.value)
        cur_i_valid = int(dut.i_valid.value)
        cur_i_pixel = int(dut.i_pixel.value)
        await NextTimeStep()

        if w_valid:
            per_frame_win_valid[frame_idx] += 1
        if w_valid_real:
            per_frame_win_valid_real[frame_idx] += 1

        row = dict(cyc=cyc, i_valid=cur_i_valid, i_pixel=cur_i_pixel, ready=ready,
                    feed_cnt=feed_cnt, in_real=in_real, accept=accept, consume=consume,
                    lb_vin=lb_vin, lb_win_ivalid=lb_win_ivalid, w_valid=w_valid,
                    w_valid_real=w_valid_real, warmup_done=warmup_done, col_cnt=col_cnt,
                    phantom=phantom, geom=geom, frame_tag=frame_tag, out_valid=out_valid,
                    out_pixel=out_pixel, fidx=frame_idx)
        history.append(row)
        if len(history) > HIST:
            history.pop(0)

        toggled = (frame_tag != prev_frame_tag)
        prev_frame_tag = frame_tag
        if toggled:
            toggle_count += 1
            print(f"\n=== TOGGLE #{toggle_count} de frame_tag_r no ciclo {cyc} "
                  f"(novo valor={frame_tag}) — fronteira frame {frame_idx+1}->{frame_idx+2} ===")
            print("  cyc i_valid i_pixel ready feed_cnt in_real accept consume lb_vin "
                  "win_ivalid w_valid w_valid_real warmup_done col_cnt phantom geom "
                  "frame_tag out_valid out_pixel fidx")
            for h in history:
                print(fmt(h))
            printing_left = POST
        elif printing_left > 0:
            print(fmt(row))
            printing_left -= 1

        if out_valid:
            collected_this_frame += 1

        flat = flats[frame_idx]
        present_now = ready and idx < len(flat)
        dut.i_valid.value = 1 if present_now else 0
        dut.i_pixel.value = flat[idx] if present_now else 0
        if present_now:
            idx += 1

        await RisingEdge(dut.clk)
        cyc += 1
        if cyc > max_cycles:
            raise TimeoutError("timeout")

        if idx >= len(flat) and collected_this_frame >= target:
            per_frame_collected.append(collected_this_frame)
            frame_idx += 1
            idx = 0
            collected_this_frame = 0
            if frame_idx >= len(flats):
                break

    dut.i_valid.value = 0
    print(f"\n=== RESUMO GERAL ===")
    for i in range(4):
        print(f"  frame {i+1}: win_valid={per_frame_win_valid[i]} "
              f"win_valid_real={per_frame_win_valid_real[i]} "
              f"collected={per_frame_collected[i]} (esperado={target})")
    print(f"  total toggles de frame_tag_r={toggle_count}")


def test_trace_all_boundaries_4frames_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_sobel_multicycle_trace_all")

    run_isolated(
        "test_trace_all_boundaries_4frames",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "line_buffer_2line.sv"),
            os.path.join(proj_root, "rtl", "common", "window_3x3.sv"),
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
        module="test_sobel_multicycle_trace",
        parameters={
            "DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH, "IMG_HEIGHT": IMG_HEIGHT,
            "COEFF_WIDTH": COEFF_WIDTH, "ACC_WIDTH": ACC_WIDTH,
        },
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )


def _build_reference_windows_continuous(rows_2d: np.ndarray):
    """Mesma logica de _build_reference_windows (test_window_3x3.py),
    mas aplicada ao stream CONTINUO de todas as linhas (reais+padding)
    de todos os frames concatenadas verticalmente, sem nenhum reset de
    padding nas fronteiras internas de frame - exatamente o que
    window_3x3.sv realmente enxerga (nao tem nocao de frame)."""
    h, w = rows_2d.shape
    padded = np.pad(rows_2d, 1, mode="constant", constant_values=0)
    windows = []
    for out_row in range(h - 1):
        for col in range(w):
            win = padded[out_row:out_row + 3, col:col + 3]
            windows.append(win.astype(int).tolist())
    return windows


def _unpack_window_local(raw: int, data_width: int):
    mask = (1 << data_width) - 1
    window = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
    for r in range(3):
        for c in range(3):
            k = 3 * r + c
            shift = (8 - k) * data_width
            window[r][c] = (raw >> shift) & mask
    return window


@cocotb.test()
async def test_continuous_stream_vs_window3x3_reference(dut):
    """Testa window_3x3 (via o pipeline completo de sobel_multicycle)
    contra uma referencia que trata os 4 frames como 1 UNICO stream
    continuo de linhas (reais + padding de borda inferior), SEM
    nenhuma nocao de fronteira de frame - exatamente o modelo mental
    correto de window_3x3.sv, que de fato nao conhece frames. Se as
    janelas RAW baterem 100% com esta referencia, o bug NAO esta em
    window_3x3/line_buffer_2line - esta na forma como o teste original
    (test_four_consecutive_frames/_feed_image_and_collect) atribui
    pulsos de saida a frames, nao no RTL."""
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

    # Constroi o stream CONTINUO real fisicamente aceito por window_3x3:
    # cada frame contribui IMG_HEIGHT linhas reais + 1 linha de padding
    # (zeros) da borda inferior - concatenadas, SEM reset entre frames
    # (mesma logica de sobel_multicycle.sv: RealTotal/PaddedTotal).
    padding_row = np.zeros((1, IMG_WIDTH), dtype=int)
    continuous_rows = np.vstack([np.vstack([im, padding_row]) for im in images])
    expected_windows_full = _build_reference_windows_continuous(continuous_rows)
    # Descarta a 1a "linha -1" virtual (fill global, 1x na vida do modulo,
    # mesma convencao ja usada em todo o projeto).
    expected_windows_real = expected_windows_full[IMG_WIDTH:]

    # Fluxo de pixels REAL fisicamente enviado ao DUT: concatenacao dos
    # 4 flats (sobel_multicycle gera o padding internamente, entao so
    # mandamos os pixels REAIS - RealTotal por frame).
    flat_all = []
    for im in images:
        flat_all.extend(im.flatten().tolist())

    idx = 0
    captured_windows = []
    cyc = 0
    max_cycles = 50 * len(flat_all) + 5000
    target_total = len(expected_windows_real)

    while True:
        await ReadOnly()
        ready = int(dut.o_ready.value)
        w_valid = int(dut.win_valid.value)
        w_valid_real = int(dut.win_valid_real.value)
        win_window = (_unpack_window_local(int(dut.u_window.o_window.value), DATA_WIDTH)
                      if w_valid else None)
        await NextTimeStep()

        if w_valid:
            captured_windows.append((cyc, win_window, w_valid_real))

        present_now = ready and idx < len(flat_all)
        dut.i_valid.value = 1 if present_now else 0
        dut.i_pixel.value = flat_all[idx] if present_now else 0
        if present_now:
            idx += 1

        await RisingEdge(dut.clk)
        cyc += 1
        if cyc > max_cycles:
            raise TimeoutError("timeout")
        if idx >= len(flat_all) and len(captured_windows) >= len(expected_windows_full):
            break

    dut.i_valid.value = 0

    # Descarta a 1a linha virtual das CAPTURADAS tambem (mesmo IMG_WIDTH
    # pulsos), alinhando com expected_windows_real.
    real_captured = captured_windows[IMG_WIDTH:IMG_WIDTH + target_total]

    n_mismatches = 0
    for i, ((c, got, vreal), exp) in enumerate(zip(real_captured, expected_windows_real)):
        if got != exp:
            n_mismatches += 1
            if n_mismatches <= 10:
                print(f"  MISMATCH idx={i} cyc={c} win_valid_real={vreal} "
                      f"obtido={got} esperado={exp}")

    print(f"\n=== RESUMO STREAM CONTINUO: raw_capturado={len(captured_windows)} "
          f"raw_esperado={len(expected_windows_full)} "
          f"reais_comparados={len(real_captured)} reais_esperados={target_total} "
          f"mismatches_de_conteudo={n_mismatches} ===")

    assert len(captured_windows) == len(expected_windows_full), (
        f"CONTAGEM de pulsos brutos diverge: window_3x3 emitiu "
        f"{len(captured_windows)}, esperado (stream continuo, sem "
        f"nocao de frame) {len(expected_windows_full)} - isso indica "
        f"defeito real em window_3x3/line_buffer_2line, nao em "
        f"atribuicao de teste"
    )
    assert n_mismatches == 0, (
        f"{n_mismatches} janelas com CONTEUDO errado (contagem bate, "
        f"mas dado errado) - ver linhas MISMATCH acima"
    )


def test_continuous_stream_vs_window3x3_reference_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_sobel_multicycle_continuous")

    run_isolated(
        "test_continuous_stream_vs_window3x3_reference",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "line_buffer_2line.sv"),
            os.path.join(proj_root, "rtl", "common", "window_3x3.sv"),
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
        module="test_sobel_multicycle_trace",
        parameters={
            "DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH, "IMG_HEIGHT": IMG_HEIGHT,
            "COEFF_WIDTH": COEFF_WIDTH, "ACC_WIDTH": ACC_WIDTH,
        },
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )

# tb_python/test_sobel_multicycle_trace.py — adicionar ao final, antes do "if __name__"

@cocotb.test()
async def test_trace_line_buffer_inputs_to_window(dut):
    """Verifica DIRETAMENTE lb_curr/lb_line1/lb_line2 (saidas de
    line_buffer_2line, entradas de window_3x3) contra os valores REAIS
    esperados da imagem, pulso a pulso - sem reconstrucao de janela.
    Isola se a corrupcao esta em line_buffer_2line (dado errado entregue)
    ou em window_3x3 (dado certo, montagem errada). Motivado por
    mismatches_de_conteudo=56/56 desde idx=0 (frame 1, ciclo 10, muito
    antes de qualquer rearm) - reconecta com o bug ja documentado em
    RESUMO_ESTADO_PROJETO.md ('i_line1 sistematicamente atrasada/errada
    em row0, mascarado por saturacao')."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    image = (np.arange(1, IMG_HEIGHT * IMG_WIDTH + 1) * 17 % 256).reshape(IMG_HEIGHT, IMG_WIDTH)
    flat = image.flatten().tolist()
    padded_ref = np.pad(image, 1, mode="constant", constant_values=0).astype(int)

    idx = 0
    pulse_count = 0
    MAX_PULSES = 25
    cyc = 0
    max_cycles = 2000
    lines = []

    while pulse_count < MAX_PULSES and cyc < max_cycles:
        await ReadOnly()
        ready = int(dut.o_ready.value)
        lb_valid = int(dut.lb_valid_in.value)
        lb_curr = int(dut.u_line_buffer.o_curr.value) if lb_valid else None
        lb_line1 = int(dut.u_line_buffer.o_line1.value) if lb_valid else None
        lb_line2 = int(dut.u_line_buffer.o_line2.value) if lb_valid else None
        cur_i_pixel = int(dut.i_pixel.value)
        cur_i_valid = int(dut.i_valid.value)
        await NextTimeStep()

        if lb_valid:
            # A qual pixel real da imagem este pulso corresponde? idx-1
            # (ja incrementado no ciclo anterior de i_valid=1) menos 1,
            # pois consume_sample/lb_valid_in reflete o pixel que ACABOU
            # de ser aceito (mesmo ciclo de i_valid=1 -> consumido).
            src_idx = pulse_count  # pulso N corresponde ao pixel N (0-indexed), 1:1 com lb_valid
            src_row, src_col = divmod(src_idx, IMG_WIDTH)
            exp_curr = flat[src_idx] if src_idx < len(flat) else None
            exp_line1 = int(padded_ref[src_row, src_col + 1]) if src_row >= 1 else 0
            exp_line2 = int(padded_ref[src_row - 1, src_col + 1]) if src_row >= 2 else 0
            match = (lb_curr == exp_curr and lb_line1 == exp_line1 and lb_line2 == exp_line2)
            lines.append(
                f"  pulse={pulse_count:2d} cyc={cyc:4d} (linha={src_row},col={src_col}) "
                f"lb_curr={lb_curr} lb_line1={lb_line1} lb_line2={lb_line2}  |  "
                f"esperado: curr={exp_curr} line1={exp_line1} line2={exp_line2}  "
                f"{'OK' if match else '<<< MISMATCH'}"
            )
            pulse_count += 1

        present_now = ready and idx < len(flat)
        dut.i_valid.value = 1 if present_now else 0
        dut.i_pixel.value = flat[idx] if present_now else 0
        if present_now:
            idx += 1

        await RisingEdge(dut.clk)
        cyc += 1

    dut.i_valid.value = 0
    print(f"\n=== lb_curr/lb_line1/lb_line2 nos primeiros {pulse_count} pulsos (frame 1) ===")
    for l in lines:
        print(l)


def test_trace_line_buffer_inputs_to_window_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_sobel_multicycle_trace_lb")

    run_isolated(
        "test_trace_line_buffer_inputs_to_window",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "line_buffer_2line.sv"),
            os.path.join(proj_root, "rtl", "common", "window_3x3.sv"),
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
        module="test_sobel_multicycle_trace",
        parameters={
            "DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH, "IMG_HEIGHT": IMG_HEIGHT,
            "COEFF_WIDTH": COEFF_WIDTH, "ACC_WIDTH": ACC_WIDTH,
        },
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )

import sys
sys.path.insert(0, os.path.dirname(__file__))
from test_sobel_multicycle import _feed_image_and_collect  # ALTERADO AQUI: reuso, nao duplicacao


@cocotb.test()
async def test_trace_via_validated_feeder(dut):
    """Mesma logica de captura de lb_curr/lb_line1/lb_line2, mas via
    callback dentro do laço JA VALIDADO (_feed_image_and_collect) - nao
    um laço de estimulo paralelo. Elimina a suspeita de bug na propria
    instrumentacao (ver analise desta sessao: pulse=1 mostrando
    flat[4] em vez de flat[1], incompativel com test_small_image_golden
    passar para o mesmo frame)."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    image = (np.arange(1, IMG_HEIGHT * IMG_WIDTH + 1) * 17 % 256).reshape(IMG_HEIGHT, IMG_WIDTH)
    padded_ref = np.pad(image, 1, mode="constant", constant_values=0).astype(int)
    lines = []
    pulse_holder = {"count": 0}

    def _on_cycle(dut_, cyc, idx):
        lb_valid = int(dut_.lb_valid_in.value)
        if lb_valid and pulse_holder["count"] < 25:
            lb_curr = int(dut_.u_line_buffer.o_curr.value)
            lb_line1 = int(dut_.u_line_buffer.o_line1.value)
            lb_line2 = int(dut_.u_line_buffer.o_line2.value)
            p = pulse_holder["count"]
            src_row, src_col = divmod(p, IMG_WIDTH)
            exp_curr = int(padded_ref[src_row + 1, src_col + 1])
            exp_line1 = int(padded_ref[src_row, src_col + 1]) if src_row >= 1 else 0
            exp_line2 = int(padded_ref[src_row - 1, src_col + 1]) if src_row >= 2 else 0
            match = (lb_curr == exp_curr and lb_line1 == exp_line1 and lb_line2 == exp_line2)
            lines.append(
                f"  pulse={p:2d} cyc={cyc:4d} idx_no_momento={idx:2d} "
                f"(linha={src_row},col={src_col}) lb_curr={lb_curr} "
                f"lb_line1={lb_line1} lb_line2={lb_line2}  |  esperado: "
                f"curr={exp_curr} line1={exp_line1} line2={exp_line2}  "
                f"{'OK' if match else '<<< MISMATCH'}"
            )
            pulse_holder["count"] += 1

    collected = await _feed_image_and_collect(dut, image, stall_prob=0.0, on_cycle=_on_cycle)

    print(f"\n=== VIA LACO VALIDADO: {len(lines)} pulsos capturados, "
          f"collected={collected} ===")
    for l in lines:
        print(l)


def test_trace_via_validated_feeder_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_sobel_multicycle_trace_validated")

    run_isolated(
        "test_trace_via_validated_feeder",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "line_buffer_2line.sv"),
            os.path.join(proj_root, "rtl", "common", "window_3x3.sv"),
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
        module="test_sobel_multicycle_trace",
        parameters={
            "DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH, "IMG_HEIGHT": IMG_HEIGHT,
            "COEFF_WIDTH": COEFF_WIDTH, "ACC_WIDTH": ACC_WIDTH,
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