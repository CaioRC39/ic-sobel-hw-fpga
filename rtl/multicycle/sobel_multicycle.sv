`include "timescale.svh"

// ALTERADO AQUI (correcao do Achado F-16, Alternativa 1 completa -
// Metade 1 em line_buffer_2line.sv + Metade 2 = line_window_skid.sv
// novo, instanciado abaixo entre u_line_buffer e u_window):
//
// *** ESTE ARQUIVO E UM RASCUNHO DE INTEGRACAO, NAO SIMULADO COMO UM
// TODO NESTA FORMA EXATA. *** A logica de line_buffer_2line.sv e de
// line_window_skid.sv foi validada exaustivamente (conteudo, handshake,
// fronteira de frame) num wrapper simplificado de 3 modulos, em
// ambiente de reproducao isolado - mas NUNCA dentro deste arquivo
// completo, com toda a logica de discard_cnt_r/warmup_done_r/
// gate_fsm_ok/frame_tag_r junto, nem com uma imagem real (640x480).
// Rodar make cocotb completo (incluindo test_sobel_multicycle.py,
// test_four_consecutive_frames) e o proximo passo obrigatorio antes de
// considerar esta integracao fechada - ver RESUMO_ESTADO_PROJETO.md,
// "Proximos passos imediatos", item 4.
//
// Mudanca de fundo: antes desta correcao, line_buffer_2line.o_curr era
// um *wire* puro (latencia 0) e o_valid gateava window_3x3.i_valid no
// MESMO ciclo em que window_3x3.o_ready liberava a aceitacao externa -
// um handshake "same-cycle" valido so porque o_curr tinha latencia 0.
// Com curr/curr_tag/valid agora registrados (Metade 1), esse handshake
// direto deixa de ser correto: a decisao de aceite e a disponibilidade
// real do dado deixam de coincidir no tempo. O novo modulo
// line_window_skid absorve esse descompasso; a condicao que antes
// gateava accept_sample via window_3x3.o_ready diretamente passa a
// usar o_room do novo skid.
module sobel_multicycle #(
    parameter int DATA_WIDTH  = 8,
    parameter int IMG_WIDTH   = 640,
    parameter int IMG_HEIGHT  = 480,
    parameter int COEFF_WIDTH = 3,
    parameter int ACC_WIDTH   = 11
) (
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic                  i_valid,
    input  logic [DATA_WIDTH-1:0] i_pixel,
    output logic                  o_ready,
    output logic                  o_valid,
    output logic [DATA_WIDTH-1:0] o_pixel,
    // status de integridade do pipeline (sticky, limpo so por reset) - ver bloco
    // "o_status" no fim do modulo. bit0=E1 overflow, bit1=E2 balanco, bit2=D dessincronia
    output logic [2:0]            o_status
);

  localparam int unsigned RealTotal = IMG_WIDTH * IMG_HEIGHT;
  localparam int unsigned PaddedTotal = IMG_WIDTH * (IMG_HEIGHT + 1);
  localparam int FeedCntWidth = $clog2(PaddedTotal + 1);

  logic [FeedCntWidth-1:0] feed_cnt_r;
  logic                    in_real_region;

  assign in_real_region = (feed_cnt_r < FeedCntWidth'(RealTotal));

  // frame_tag_r alterna 1 bit a cada wrap do UNICO contador de frame ja
  // existente (feed_cnt_r) - reaproveita a mesma condicao de wrap do
  // bloco de feed_cnt_r mais abaixo (mesmo instante, registrador
  // separado por clareza, sem introduzir um 2o contador).
  logic frame_tag_r;
  logic frame_start_pulse;
  // pulso de re-arme - dispara no PRIMEIRO ciclo de cada frame
  // (feed_cnt_r ainda em 0, antes do incremento deste mesmo ciclo). No
  // frame 1 e um no-op inofensivo (os contadores de aquecimento ja
  // estao em 0 apos rst_n).

  logic                  lb_valid_in;
  logic [DATA_WIDTH-1:0] lb_pixel_in;
  logic                  lb_valid;
  logic [DATA_WIDTH-1:0] lb_curr, lb_line1, lb_line2;
  logic                  lb_curr_tag, lb_line1_tag, lb_line2_tag;

  line_buffer_2line #(
      .DATA_WIDTH(DATA_WIDTH),
      .IMG_WIDTH (IMG_WIDTH)
  ) u_line_buffer (
      .clk       (clk),
      .rst_n     (rst_n),
      .i_valid   (lb_valid_in),
      .i_pixel   (lb_pixel_in),
      .i_tag     (frame_tag_r),
      .i_rearm   (frame_start_pulse),
      .o_valid   (lb_valid),
      .o_curr    (lb_curr),
      .o_line1   (lb_line1),
      .o_line2   (lb_line2),
      .o_curr_tag (lb_curr_tag),
      .o_line1_tag(lb_line1_tag),
      .o_line2_tag(lb_line2_tag)
  );

  // ALTERADO AQUI: novo estagio elastico (Metade 2 da Alternativa 1),
  // absorvendo o descompasso de 1 ciclo introduzido pela Metade 1
  // acima. DEPTH=2, formula "v2" de o_room (ver line_window_skid.sv) -
  // profundidade recomendada em RESUMO_ESTADO_PROJETO.md, secao 3
  // ("Duas formulas de o_room testadas").
  logic                    lw_skid_room;
  logic                    lw_skid_valid;
  logic [DATA_WIDTH-1:0]   lw_skid_curr, lw_skid_line1, lw_skid_line2;
  logic                    lw_skid_curr_tag, lw_skid_line1_tag, lw_skid_line2_tag;
  logic                    lw_skid_overflow;  // consumido pelo bit 0 de o_status (E1)

  line_window_skid #(
      .DATA_WIDTH(DATA_WIDTH),
      .DEPTH     (2)
  ) u_lw_skid (
      .clk               (clk),
      .rst_n             (rst_n),
      .i_push            (lb_valid),
      .i_curr            (lb_curr),
      .i_line1           (lb_line1),
      .i_line2           (lb_line2),
      .i_curr_tag        (lb_curr_tag),
      .i_line1_tag       (lb_line1_tag),
      .i_line2_tag       (lb_line2_tag),
      .o_room            (lw_skid_room),
      // ALTERADO AQUI (Alternativa A3): so libera esta entrega (pop)
      // quando window_3x3 esta pronto E u_skid esta completamente vazio
      // - uma unica entrega pode gerar ate 2 pushes em u_skid (saida
      // normal + ciclo fantasma de window_3x3), entao "quase vazio"
      // nao basta. Mantido em LOCKSTEP com o gating de i_valid de
      // u_window abaixo (mesma expressao) - ver justificativa completa
      // no cabecalho de skid_fifo2.sv.
      .i_downstream_ready(win_ready && skid_room),
      .o_valid           (lw_skid_valid),
      .o_curr            (lw_skid_curr),
      .o_line1           (lw_skid_line1),
      .o_line2           (lw_skid_line2),
      .o_curr_tag        (lw_skid_curr_tag),
      .o_line1_tag       (lw_skid_line1_tag),
      .o_line2_tag       (lw_skid_line2_tag),
      .o_overflow        (lw_skid_overflow)
  );
  // lw_skid_overflow e skid_overflow alimentam o bit 0 (E1) de o_status: ao
  // contrario do $error (so simulacao), sobrevivem em hardware sintetizado.

  logic                    win_ready;
  logic                    win_valid;
  logic [9*DATA_WIDTH-1:0] win_window;
  /* verilator lint_off UNUSEDSIGNAL */
  logic                    win_tag;               // nao consumido ainda
  /* verilator lint_on UNUSEDSIGNAL */
  logic                    win_window_valid_geom;

  window_3x3 #(
      .DATA_WIDTH(DATA_WIDTH),
      .IMG_WIDTH (IMG_WIDTH)
  ) u_window (
      .clk               (clk),
      .rst_n             (rst_n),
      // ALTERADO AQUI: entradas vem do novo skid (lw_skid_*), nao mais
      // diretamente de line_buffer_2line (lb_*).
      // ALTERADO AQUI (Alternativa A3): gateado tambem por skid_room -
      // sem isso, lw_skid_valid ficaria "preso" em 1 aguardando o pop
      // (agora condicionado por skid_room acima) e window_3x3 aceitaria
      // a MESMA janela mais de uma vez (o modulo nao tem nocao de "dado
      // repetido" - so amostra i_valid=1 sempre que ve). Mesma
      // expressao win_ready&&skid_room do pop de u_lw_skid acima,
      // mantendo consumo e pop sempre em lockstep.
      .i_valid           (lw_skid_valid && win_ready && skid_room),
      .i_curr            (lw_skid_curr),
      .i_line1           (lw_skid_line1),
      .i_line2           (lw_skid_line2),
      .i_curr_tag        (lw_skid_curr_tag),
      .i_line1_tag       (lw_skid_line1_tag),
      .i_line2_tag       (lw_skid_line2_tag),
      .o_ready           (win_ready),
      .o_valid           (win_valid),
      .o_window          (win_window),
      .o_tag             (win_tag),
      .o_window_valid_geom(win_window_valid_geom)
  );

  logic                    fsm_ready;
  logic                    fsm_i_valid;
  logic [9*DATA_WIDTH-1:0] fsm_i_window;
  logic                    skid_room;  // ALTERADO AQUI (Alternativa A3) - u_skid completamente vazio

  // skid_fifo2 (janela -> FSM). Ganhou a saida o_room nesta correcao
  // (Alternativa A3) - ver RESUMO_ESTADO_PROJETO.md, achado "overflow de
  // skid_fifo2 apos integrar line_window_skid". Continua um modulo
  // deliberadamente SEPARADO de line_window_skid (razao inalterada, ver
  // secao "Trade-off de fundir skid_fifo2.sv... com o novo skid").
  logic skid_overflow;  // consumido pelo bit 0 de o_status (E1)

  skid_fifo2 #(
      .DATA_WIDTH(9 * DATA_WIDTH)
  ) u_skid (
      .clk               (clk),
      .rst_n             (rst_n),
      .i_push            (win_valid_real),
      .i_push_data       (win_window),
      .i_downstream_ready(fsm_ready),
      .o_valid           (fsm_i_valid),
      .o_data            (fsm_i_window),
      .o_overflow        (skid_overflow),
      .o_room            (skid_room)
  );

  mac_control_fsm #(
      .DATA_WIDTH (DATA_WIDTH),
      .COEFF_WIDTH(COEFF_WIDTH),
      .ACC_WIDTH  (ACC_WIDTH)
  ) u_fsm (
      .clk     (clk),
      .rst_n   (rst_n),
      .i_valid (fsm_i_valid),
      .i_window(fsm_i_window),
      .o_ready (fsm_ready),
      .o_valid (o_valid),
      .o_pixel (o_pixel)
  );

  // ALTERADO AQUI (F-17, Opcao 2): contador ciclico por ORDEM DE JANELA.
  // window_3x3 emite W*(H+1) janelas raw por frame; as W primeiras de cada
  // ciclo sao a "linha de saida -1" virtual (line1/line2 = zero-padding pos
  // i_rearm) e NUNCA sao pixels reais. Independe de tag e de temporizacao
  // de fronteira - so do invariante geometrico (docs/MODELO_LATENCIA_PIPELINE.md).
  localparam int WinCntWidth = $clog2(PaddedTotal);

  logic [WinCntWidth-1:0] win_cnt_r;
  logic                   win_is_spurious;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      win_cnt_r <= '0;
    end else if (win_valid) begin
      win_cnt_r <= (win_cnt_r == WinCntWidth'(PaddedTotal - 1)) ? '0 : (win_cnt_r + 1'b1);
    end
  end

  assign win_is_spurious = (win_cnt_r < WinCntWidth'(IMG_WIDTH));

  // INALTERADO: win_valid_real continua exigindo janela geometricamente
  // pura (win_window_valid_geom) - agora com o residuo pequeno e
  // sempre sinalizado documentado em RESUMO_ESTADO_PROJETO.md, secao
  // "Correcao aplicada na sandbox... validacao final de ponta a ponta"
  // (2 janelas impuras por fronteira de frame, sempre descartadas
  // aqui, nunca silenciosamente erradas).
  logic win_valid_real;
  assign win_valid_real = win_valid && !win_is_spurious && win_window_valid_geom;

  logic gate_fsm_ok;
  logic accept_sample;
  logic consume_sample;

  assign gate_fsm_ok = fsm_ready && !win_valid;
  // ALTERADO AQUI: accept_sample agora gateado por lw_skid_room (o novo
  // skid), nao mais diretamente por win_ready. win_ready continua
  // existindo e sendo usado, mas so como i_downstream_ready do novo
  // skid (ver instancia u_lw_skid acima) - nao mais lido diretamente
  // aqui.
  assign accept_sample = lw_skid_room && gate_fsm_ok;

  assign o_ready = accept_sample && in_real_region;

  assign consume_sample = accept_sample && (in_real_region ? i_valid : 1'b1);

  assign lb_valid_in = consume_sample;
  assign lb_pixel_in = in_real_region ? i_pixel : {DATA_WIDTH{1'b0}};
  assign frame_start_pulse = consume_sample && (feed_cnt_r == '0);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      feed_cnt_r <= '0;
    end else if (consume_sample) begin
      feed_cnt_r <= (feed_cnt_r == FeedCntWidth'(PaddedTotal - 1)) ? '0 : (feed_cnt_r + 1'b1);
    end
  end

  // frame_tag_r alterna exatamente no ciclo em que feed_cnt_r da a
  // volta (PaddedTotal-1 -> 0) - mesma condicao do bloco acima,
  // registrador separado por clareza. O bit alterna 1x por frame
  // completo (reais + padding da borda inferior), nunca no meio de um
  // frame - contrato ja assumido pelos testbenches de
  // line_buffer_2line.sv/window_3x3.sv.
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      frame_tag_r <= 1'b0;
    end else if (consume_sample && feed_cnt_r == FeedCntWidth'(PaddedTotal - 1)) begin
      frame_tag_r <= ~frame_tag_r;
    end
  end

  // ---------------------------------------------------------------------
  // o_status: monitor de integridade do pipeline (Ressalva 3 da Auditoria 01).
  // 3 bits STICKY (so o reset limpa), sintetizaveis, so sinalizam - nao ha
  // autocorrecao (decisao registrada: autocorrigir esconderia o erro e o dano
  // de uma perda a montante esta em 2 contadores, nao so em 1).
  //
  //  bit0 (E1): overflow de u_skid ou u_lw_skid. Perda por causa conhecida,
  //             sinalizada NO INSTANTE do evento.
  //  bit1 (E2): balanco de janelas. bal_r conta +1 por janela real que tenta
  //             entrar em u_skid e -1 por pixel que sai da FSM. Com a FSM
  //             ociosa e o skid vazio (fsm_ready && !fsm_i_valid) o saldo
  //             tem de ser 0. Pega perda E duplicacao a jusante de win_valid_real.
  //  bit2 (D) : dessincronia a montante (perda de amostra antes de window_3x3).
  //             Com o pipeline drenado, win_cnt_r tem de valer
  //             feed_cnt_r - (col_feed_r != 0). Ver docs (Fase 2, sondas v2/v3).
  //
  // Modelo de falhas (declarado): detecta perda/duplicacao/dessincronia de
  // janelas. NAO detecta erro de VALOR de pixel, nem perda de pulso de o_valid
  // por consumidor externo (a saida nao tem ready). Perda + duplicacao dentro
  // de um mesmo intervalo entre verificacoes se compensam em bit1 (risco
  // residual aceito; perda por overflow e pega por bit0 independentemente).
  //
  // Todos os termos abaixo dependem so de REGISTRADORES (ou de nets derivados
  // deles), nunca de i_valid de entrada - mesma classe de latencia, sem
  // misturar instantes de decisao diferentes.
  // ---------------------------------------------------------------------
  localparam int ColFeedWidth = $clog2(IMG_WIDTH);
  localparam logic [ColFeedWidth-1:0] LastColFeed = ColFeedWidth'(IMG_WIDTH - 1);

  // Coluna da amostra consumida (= feed_cnt_r mod IMG_WIDTH, sem divisor:
  // PaddedTotal e multiplo de IMG_WIDTH, entao os dois wraps coincidem).
  logic [ColFeedWidth-1:0] col_feed_r;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      col_feed_r <= '0;
    end else if (consume_sample) begin
      col_feed_r <= (col_feed_r == LastColFeed) ? '0 : (col_feed_r + 1'b1);
    end
  end

  // E1
  logic e1_event;
  assign e1_event = skid_overflow || lw_skid_overflow;

  // E2: bal_r aritmetica modular de 4 bits (so importa bal_r != 0).
  logic [3:0] bal_r;
  logic       e2_check;
  logic       e2_mismatch;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      bal_r <= '0;
    end else begin
      bal_r <= bal_r + {3'b0, win_valid_real} - {3'b0, o_valid};
    end
  end

  // fsm_ready && !fsm_i_valid implica skid vazio (o_valid do skid e
  // count!=0 && ready) e FSM em S_IDLE (sem saida pendente).
  assign e2_check    = fsm_ready && !fsm_i_valid;
  assign e2_mismatch = e2_check && (bal_r != '0);

  // D: pipeline drenado = nada em voo entre line_buffer, u_lw_skid,
  // window_3x3 (win_ready = fora do ciclo fantasma) e u_skid/FSM.
  logic                    drained_d;
  logic [FeedCntWidth-1:0] win_cnt_expected;
  logic                    d_mismatch;

  assign drained_d = !lb_valid && !win_valid && !lw_skid_valid && win_ready && e2_check;
  assign win_cnt_expected = (col_feed_r != '0) ? (feed_cnt_r - 1'b1) : feed_cnt_r;
  assign d_mismatch = drained_d && (win_cnt_expected != FeedCntWidth'(win_cnt_r));

  logic [2:0] status_r;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      status_r <= '0;
    end else begin
      status_r <= status_r | {d_mismatch, e2_mismatch, e1_event};
    end
  end

  assign o_status = status_r;

  // synthesis translate_off
  // Localiza a falha em simulacao (1 mensagem por bit, na 1a subida).
  /* verilator lint_off SYNCASYNCNET */
  always_ff @(posedge clk) begin
    if (rst_n) begin
      if (e1_event && !status_r[0]) begin
        $error("sobel_multicycle: o_status[0] (E1) - overflow de skid (u_skid=%0d u_lw_skid=%0d)",
               skid_overflow, lw_skid_overflow);
      end
      if (e2_mismatch && !status_r[1]) begin
        $error("sobel_multicycle: o_status[1] (E2) - balanco de janelas bal=%0d feed_cnt=%0d win_cnt=%0d",
               $signed(bal_r), feed_cnt_r, win_cnt_r);
      end
      if (d_mismatch && !status_r[2]) begin
        $error("sobel_multicycle: o_status[2] (D) - dessincronia feed_cnt=%0d col_feed=%0d win_cnt=%0d esperado=%0d",
               feed_cnt_r, col_feed_r, win_cnt_r, win_cnt_expected);
      end
    end
  end
  /* verilator lint_on SYNCASYNCNET */
  // synthesis translate_on

endmodule
