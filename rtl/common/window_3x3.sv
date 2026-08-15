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
// ALTERADO AQUI: alem do $error (alarme passivo, so em simulacao), o
// modulo agora expoe o_ready (trava ativa, sintetizavel, sobrevive em
// hardware real) - o jeito CORRETO de nunca violar o contrato acima e
// simplesmente nunca apresentar i_valid=1 quando o_ready=0, em vez de
// calcular manualmente quando o gap deveria acontecer. Quem respeita
// o_ready nunca viola o contrato, mesmo sem saber nada sobre
// col_cnt_r ou IMG_WIDTH.
//
// Este modulo NAO trata a borda inferior do frame (ultima linha da
// imagem) - isso exige uma linha fantasma extra de zeros ao final do
// frame, responsabilidade de um controlador de nivel superior (fora do
// escopo deste modulo, que nao tem nocao de altura de imagem).
//
// ALTERADO AQUI (Alternativa 3-B, RESUMO_ESTADO_PROJETO.md, secao
// "Design fechado - prevencao estrutural do bug de fronteira de
// frame", motivada pelo Achado F-02 da Auditoria 01): o modulo recebe
// agora 3 tags de proveniencia (i_curr_tag/i_line1_tag/i_line2_tag,
// vindas de line_buffer_2line.sv em lockstep com i_curr/i_line1/
// i_line2) e mantem 3 shift-registers de tag PROPRIOS, na MESMA
// estrutura/temporizacao dos 3 shift-registers de pixel ja existentes
// (tag_row0_r/tag_row1_r/tag_row2_r espelham sr_row0_r/sr_row1_r/
// sr_row2_r posicao a posicao). Isso e deliberado, nao redundante: a
// janela 3x3 e formada por ate 3 ciclos de historico POR LINHA, entao
// comparar so a tag "de chegada" do ciclo atual NAO cobriria o caso em
// que uma janela ainda contem, nas posicoes mais antigas do shift
// register, pixels de um frame anterior que ainda nao foram
// "empurrados para fora" pelo deslizamento horizontal - exatamente o
// cenario de contaminacao de fronteira que esta alternativa existe
// para cobrir.
//
// o_window_valid_geom (novo) e 1 quando as 9 tags da janela (3 linhas
// x 3 colunas) sao TODAS iguais entre si - geometricamente pura, sem
// nenhuma amostra remanescente de outro frame. Segue a MESMA convencao
// de o_window: so tem significado quando o_valid=1 (nao e gated
// internamente, mesmo padrao ja usado pelo proprio o_window).
//
// o_tag (novo) e a tag "nominal" da janela como um todo - passthrough
// da tag da LINHA CENTRAL (i_line1_tag), a mesma linha em que a janela
// esta CENTRADA por convencao (ver comentario de mapeamento no topo
// deste cabecalho). Pensado para um futuro consumidor (ex: um
// controlador de frame em sobel_multicycle.sv) que precise continuar
// propagando a tag adiante sem reconstruir o raciocinio de qual das 3
// linhas usar como referencia.
//
// O ciclo fantasma da borda direita (ver phantom_pending_r abaixo)
// desliza um ZERO de pixel para dentro da janela - mas a tag que
// acompanha esse zero fantasma continua sendo a tag REAL da ultima
// coluna de cada linha (o shift register de tag simplesmente repete o
// valor que ja estava na posicao mais recente, em vez de deslizar uma
// tag nova) - o zero fantasma representa borda DENTRO do mesmo frame,
// nunca deveria por si so derrubar o_window_valid_geom.
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
    input  logic                    i_curr_tag,           // ALTERADO AQUI (3-B)
    input  logic                    i_line1_tag,          // ALTERADO AQUI (3-B)
    input  logic                    i_line2_tag,          // ALTERADO AQUI (3-B)
    output logic                    o_ready,  // trava ativa, ver ARQUITETURA_MULTICICLO.md secao 4.2
    output logic                    o_valid,
    output logic [9*DATA_WIDTH-1:0] o_window,             // vetor achatado, ver nota de layout
    output logic                    o_tag,                // ALTERADO AQUI (3-B) - tag da linha 1
    output logic                    o_window_valid_geom   // ALTERADO AQUI (3-B) - 1 = janela pura
);

  localparam int ColWidth = $clog2(IMG_WIDTH);
  // ALTERADO AQUI (A-10): cast explicito, mesmo raciocinio de
  // line_buffer_2line.sv/LastPtr - elimina o warning WIDTHTRUNC sem mudar
  // o valor calculado (ColWidth = $clog2(IMG_WIDTH) ja garante que cabe).
  localparam logic [ColWidth-1:0] LastCol = ColWidth'(IMG_WIDTH - 1);

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

  // ALTERADO AQUI (3-B): 3 shift-registers de tag, espelhando
  // sr_row0_r/sr_row1_r/sr_row2_r posicao a posicao (mesma
  // profundidade, mesmo timing de deslizamento) - ver justificativa no
  // cabecalho do modulo.
  logic tag_row0_r[3];
  logic tag_row1_r[3];
  logic tag_row2_r[3];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      col_cnt_r <= '0;
      phantom_pending_r <= 1'b0;
      valid_r <= 1'b0;
      for (int i = 0; i < 3; i++) begin
        sr_row0_r[i] <= '0;
        sr_row1_r[i] <= '0;
        sr_row2_r[i] <= '0;
        tag_row0_r[i] <= 1'b0;  // ALTERADO AQUI (3-B)
        tag_row1_r[i] <= 1'b0;  // ALTERADO AQUI (3-B)
        tag_row2_r[i] <= 1'b0;  // ALTERADO AQUI (3-B)
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
      // ALTERADO AQUI (3-B): o zero fantasma pertence ao MESMO frame
      // da ultima coluna real - a tag deslizada para a posicao mais
      // recente REPETE o valor que ja estava la (tag_rowX_r[0]), em
      // vez de introduzir uma tag nova. Ver cabecalho do modulo.
      tag_row0_r[2] <= tag_row0_r[1];
      tag_row0_r[1] <= tag_row0_r[0];
      tag_row0_r[0] <= tag_row0_r[0];
      tag_row1_r[2] <= tag_row1_r[1];
      tag_row1_r[1] <= tag_row1_r[0];
      tag_row1_r[0] <= tag_row1_r[0];
      tag_row2_r[2] <= tag_row2_r[1];
      tag_row2_r[1] <= tag_row2_r[0];
      tag_row2_r[0] <= tag_row2_r[0];
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
        // ALTERADO AQUI (3-B) - BUG REAL corrigido apos rodar o teste
        // test_window_valid_geom_detects_vertical_frame_boundary de
        // verdade: as posicoes [1]/[2] (ainda sem vizinho esquerdo
        // real) precisam herdar a tag ATUAL (mesmo raciocinio do
        // ciclo fantasma da borda direita, e do zero-padding em
        // line_buffer_2line.sv) - NAO um 1'b0 fixo. Um 1'b0 fixo aqui
        // fazia toda janela nas 2 primeiras colunas de QUALQUER linha
        // reportar falsamente o_window_valid_geom=0 sempre que a tag
        // do frame corrente fosse 1 (a comparacao via tag_and/tag_or
        // via de calcular incorretamente 2 "frames" diferentes onde
        // so havia 1). Pixel usa '0 porque zero e um valor real de
        // padding; tag NAO tem um "valor neutro" equivalente - precisa
        // ser a tag verdadeira da amostra que esta entrando.
        tag_row0_r[0] <= i_line2_tag;  // ALTERADO AQUI (3-B)
        tag_row0_r[1] <= i_line2_tag;
        tag_row0_r[2] <= i_line2_tag;
        tag_row1_r[0] <= i_line1_tag;  // ALTERADO AQUI (3-B)
        tag_row1_r[1] <= i_line1_tag;
        tag_row1_r[2] <= i_line1_tag;
        tag_row2_r[0] <= i_curr_tag;  // ALTERADO AQUI (3-B)
        tag_row2_r[1] <= i_curr_tag;
        tag_row2_r[2] <= i_curr_tag;
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
        tag_row0_r[2] <= tag_row0_r[1];  // ALTERADO AQUI (3-B)
        tag_row0_r[1] <= tag_row0_r[0];
        tag_row0_r[0] <= i_line2_tag;
        tag_row1_r[2] <= tag_row1_r[1];  // ALTERADO AQUI (3-B)
        tag_row1_r[1] <= tag_row1_r[0];
        tag_row1_r[0] <= i_line1_tag;
        tag_row2_r[2] <= tag_row2_r[1];  // ALTERADO AQUI (3-B)
        tag_row2_r[1] <= tag_row2_r[0];
        tag_row2_r[0] <= i_curr_tag;
        valid_r <= 1'b1;
      end
      col_cnt_r <= is_last_col ? '0 : (col_cnt_r + 1'b1);
      if (is_last_col) phantom_pending_r <= 1'b1;
    end else begin
      valid_r <= 1'b0;
    end
  end

  assign o_valid = valid_r;

  // ALTERADO AQUI: trava ativa - "pronto pra receber pixel novo" e o
  // OPOSTO de "estou no ciclo fantasma agora". phantom_pending_r ja
  // existia internamente (o modulo ja se protegia sozinho, dando
  // prioridade ao ciclo fantasma mesmo sem isto) - esta atribuicao so
  // torna essa protecao OBSERVAVEL por quem instancia o modulo, sem
  // adicionar nenhum flip-flop novo (reaproveita um sinal que ja
  // existia). Ver docs/ARQUITETURA_MULTICICLO.md, secao 4.2, para o
  // contrato completo.
  assign o_ready = !phantom_pending_r;

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

  // ALTERADO AQUI (3-B): tag nominal da janela = tag da linha central
  // (i_line1_tag), a posicao mais recente do shift register do meio -
  // mesma convencao de centralizacao ja documentada no cabecalho do
  // modulo ("a janela emitida ... esta CENTRADA na linha de i_line1").
  assign o_tag = tag_row1_r[0];

  // ALTERADO AQUI (3-B): geometricamente pura <=> as 9 tags da janela
  // sao TODAS iguais entre si. Truque de reducao para largura 1 bit:
  // AND de todos os bits == OR de todos os bits so pode ser verdade se
  // todos forem identicos (ou todos 0, ou todos 1) - equivalente a uma
  // comparacao par-a-par exaustiva (36 pares), mas sem escrever os 36
  // pares.
  logic tag_and, tag_or;
  assign tag_and = tag_row0_r[0] & tag_row0_r[1] & tag_row0_r[2] &
                   tag_row1_r[0] & tag_row1_r[1] & tag_row1_r[2] &
                   tag_row2_r[0] & tag_row2_r[1] & tag_row2_r[2];
  assign tag_or  = tag_row0_r[0] | tag_row0_r[1] | tag_row0_r[2] |
                   tag_row1_r[0] | tag_row1_r[1] | tag_row1_r[2] |
                   tag_row2_r[0] | tag_row2_r[1] | tag_row2_r[2];
  assign o_window_valid_geom = (tag_and == tag_or);

  // synthesis translate_off
  // Checagem de simulacao: violacao do contrato de gap entre linhas.
  // Se isso disparar, um pixel real foi descartado silenciosamente
  // porque o ciclo fantasma nao teve onde acontecer.
  // ALTERADO AQUI (F-09/A-09): rst_n e lido aqui so como DADO (condicao do
  // $error), nunca como reset de fato - este bloco nao tem nenhum
  // flip-flop proprio de estado. O Verilator nao remove blocos
  // "synthesis translate_off/on" antes de lintar (ao contrario de
  // Vivado/Quartus na sintese real), entao compara esta leitura sincrona
  // de rst_n com o uso assincrono no always_ff principal do modulo e
  // aponta SYNCASYNCNET - falso-positivo confirmado por analise (ver
  // docs/AUDITORIA_01_PRE_MULTICICLO.md, F-09/A-09): nenhum hardware real
  // e afetado, ja que este bloco inteiro e removido na sintese.
  /* verilator lint_off SYNCASYNCNET */
  always_ff @(posedge clk) begin
    if (rst_n && phantom_pending_r && i_valid) begin
      $error("window_3x3: violacao de contrato - i_valid ativo durante ciclo fantasma ",
             "(falta >=1 ciclo de gap entre linhas)");
    end
  end
  /* verilator lint_on SYNCASYNCNET */
  // synthesis translate_on

endmodule
