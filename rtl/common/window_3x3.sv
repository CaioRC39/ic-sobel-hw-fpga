`include "timescale.svh"

// window_3x3
//
// Modulo comum (usado pelas 3 arquiteturas). Recebe, a cada ciclo com
// i_valid=1, uma amostra de 3 linhas diferentes da imagem alinhadas na
// mesma coluna (i_curr, i_line1, i_line2 - tipicamente vindas de
// line_buffer_2line) e monta a janela deslizante 3x3 completa,
// aplicando zero-padding nas bordas esquerda e direita de cada linha.
//
// Mapeamento de o_window[linha][coluna]:
//   linha 0 = 2 linhas acima da linha central (i_line2)
//   linha 1 = linha central da janela         (i_line1)
//   linha 2 = 1 linha abaixo da linha central  (i_curr)
//   coluna 0 = esquerda, coluna 1 = centro, coluna 2 = direita
//
// Ou seja: a janela emitida em um dado ciclo esta CENTRADA na linha de
// i_line1, nao na linha de i_curr - i_curr funciona como o "olhar a
// frente" necessario para completar a vizinhanca abaixo do centro. Ver
// docs/ARQUITETURA_MULTICICLO.md, secao "Modulos Comuns > window_3x3",
// para a derivacao completa (por que a borda esquerda "sai de graca" do
// reset mas a direita exige um ciclo fantasma extra).
//
// A porta o_window e um vetor 1D "achatado" (packed), nao um array 2D -
// ferramentas de simulacao via VPI (Icarus+cocotb, neste projeto) nao
// indexam com confianca portas de array 2D unpacked. Layout: 9 fatias
// de DATA_WIDTH bits, MSB->LSB na ordem linha-major k=3*linha+coluna
// (k=0 e a fatia mais significativa): o_window[(9-k)*DATA_WIDTH-1 -:
// DATA_WIDTH] == window[linha][coluna].
//
// CONTRATO DE INTERFACE (importante): a fonte que dirige i_valid/i_curr/
// i_line1/i_line2 DEVE inserir pelo menos 1 ciclo de gap (i_valid=0)
// entre o ultimo pixel de uma linha e o primeiro pixel da linha
// seguinte - analogo ao intervalo de blanking horizontal em video. Sem
// esse gap, o ciclo fantasma de borda direita nao tem onde acontecer e
// um pixel real seria descartado (ver assertion de simulacao abaixo).
//
// Este modulo NAO trata a borda inferior do frame (ultima linha da
// imagem) - isso exige uma linha fantasma extra de zeros ao final do
// frame, responsabilidade de um controlador de nivel superior (fora do
// escopo deste modulo, que nao tem nocao de altura de imagem).
module window_3x3 #(
    parameter int DATA_WIDTH = 8,
    parameter int IMG_WIDTH  = 8
) (
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    i_valid,
    input  logic [  DATA_WIDTH-1:0] i_curr,
    input  logic [  DATA_WIDTH-1:0] i_line1,
    input  logic [  DATA_WIDTH-1:0] i_line2,
    output logic                    o_valid,
    output logic [9*DATA_WIDTH-1:0] o_window
);

  localparam int ColWidth = $clog2(IMG_WIDTH);
  localparam logic [ColWidth-1:0] LastCol = (IMG_WIDTH - 1);

  logic [ColWidth-1:0] col_cnt_r;
  logic                phantom_pending_r;
  logic                valid_r;
  logic                is_first_col;
  logic                is_last_col;

  assign is_first_col = (col_cnt_r == '0);
  assign is_last_col  = (col_cnt_r == LastCol);

  // Tres shift-registers horizontais independentes (3 posicoes cada),
  // um por linha da janela. sr_*_r[0] = amostra mais recente (direita),
  // sr_*_r[2] = amostra mais antiga (esquerda).
  logic [DATA_WIDTH-1:0] sr_row0_r[3];  // linha "2 acima do centro" (i_line2)
  logic [DATA_WIDTH-1:0] sr_row1_r[3];  // linha central            (i_line1)
  logic [DATA_WIDTH-1:0] sr_row2_r[3];  // linha "abaixo do centro" (i_curr)

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      col_cnt_r <= '0;
      phantom_pending_r <= 1'b0;
      valid_r <= 1'b0;
      for (int i = 0; i < 3; i++) begin
        sr_row0_r[i] <= '0;
        sr_row1_r[i] <= '0;
        sr_row2_r[i] <= '0;
      end
    end else if (phantom_pending_r) begin
      // Ciclo fantasma: nao ha pixel novo (fim de linha) - desliza um
      // zero para completar a borda direita da janela.
      sr_row0_r[2] <= sr_row0_r[1];
      sr_row0_r[1] <= sr_row0_r[0];
      sr_row0_r[0] <= '0;
      sr_row1_r[2] <= sr_row1_r[1];
      sr_row1_r[1] <= sr_row1_r[0];
      sr_row1_r[0] <= '0;
      sr_row2_r[2] <= sr_row2_r[1];
      sr_row2_r[1] <= sr_row2_r[0];
      sr_row2_r[0] <= '0;
      phantom_pending_r <= 1'b0;
      valid_r <= 1'b1;
    end else if (i_valid) begin
      if (is_first_col) begin
        // Inicio de nova linha: descarta o contexto horizontal da linha
        // anterior (senao o pixel da direita da linha anterior "vazaria"
        // como vizinho esquerdo da primeira coluna desta linha).
        sr_row0_r[0] <= i_line2;
        sr_row0_r[1] <= '0;
        sr_row0_r[2] <= '0;
        sr_row1_r[0] <= i_line1;
        sr_row1_r[1] <= '0;
        sr_row1_r[2] <= '0;
        sr_row2_r[0] <= i_curr;
        sr_row2_r[1] <= '0;
        sr_row2_r[2] <= '0;
        valid_r <= 1'b0;  // ainda falta o vizinho da direita
      end else begin
        sr_row0_r[2] <= sr_row0_r[1];
        sr_row0_r[1] <= sr_row0_r[0];
        sr_row0_r[0] <= i_line2;
        sr_row1_r[2] <= sr_row1_r[1];
        sr_row1_r[1] <= sr_row1_r[0];
        sr_row1_r[0] <= i_line1;
        sr_row2_r[2] <= sr_row2_r[1];
        sr_row2_r[1] <= sr_row2_r[0];
        sr_row2_r[0] <= i_curr;
        valid_r <= 1'b1;
      end
      col_cnt_r <= is_last_col ? '0 : (col_cnt_r + 1'b1);
      if (is_last_col) phantom_pending_r <= 1'b1;
    end else begin
      valid_r <= 1'b0;
    end
  end

  assign o_valid = valid_r;

  // Concatenacao MSB->LSB na ordem linha-major (ver comentario no
  // cabecalho do modulo para o layout exato de bits).
  assign o_window = {
    sr_row0_r[2],
    sr_row0_r[1],
    sr_row0_r[0],
    sr_row1_r[2],
    sr_row1_r[1],
    sr_row1_r[0],
    sr_row2_r[2],
    sr_row2_r[1],
    sr_row2_r[0]
  };

  // synthesis translate_off
  // Checagem de simulacao: violacao do contrato de gap entre linhas.
  // Se isso disparar, um pixel real foi descartado silenciosamente
  // porque o ciclo fantasma nao teve onde acontecer.
  always_ff @(posedge clk) begin
    if (rst_n && phantom_pending_r && i_valid) begin
      $error("window_3x3: violacao de contrato - i_valid ativo durante ciclo fantasma ",
             "(falta >=1 ciclo de gap entre linhas)");
    end
  end
  // synthesis translate_on

endmodule
