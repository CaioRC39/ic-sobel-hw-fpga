`include "timescale.svh"

// sobel_multicycle
//
// Top-level da arquitetura multiciclo: line_buffer_2line -> window_3x3
// -> mac_control_fsm. Resolve o handshake de backpressure entre o
// stream de entrada continuo e a FSM (15 ciclos uteis/janela) e fecha
// a borda inferior do frame (window_3x3/line_buffer_2line sao
// agnosticos a IMG_HEIGHT por projeto - ver docs/ARQUITETURA_MULTICICLO.md,
// secao 7.1). Design fechado em sessao de discussao - ver
// RESUMO_ESTADO_PROJETO.md, secao "Design fechado para
// sobel_multicycle.sv", para o raciocinio completo e alternativas
// descartadas (contador de coluna proprio, frame_done dedicado, FIFO
// de desacoplamento).
//
// Contrato de interface (ready/valid classico): o mundo externo so
// deve considerar 1 pixel aceito quando i_valid=1 E o_ready=1 no MESMO
// ciclo. i_valid=1 com o_ready=0 e apenas ignorado (backpressure
// normal, sem $error - diferente do contrato de window_3x3, que e
// interno a este modulo e nunca chega a ser violado por construcao,
// ja que o_ready aqui so sobe quando window_3x3.o_ready tambem esta
// em 1).
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

  // RealTotal: pixels de imagem de fato. PaddedTotal: + 1 "linha
  // fantasma" de zeros no fim (borda inferior, mesma convencao das
  // demais bordas - ver cabecalho do modulo).
  localparam int unsigned RealTotal = IMG_WIDTH * IMG_HEIGHT;
  localparam int unsigned PaddedTotal = IMG_WIDTH * (IMG_HEIGHT + 1);
  localparam int FeedCntWidth = $clog2(PaddedTotal + 1);

  logic [FeedCntWidth-1:0] feed_cnt_r;
  logic                    in_real_region;

  assign in_real_region = (feed_cnt_r < FeedCntWidth'(RealTotal));

  // ---------------------------------------------------------------------
  // line_buffer_2line
  // ---------------------------------------------------------------------
  logic                  lb_valid_in;
  logic [DATA_WIDTH-1:0] lb_pixel_in;
  logic                  lb_valid;
  logic [DATA_WIDTH-1:0] lb_curr, lb_line1, lb_line2;

  line_buffer_2line #(
      .DATA_WIDTH(DATA_WIDTH),
      .IMG_WIDTH (IMG_WIDTH)
  ) u_line_buffer (
      .clk    (clk),
      .rst_n  (rst_n),
      .i_valid(lb_valid_in),
      .i_pixel(lb_pixel_in),
      .o_valid(lb_valid),
      .o_curr (lb_curr),
      .o_line1(lb_line1),
      .o_line2(lb_line2)
  );

  // ---------------------------------------------------------------------
  // window_3x3
  // ---------------------------------------------------------------------
  logic                    win_ready;
  logic                    win_valid;
  logic [9*DATA_WIDTH-1:0] win_window;

  window_3x3 #(
      .DATA_WIDTH(DATA_WIDTH),
      .IMG_WIDTH (IMG_WIDTH)
  ) u_window (
      .clk     (clk),
      .rst_n   (rst_n),
      .i_valid (lb_valid),
      .i_curr  (lb_curr),
      .i_line1 (lb_line1),
      .i_line2 (lb_line2),
      .o_ready (win_ready),
      .o_valid (win_valid),
      .o_window(win_window)
  );

  // ---------------------------------------------------------------------
  // Skid buffer de profundidade 1 (Alternativa B): window_3x3 pode
  // emitir 2 win_valid CONSECUTIVOS por linha - a janela "real" da
  // ultima coluna e, no ciclo SEGUINTE, a janela do ciclo fantasma da
  // borda direita (autonoma: dispara sozinha, sem nenhum feed novo do
  // top-level - ver window_3x3.sv, ramo `phantom_pending_r`). O 2o
  // pulso chega enquanto a FSM ja esta ocupada processando o 1o
  // (mac_control_fsm leva 15 ciclos/janela) e seria perdido
  // silenciosamente sem este buffer - bug real, encontrado por
  // execucao real (nao hipotetico).
  //
  // Profundidade 1 e suficiente POR CONSTRUCAO, nao por sorte: o
  // gating de accept_sample (abaixo) ja impede que uma janela REAL
  // nova colida com a FSM ocupada (usa `!win_valid` e `fsm_ready`); so
  // o pulso fantasma AUTONOMO escapa dessa gating, e ele acontece no
  // maximo 1x por linha, sempre separado do proximo por muito mais de
  // 15 ciclos (a propria gating ja paceia o feed de pixels reais no
  // ritmo da FSM).
  // ---------------------------------------------------------------------
  logic                    fsm_ready;
  logic                    skid_valid_r;
  logic [9*DATA_WIDTH-1:0] skid_window_r;
  logic                    fsm_i_valid;
  logic [9*DATA_WIDTH-1:0] fsm_i_window;

  // Mux de entrada da FSM: o valor guardado no skid (se houver) tem
  // prioridade sobre a saida "ao vivo" de window_3x3 - garante que a
  // ordem de entrega das janelas nunca inverte.
  //
  // ALTERADO AQUI (correcao de bug real - ver historico do chat): a
  // apresentacao de i_valid a FSM so pode acontecer no(s) ciclo(s) em
  // que fsm_ready(=o_ready da FSM) tambem esta em 1 - o contrato da
  // FSM exige i_valid=1 EXATAMENTE no ciclo em que ela esta em
  // S_IDLE, nao "por varios ciclos ate ela ficar livre". A versao
  // anterior travava fsm_i_valid=1 pelos ~15 ciclos inteiros em que a
  // FSM ficava ocupada processando a janela anterior, violando o
  // contrato repetidamente (nao so 1 vez) - bug real, achado pelo
  // padrao de ~15 disparos consecutivos do $error.
  assign fsm_i_valid  = fsm_ready && (skid_valid_r || win_valid_real);
  assign fsm_i_window = skid_valid_r ? skid_window_r : win_window;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      skid_valid_r  <= 1'b0;
      skid_window_r <= '0;
    end else if (skid_valid_r) begin
      if (fsm_ready) skid_valid_r <= 1'b0;  // FSM aceitou o valor guardado neste ciclo
    end else if (win_valid_real && !fsm_ready) begin
      // FSM ocupada no exato ciclo em que a janela chega - captura em
      // vez de deixar o contrato de mac_control_fsm ser violado.
      skid_valid_r  <= 1'b1;
      skid_window_r <= win_window;
    end
  end

  // synthesis translate_off
  // Checagem de simulacao: a profundidade 1 e uma promessa derivada da
  // analise acima (no maximo 1 pulso "extra" pendente por vez) - se um
  // dia deixar de valer (ex: mudanca futura no gating de accept_sample
  // ou no proprio window_3x3), uma 2a janela chegaria com o buffer ja
  // ocupado e seria perdida silenciosamente sem este alarme.
  always_ff @(posedge clk) begin
    if (rst_n && skid_valid_r && win_valid) begin
      $error("sobel_multicycle: skid buffer (profundidade 1) transbordou - ",
             "2 win_valid simultaneos com o buffer ja ocupado, janela seria perdida");
    end
  end
  // synthesis translate_on

  // ---------------------------------------------------------------------
  // mac_control_fsm
  // ---------------------------------------------------------------------

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

  // ---------------------------------------------------------------------
  // Handshake unico: decide, a cada ciclo, se a pipeline pode receber
  // 1 amostra nova - seja pixel real ou zero de padding da borda
  // inferior. gate_fsm_ok evita a colisao no ciclo de handoff da
  // janela (window_3x3 nao tem backpressure proprio da FSM - se
  // emitisse win_valid no mesmo ciclo em que a FSM ainda nao esta
  // pronta, a janela seria perdida silenciosamente).
  // ---------------------------------------------------------------------

  // ---------------------------------------------------------------------
  // Descarte "linha de saida -1": window_3x3 emite IMG_WIDTH janelas
  // espurias no arranque, antes de line_buffer_2line.o_line1/o_line2
  // conterem dado real (mesmo fenomeno ja documentado e descartado em
  // test_window_3x3.py, secao 4.2 do ARQUITETURA_MULTICICLO.md) - bug
  // real, confirmado por execucao (trace + conta na mao batendo com o
  // o_pixel observado, ver historico do chat).
  //
  // Acontece 1 UNICA VEZ na vida do modulo, nao a cada frame:
  // line_buffer_2line nunca "esfria" de novo sozinho (warmup1_cnt_r/
  // warmup2_cnt_r so resetam em rst_n), e a borda superior dos frames
  // seguintes ja e suprida pela propria linha fantasma de zeros do fim
  // do frame anterior (Ponto 4 do design fechado) - por isso um latch
  // (warmup_done_r), nao um contador que reinicia.
  // ---------------------------------------------------------------------
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

  // win_valid_real: so as janelas que correspondem a uma posicao de
  // saida legitima. gate_fsm_ok/accept_sample continuam usando o
  // win_valid BRUTO (timing estrutural interno de window_3x3, nao
  // depende do conteudo ser lixo ou nao).
  logic win_valid_real;
  assign win_valid_real = win_valid && warmup_done_r;

  logic gate_fsm_ok;
  logic accept_sample;
  logic consume_sample;

  assign gate_fsm_ok = fsm_ready && !win_valid;
  assign accept_sample = win_ready && gate_fsm_ok;

  // o_ready externo: so pede pixel novo de fora enquanto ainda estamos
  // na regiao real do frame - durante o padding da borda inferior, o
  // modulo se auto-alimenta e NAO deve aceitar pixel externo (evita
  // misturar o inicio do proximo frame com o padding do atual).
  assign o_ready = accept_sample && in_real_region;

  // Consumo efetivo: na regiao real, so acontece se o mundo externo
  // tambem apresentou i_valid=1 (par ready/valid classico); na regiao
  // de padding, e auto-alimentacao (nao depende de i_valid externo).
  assign consume_sample = accept_sample && (in_real_region ? i_valid : 1'b1);

  assign lb_valid_in = consume_sample;
  assign lb_pixel_in = in_real_region ? i_pixel : {DATA_WIDTH{1'b0}};

  // Contador unico (Ponto 2 do design fechado). Wrap natural em
  // PaddedTotal-1 -> 0 fecha sozinho o reinicio do proximo frame, sem
  // nenhuma logica de reset dedicada - assim que o_ready volta a 1
  // (Ponto 5), o proximo pixel aceito ja incrementa a partir de 0.
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      feed_cnt_r <= '0;
    end else if (consume_sample) begin
      feed_cnt_r <= (feed_cnt_r == FeedCntWidth'(PaddedTotal - 1)) ? '0 : (feed_cnt_r + 1'b1);
    end
  end

  // synthesis translate_off
  // Instrumentacao TEMPORARIA de depuracao - remover apos o diagnostico.
  // So imprime EVENTOS (nao todo ciclo), pra manter o log curto e legivel.
  logic dbg_prev_skid_r;

  always_ff @(posedge clk) begin
    if (rst_n) begin
      if (consume_sample)
        $display("[%0t] FEED  feed_cnt_r=%0d->  in_real=%0d pixel_fed=%0d",
                  $time, feed_cnt_r, in_real_region, lb_pixel_in);
      if (win_valid)
        $display("[%0t] WINV  win_valid=1  fsm_ready=%0d skid_valid_r=%0d fsm_i_valid=%0d win_window=%0h",
                  $time, fsm_ready, skid_valid_r, fsm_i_valid, win_window);
      if (skid_valid_r && !dbg_prev_skid_r)
        $display("[%0t] SKID  CAPTUROU win_window=%0h", $time, skid_window_r);
      if (!skid_valid_r && dbg_prev_skid_r)
        $display("[%0t] SKID  LIBEROU p/ FSM", $time);
      if (o_valid)
        $display("[%0t] OUT   o_pixel=%0d", $time, o_pixel);
    end
    dbg_prev_skid_r <= skid_valid_r;
  end
  // synthesis translate_on

endmodule
