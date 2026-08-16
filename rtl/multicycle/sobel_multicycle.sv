`include "timescale.svh"

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

  // ALTERADO AQUI (Alternativa 3-B, RESUMO_ESTADO_PROJETO.md, secao
  // "Design fechado - prevencao estrutural do bug de fronteira de
  // frame"): frame_tag_r alterna 1 bit a cada wrap do UNICO contador
  // de frame ja existente (feed_cnt_r) - reaproveita a mesma condicao
  // de wrap do bloco de feed_cnt_r mais abaixo (mesmo instante,
  // registrador separado por clareza, sem introduzir um 2o contador).
  logic frame_tag_r;
  logic frame_start_pulse;  // ALTERADO AQUI (3-C)
  // ALTERADO AQUI (3-C): pulso de re-arme - dispara no
  // PRIMEIRO ciclo de cada frame (feed_cnt_r ainda em 0, antes do
  // incremento deste mesmo ciclo). No frame 1 e um no-op inofensivo
  // (os contadores de aquecimento ja estao em 0 apos rst_n).

  logic                  lb_valid_in;
  logic [DATA_WIDTH-1:0] lb_pixel_in;
  logic                  lb_valid;
  logic [DATA_WIDTH-1:0] lb_curr, lb_line1, lb_line2;
  logic                  lb_curr_tag, lb_line1_tag, lb_line2_tag;  // ALTERADO AQUI (3-B)

  line_buffer_2line #(
      .DATA_WIDTH(DATA_WIDTH),
      .IMG_WIDTH (IMG_WIDTH)
  ) u_line_buffer (
      .clk       (clk),
      .rst_n     (rst_n),
      .i_valid   (lb_valid_in),
      .i_pixel   (lb_pixel_in),
      .i_tag     (frame_tag_r),   // ALTERADO AQUI (3-B)
      .i_rearm   (frame_start_pulse),  // ALTERADO AQUI (3-C)
      .o_valid   (lb_valid),
      .o_curr    (lb_curr),
      .o_line1   (lb_line1),
      .o_line2   (lb_line2),
      .o_curr_tag (lb_curr_tag),   // ALTERADO AQUI (3-B)
      .o_line1_tag(lb_line1_tag),  // ALTERADO AQUI (3-B)
      .o_line2_tag(lb_line2_tag)   // ALTERADO AQUI (3-B)
  );

  logic                    win_ready;
  logic                    win_valid;
  logic [9*DATA_WIDTH-1:0] win_window;
  logic                    win_tag;               // ALTERADO AQUI (3-B) - nao consumido ainda
  logic                    win_window_valid_geom;  // ALTERADO AQUI (3-B)

  window_3x3 #(
      .DATA_WIDTH(DATA_WIDTH),
      .IMG_WIDTH (IMG_WIDTH)
  ) u_window (
      .clk               (clk),
      .rst_n             (rst_n),
      .i_valid           (lb_valid),
      .i_curr            (lb_curr),
      .i_line1           (lb_line1),
      .i_line2           (lb_line2),
      .i_curr_tag        (lb_curr_tag),   // ALTERADO AQUI (3-B)
      .i_line1_tag       (lb_line1_tag),  // ALTERADO AQUI (3-B)
      .i_line2_tag       (lb_line2_tag),  // ALTERADO AQUI (3-B)
      .o_ready           (win_ready),
      .o_valid           (win_valid),
      .o_window          (win_window),
      .o_tag             (win_tag),               // ALTERADO AQUI (3-B)
      .o_window_valid_geom(win_window_valid_geom)  // ALTERADO AQUI (3-B)
  );

  logic                    fsm_ready;
  logic                    skid_valid_r;
  logic [9*DATA_WIDTH-1:0] skid_window_r;
  logic                    fsm_i_valid;
  logic [9*DATA_WIDTH-1:0] fsm_i_window;

  assign fsm_i_valid  = fsm_ready && (skid_valid_r || win_valid_real);
  assign fsm_i_window = skid_valid_r ? skid_window_r : win_window;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      skid_valid_r  <= 1'b0;
      skid_window_r <= '0;
    end else if (skid_valid_r) begin
      if (fsm_ready) skid_valid_r <= 1'b0;
    end else if (win_valid_real && !fsm_ready) begin
      skid_valid_r  <= 1'b1;
      skid_window_r <= win_window;
    end
  end

  /* verilator lint_off SYNCASYNCNET */
  // synthesis translate_off
  always_ff @(posedge clk) begin
    if (rst_n && skid_valid_r && win_valid) begin
      $error("sobel_multicycle: skid buffer (profundidade 1) transbordou - ",
             "2 win_valid simultaneos com o buffer ja ocupado, janela seria perdida");
    end
  end
  // synthesis translate_on
  /* verilator lint_on SYNCASYNCNET */

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

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      discard_cnt_r <= '0;
      warmup_done_r <= 1'b0;
    end else if (!warmup_done_r && win_valid) begin
      if (discard_cnt_r == DiscardCntWidth'(IMG_WIDTH - 1)) warmup_done_r <= 1'b1;
      else discard_cnt_r <= discard_cnt_r + 1'b1;
    end
  end

  // ALTERADO AQUI (3-B, Opcao 1 - gate ANTES do skid, aprovada em
  // sessao de discussao): win_valid_real agora tambem exige janela
  // geometricamente pura (win_window_valid_geom). Mesma estrutura de
  // win_valid_real ja usada para warmup_done_r - uma janela impura
  // (residuo do frame anterior ainda em i_line2, ou a "linha -1" do
  // arranque) nunca chega a ser candidata a entrar no skid nem a
  // alimentar a FSM; o pixel de saida correspondente e simplesmente
  // omitido do stream, sem custo de area adicional no skid (que
  // continua guardando so win_window, sem +1 bit de geom - ver
  // analise de trade-off registrada no chat).
  logic win_valid_real;
  assign win_valid_real = win_valid && warmup_done_r && win_window_valid_geom;

  logic gate_fsm_ok;
  logic accept_sample;
  logic consume_sample;

  assign gate_fsm_ok = fsm_ready && !win_valid;
  assign accept_sample = win_ready && gate_fsm_ok;

  assign o_ready = accept_sample && in_real_region;

  assign consume_sample = accept_sample && (in_real_region ? i_valid : 1'b1);

  assign lb_valid_in = consume_sample;
  assign lb_pixel_in = in_real_region ? i_pixel : {DATA_WIDTH{1'b0}};
  assign frame_start_pulse = consume_sample && (feed_cnt_r == '0);  // ALTERADO AQUI (3-C)

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      feed_cnt_r <= '0;
    end else if (consume_sample) begin
      feed_cnt_r <= (feed_cnt_r == FeedCntWidth'(PaddedTotal - 1)) ? '0 : (feed_cnt_r + 1'b1);
    end
  end

  // ALTERADO AQUI (3-B): frame_tag_r alterna exatamente no ciclo em
  // que feed_cnt_r da a volta (PaddedTotal-1 -> 0) - mesma condicao
  // do bloco acima, registrador separado por clareza. O bit alterna
  // 1x por frame completo (reais + padding da borda inferior), nunca
  // no meio de um frame - contrato ja assumido pelos testbenches de
  // line_buffer_2line.sv/window_3x3.sv ("o integrador alterna i_tag
  // APENAS a cada inicio de frame").
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      frame_tag_r <= 1'b0;
    end else if (consume_sample && feed_cnt_r == FeedCntWidth'(PaddedTotal - 1)) begin
      frame_tag_r <= ~frame_tag_r;
    end
  end

endmodule
