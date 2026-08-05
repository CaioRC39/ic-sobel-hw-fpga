`include "timescale.svh"

// line_buffer_2line
//
// Modulo comum (usado pelas 3 arquiteturas). Recebe um stream serial de
// pixels (1 por ciclo, quando i_valid=1) e produz, no mesmo ciclo, 3
// amostras alinhadas na mesma coluna mas vindas de linhas diferentes da
// imagem: a linha atual (o_curr), 1 linha acima (o_line1) e 2 linhas
// acima (o_line2).
//
// Implementado como 2 estagios de atraso em cascata, cada um de
// profundidade IMG_WIDTH ciclos (uma FIFO circular com leitura
// SINCRONA/registrada - BRAM-friendly). Ver
// docs/ARQUITETURA_MULTICICLO.md, secao "Modulos Comuns > line_buffer_2line"
// para a justificativa completa de projeto, incluindo a derivacao exata
// de por que o limiar de "aquecimento" precisa ser IMG_WIDTH+1 (e nao
// IMG_WIDTH) para compensar a latencia de 1 ciclo da leitura registrada.
//
// Contrato de interface: este modulo NAO tem nocao de "fim de linha" ou
// "fim de frame" - ele apenas atrasa o stream em IMG_WIDTH ciclos de
// i_valid=1. Cabe a quem o instancia (window_3x3, e futuramente um
// controlador de frame) interpretar a geometria da imagem.
module line_buffer_2line #(
    parameter int DATA_WIDTH = 8,
    parameter int IMG_WIDTH  = 8
) (
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic                  i_valid,
    input  logic [DATA_WIDTH-1:0] i_pixel,
    output logic                  o_valid,
    output logic [DATA_WIDTH-1:0] o_curr,
    output logic [DATA_WIDTH-1:0] o_line1,
    output logic [DATA_WIDTH-1:0] o_line2
);

  localparam int PtrWidth = $clog2(IMG_WIDTH);
  // +1: precisa contar ate IMG_WIDTH+1 (nao so IMG_WIDTH), ver comentario
  // no limiar de warm1/warm2 abaixo.
  localparam int WarmupWidth = $clog2(IMG_WIDTH + 2);
  localparam logic [PtrWidth-1:0] LastPtr = (IMG_WIDTH - 1);
  // Limiar de "aquecido": IMG_WIDTH+1, nao IMG_WIDTH. A leitura de mem1 e
  // registrada (read-antes-do-write no MESMO endereco do write deste
  // ciclo, resultado disponivel so no ciclo SEGUINTE) - isso da IMG_WIDTH
  // ciclos de atraso de armazenamento + 1 ciclo de latencia do proprio
  // registro de leitura = IMG_WIDTH+1 ciclos totais ate o primeiro dado
  // real e valido aparecer. Usar o limiar IMG_WIDTH (sem o +1) deixa
  // warm1 "verdadeiro" 1 ciclo cedo demais, vazando X (memoria nunca
  // escrita) para a saida logo na transicao - bug real, encontrado e
  // corrigido durante os testes deste modulo.
  localparam logic [WarmupWidth-1:0] WarmThresh = (IMG_WIDTH + 1);

  // ---------------------------------------------------------------------
  // Estagio 1: atraso de 1 linha completa (IMG_WIDTH ciclos de i_valid)
  // ---------------------------------------------------------------------
  logic [ DATA_WIDTH-1:0] mem1          [IMG_WIDTH];
  logic [   PtrWidth-1:0] wr_ptr1_r;
  logic [ DATA_WIDTH-1:0] rd_data1_r;
  logic [WarmupWidth-1:0] warmup1_cnt_r;
  logic                   warm1;

  assign warm1 = (warmup1_cnt_r >= WarmThresh);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wr_ptr1_r     <= '0;
      rd_data1_r    <= '0;
      warmup1_cnt_r <= '0;
    end else if (i_valid) begin
      // Le a posicao ANTES de escrever: e o valor gravado IMG_WIDTH
      // ciclos atras (mesma coluna, 1 linha acima). Resultado registrado
      // -> so fica visivel no ciclo seguinte (BRAM-friendly).
      rd_data1_r <= mem1[wr_ptr1_r];
      mem1[wr_ptr1_r] <= i_pixel;
      wr_ptr1_r <= (wr_ptr1_r == LastPtr) ? '0 : (wr_ptr1_r + 1'b1);
      if (!warm1) warmup1_cnt_r <= warmup1_cnt_r + 1'b1;
    end
  end

  logic [DATA_WIDTH-1:0] line1_val;
  // Zero-padding enquanto nao aquecido - nao dependemos do conteudo de
  // mem1 estar zerado no reset (memorias reais/BRAM nao resetam
  // instantaneamente de qualquer forma).
  assign line1_val = warm1 ? rd_data1_r : {DATA_WIDTH{1'b0}};

  // ---------------------------------------------------------------------
  // Estagio 2: mais 1 linha de atraso, alimentado pela saida do estagio 1
  // ---------------------------------------------------------------------
  // Leitura COMBINACIONAL aqui (nao registrada como no estagio 1) e
  // proposital, nao inconsistencia: line1_val (o dado escrito em mem2)
  // ja e ele mesmo derivado de um registro (rd_data1_r) do estagio 1.
  // Se o estagio 2 TAMBEM usasse leitura registrada, os 2 ciclos de
  // latencia de leitura se acumulariam, dando 2*IMG_WIDTH+1 ciclos de
  // atraso total em vez de exatamente 2*IMG_WIDTH (confirmado testando:
  // com leitura registrada nos dois estagios, o_line2 chegava 1 ciclo
  // atrasado). A leitura combinacional do estagio 2 compensa exatamente
  // esse ciclo extra, fechando o atraso total em 2*IMG_WIDTH ciclos e
  // mantendo o_curr/o_line1/o_line2 alinhados na mesma logica de coluna.
  logic [ DATA_WIDTH-1:0] mem2          [IMG_WIDTH];
  logic [   PtrWidth-1:0] wr_ptr2_r;
  logic [WarmupWidth-1:0] warmup2_cnt_r;
  logic                   warm2;

  // Limiar SIMPLES (IMG_WIDTH, sem +1) - ver comentario acima sobre por
  // que o estagio 2 nao precisa da mesma compensacao do estagio 1.
  assign warm2 = (warmup2_cnt_r >= IMG_WIDTH[WarmupWidth-1:0]);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wr_ptr2_r     <= '0;
      warmup2_cnt_r <= '0;
    end else if (i_valid) begin
      mem2[wr_ptr2_r] <= line1_val;
      wr_ptr2_r <= (wr_ptr2_r == LastPtr) ? '0 : (wr_ptr2_r + 1'b1);
      if (!warm2) warmup2_cnt_r <= warmup2_cnt_r + 1'b1;
    end
  end

  logic [DATA_WIDTH-1:0] line2_val;
  assign line2_val = warm2 ? mem2[wr_ptr2_r] : {DATA_WIDTH{1'b0}};

  // ---------------------------------------------------------------------
  // Saidas: curr e um passthrough combinacional; valid acompanha
  // i_valid diretamente (sem latencia extra neste nivel).
  // ---------------------------------------------------------------------
  assign o_valid = i_valid;
  assign o_curr = i_pixel;
  assign o_line1 = line1_val;
  assign o_line2 = line2_val;

endmodule
