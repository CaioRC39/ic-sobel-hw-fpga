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
//
// ALTERADO AQUI (Alternativa 3-B, RESUMO_ESTADO_PROJETO.md, secao
// "Design fechado - prevencao estrutural do bug de fronteira de
// frame", motivada pelo Achado F-02 da Auditoria 01): alem do pixel,
// o modulo agora propaga uma TAG de proveniencia de 1 bit
// (i_tag -> o_curr_tag/o_line1_tag/o_line2_tag), no MESMO padrao ja
// usado para o_curr/o_line1/o_line2 - passthrough puro, nunca
// interpretado por este modulo, atrasado em LOCKSTEP com o pixel
// correspondente. O integrador (sobel_multicycle.sv, ainda a
// implementar) alterna essa tag a cada inicio de frame; e
// window_3x3.sv (a jusante) quem de fato compara as 3 tags da janela
// para detectar contaminacao de fronteira entre frames.
//
// Decisao de projeto (avaliada e fechada nesta sessao): a tag e
// EMPACOTADA na mesma palavra de memoria que o pixel (mem1/mem2
// passam de DATA_WIDTH para DATA_WIDTH+1 bits), em vez de uma cadeia
// de atraso paralela e independente para a tag. Isso garante POR
// CONSTRUCAO que a tag sofre exatamente o mesmo atraso que o pixel -
// reaproveita 100% da logica de enderecamento/aquecimento ja validada
// por 3 bugs reais (secao 4.1 acima), em vez de duplicar essa mesma
// logica numa 2a estrutura que poderia divergir dela silenciosamente
// no futuro (2 fontes de verdade para o mesmo atraso).
module line_buffer_2line #(
    parameter int DATA_WIDTH = 8,
    parameter int IMG_WIDTH  = 8
) (
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic                  i_valid,
    input  logic [DATA_WIDTH-1:0] i_pixel,
    input  logic                  i_tag,        // ALTERADO AQUI (3-B) - tag de proveniencia
    input  logic                  i_rearm,      // ALTERADO AQUI (3-C) - pulso: re-arma aquecimento
    output logic                  o_valid,
    output logic [DATA_WIDTH-1:0] o_curr,
    output logic [DATA_WIDTH-1:0] o_line1,      // linha y-1
    output logic [DATA_WIDTH-1:0] o_line2,      // linha y-2
    output logic                  o_curr_tag,   // ALTERADO AQUI (3-B) - passthrough de i_tag
    output logic                  o_line1_tag,  // ALTERADO AQUI (3-B) - tag em lockstep c/ o_line1
    output logic                  o_line2_tag   // ALTERADO AQUI (3-B) - tag em lockstep c/ o_line2
);

  localparam int PtrWidth = $clog2(IMG_WIDTH);
  // +1: precisa contar ate IMG_WIDTH+1 (nao so IMG_WIDTH), ver comentario
  // no limiar de warm1/warm2 abaixo.
  localparam int WarmupWidth = $clog2(IMG_WIDTH + 2);
  // ALTERADO AQUI (A-10): cast explicito - IMG_WIDTH-1 sempre cabe em
  // PtrWidth bits por construcao (PtrWidth = $clog2(IMG_WIDTH)); o cast so
  // declara isso ao Verilator, eliminando o warning WIDTHTRUNC sem mudar
  // o valor calculado.
  localparam logic [PtrWidth-1:0] LastPtr = PtrWidth'(IMG_WIDTH - 1);
  // Limiar de "aquecido": IMG_WIDTH+1, nao IMG_WIDTH. A leitura de mem1 e
  // registrada (read-antes-do-write no MESMO endereco do write deste
  // ciclo, resultado disponivel so no ciclo SEGUINTE) - isso da IMG_WIDTH
  // ciclos de atraso de armazenamento + 1 ciclo de latencia do proprio
  // registro de leitura = IMG_WIDTH+1 ciclos totais ate o primeiro dado
  // real e valido aparecer. Usar o limiar IMG_WIDTH (sem o +1) deixa
  // warm1 "verdadeiro" 1 ciclo cedo demais, vazando X (memoria nunca
  // escrita) para a saida logo na transicao - bug real, encontrado e
  // corrigido durante os testes deste modulo.
  // ALTERADO AQUI (A-10): mesmo raciocinio de LastPtr acima - IMG_WIDTH+1
  // sempre cabe em WarmupWidth bits por construcao (ver comentario de
  // WarmupWidth = $clog2(IMG_WIDTH + 2), acima).
  localparam logic [WarmupWidth-1:0] WarmThresh = WarmupWidth'(IMG_WIDTH + 1);

  // ALTERADO AQUI (3-B): largura da palavra armazenada em mem1/mem2
  // passa a incluir a tag de proveniencia, empacotada junto do pixel -
  // ver justificativa no cabecalho do modulo. Layout de cada palavra:
  // bit MSB (indice DATA_WIDTH) = tag; bits [DATA_WIDTH-1:0] = pixel.
  localparam int PixTagWidth = DATA_WIDTH + 1;

  // ---------------------------------------------------------------------
  // Estagio 1: atraso de 1 linha completa (IMG_WIDTH ciclos de i_valid)
  // ---------------------------------------------------------------------
  logic [PixTagWidth-1:0] mem1          [IMG_WIDTH];  // ALTERADO AQUI (3-B) - +1 bit (tag)
  logic [   PtrWidth-1:0] wr_ptr1_r;
  logic [PixTagWidth-1:0] rd_data1_r;                 // ALTERADO AQUI (3-B) - +1 bit (tag)
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
      mem1[wr_ptr1_r] <= {i_tag, i_pixel};  // ALTERADO AQUI (3-B) - tag empacotada com o pixel
      wr_ptr1_r <= (wr_ptr1_r == LastPtr) ? '0 : (wr_ptr1_r + 1'b1);
      // ALTERADO AQUI (3-C): i_rearm tem prioridade sobre o
      // incremento normal - forca warmup1_cnt_r de volta a 0 no
      // primeiro ciclo de cada novo frame, fazendo warm1 voltar a
      // falso e o zero-padding de borda superior se repetir a cada
      // fronteira de frame, nao so no power-up.
      if (i_rearm) warmup1_cnt_r <= '0;
      else if (!warm1) warmup1_cnt_r <= warmup1_cnt_r + 1'b1;
    end
  end

  logic [DATA_WIDTH-1:0] line1_val;
  logic                  tag1_val;  // ALTERADO AQUI (3-B)
  // Zero-padding enquanto nao aquecido - nao dependemos do conteudo de
  // mem1 estar zerado no reset (memorias reais/BRAM nao resetam
  // instantaneamente de qualquer forma).
  assign line1_val = warm1 ? rd_data1_r[DATA_WIDTH-1:0] : {DATA_WIDTH{1'b0}};
  // ALTERADO AQUI (3-B): enquanto nao aquecido, o zero-padding
  // representa a BORDA SUPERIOR da imagem (dentro do MESMO frame que
  // esta entrando agora) - herda i_tag, para nao ser confundido com
  // contaminacao de fronteira entre frames (mesmo raciocinio do
  // "ciclo fantasma" de window_3x3.sv, secao 4.2). Depois de aquecido,
  // e a tag REAL empacotada (rd_data1_r[DATA_WIDTH]) quem decide - e e
  // exatamente essa tag real que revela dado remanescente do frame
  // ANTERIOR ainda residente na memoria circular (a causa raiz do
  // Achado F-02 que esta Alternativa 3-B resolve).
  assign tag1_val = warm1 ? rd_data1_r[DATA_WIDTH] : i_tag;

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
  logic [PixTagWidth-1:0] mem2          [IMG_WIDTH];  // ALTERADO AQUI (3-B) - +1 bit (tag)
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
      mem2[wr_ptr2_r] <= {tag1_val, line1_val};  // ALTERADO AQUI (3-B) - mesmo padrao do estagio 1
      wr_ptr2_r <= (wr_ptr2_r == LastPtr) ? '0 : (wr_ptr2_r + 1'b1);
      // ALTERADO AQUI (3-C): mesmo raciocinio do estagio 1.
      if (i_rearm) warmup2_cnt_r <= '0;
      else if (!warm2) warmup2_cnt_r <= warmup2_cnt_r + 1'b1;
    end
  end

  logic [DATA_WIDTH-1:0] line2_val;
  logic                  tag2_val;  // ALTERADO AQUI (3-B)
  assign line2_val = warm2 ? mem2[wr_ptr2_r][DATA_WIDTH-1:0] : {DATA_WIDTH{1'b0}};
  // ALTERADO AQUI (3-B): mesmo raciocinio do estagio 1 - borda
  // superior (nao aquecido) herda i_tag; depois de aquecido, a tag
  // empacotada real decide.
  assign tag2_val = warm2 ? mem2[wr_ptr2_r][DATA_WIDTH] : i_tag;

  // ---------------------------------------------------------------------
  // Saidas: curr e um passthrough combinacional; valid acompanha
  // i_valid diretamente (sem latencia extra neste nivel).
  // ---------------------------------------------------------------------
  assign o_valid = i_valid;
  assign o_curr = i_pixel;
  assign o_line1 = line1_val;
  assign o_line2 = line2_val;
  // ALTERADO AQUI (3-B): tags de saida, mesmo padrao/lockstep de
  // o_curr/o_line1/o_line2 - o_curr_tag e passthrough puro (mesmo
  // ciclo de i_tag, sem nenhuma latencia extra neste nivel);
  // o_line1_tag/o_line2_tag saem do mesmo caminho de atraso empacotado
  // que o pixel correspondente, garantindo lockstep por construcao.
  assign o_curr_tag = i_tag;
  assign o_line1_tag = tag1_val;
  assign o_line2_tag = tag2_val;

endmodule
