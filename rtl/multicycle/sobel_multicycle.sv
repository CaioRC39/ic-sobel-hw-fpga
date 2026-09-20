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
    output logic [DATA_WIDTH-1:0] o_pixel
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
  logic                    lw_skid_overflow;  // nao conectado de proposito - ver nota abaixo

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
      .i_downstream_ready(win_ready),
      .o_valid           (lw_skid_valid),
      .o_curr            (lw_skid_curr),
      .o_line1           (lw_skid_line1),
      .o_line2           (lw_skid_line2),
      .o_curr_tag        (lw_skid_curr_tag),
      .o_line1_tag       (lw_skid_line1_tag),
      .o_line2_tag       (lw_skid_line2_tag),
      .o_overflow        (lw_skid_overflow)
  );
  // lw_skid_overflow deixado sem consumo alem do proprio $error interno
  // do modulo - mesmo padrao ja usado para skid_fifo2's o_overflow e
  // para kernel_rom's o_addr_valid: saida nao conectada a mais nada nao
  // e erro, o alarme de simulacao ja cobre a violacao de contrato
  // independente de conexao externa.

  logic                    win_ready;
  logic                    win_valid;
  logic [9*DATA_WIDTH-1:0] win_window;
  logic                    win_tag;               // nao consumido ainda
  logic                    win_window_valid_geom;

  window_3x3 #(
      .DATA_WIDTH(DATA_WIDTH),
      .IMG_WIDTH (IMG_WIDTH)
  ) u_window (
      .clk               (clk),
      .rst_n             (rst_n),
      // ALTERADO AQUI: entradas vem do novo skid (lw_skid_*), nao mais
      // diretamente de line_buffer_2line (lb_*).
      .i_valid           (lw_skid_valid),
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

  // skid_fifo2 (janela -> FSM) - INALTERADO por esta correcao, ver
  // RESUMO_ESTADO_PROJETO.md secao "Trade-off de fundir skid_fifo2.sv
  // ... com o novo skid" para o porque de nao reaproveitar/fundir com
  // line_window_skid.
  skid_fifo2 #(
      .DATA_WIDTH(9 * DATA_WIDTH)
  ) u_skid (
      .clk               (clk),
      .rst_n             (rst_n),
      .i_push            (win_valid_real),
      .i_push_data       (win_window),
      .i_downstream_ready(fsm_ready),
      .o_valid           (fsm_i_valid),
      .o_data            (fsm_i_window)
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

  localparam int DiscardCntWidth = $clog2(IMG_WIDTH + 1);

  logic [DiscardCntWidth-1:0] discard_cnt_r;
  logic                       warmup_done_r;

  // INALTERADO: continua contando pulsos de win_valid (saida de
  // window_3x3), nao afetado pelo novo skid - window_3x3 continua
  // emitindo a mesma sequencia de pulsos de sempre, so com temporizacao
  // de chegada diferente por causa do buffer elastico a montante.
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      discard_cnt_r <= '0;
      warmup_done_r <= 1'b0;
    end else if (!warmup_done_r && win_valid) begin
      if (discard_cnt_r == DiscardCntWidth'(IMG_WIDTH - 1)) warmup_done_r <= 1'b1;
      else discard_cnt_r <= discard_cnt_r + 1'b1;
    end
  end

  // INALTERADO: win_valid_real continua exigindo janela geometricamente
  // pura (win_window_valid_geom) - agora com o residuo pequeno e
  // sempre sinalizado documentado em RESUMO_ESTADO_PROJETO.md, secao
  // "Correcao aplicada na sandbox... validacao final de ponta a ponta"
  // (2 janelas impuras por fronteira de frame, sempre descartadas
  // aqui, nunca silenciosamente erradas).
  logic win_valid_real;
  assign win_valid_real = win_valid && warmup_done_r && win_window_valid_geom;

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

endmodule
