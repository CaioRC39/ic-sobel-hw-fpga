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
// correspondente. O integrador (sobel_multicycle.sv) alterna essa tag
// a cada inicio de frame; e window_3x3.sv (a jusante) quem de fato
// compara as 3 tags da janela para detectar contaminacao de fronteira.
//
// Decisao de projeto (avaliada e fechada nesta sessao): a tag e
// EMPACOTADA na mesma palavra de memoria que o pixel (mem1/mem2
// passam de DATA_WIDTH para DATA_WIDTH+1 bits), em vez de uma cadeia
// de atraso paralela e independente para a tag. Isso garante POR
// CONSTRUCAO que a tag sofre exatamente o mesmo atraso que o pixel -
// reaproveita 100% da logica de enderecamento/aquecimento ja validada
// por 3 bugs reais, em vez de duplicar essa mesma logica numa 2a
// estrutura que poderia divergir dela silenciosamente no futuro.
//
// ALTERADO AQUI (correcao do Achado F-16, Alternativa 1 - "Metade 1",
// RESUMO_ESTADO_PROJETO.md, secao "Investigacao da Alternativa 1 para
// o F-16"): a causa raiz do F-16 e uma assimetria de latencia dentro
// deste proprio modulo. o_line1/o_line2 sao derivados de um mux sobre
// um REGISTRADOR (rd_data1_r/mem2[...]) que atualiza na MESMA borda em
// que um consumidor sincrono direto (window_3x3) os amostra - por
// semantica sincrona padrao, isso da a o_line1/o_line2 1 ciclo INTEIRO
// a mais de latencia efetiva do que o_curr, que ate esta correcao era
// um *wire* puro (assign o_curr = i_pixel, latencia 0). Um consumidor
// sincrono ligado diretamente (sem registro entre modulos) via, a cada
// janela, o_curr de um instante e o_line1/o_line2 de 1 instante antes -
// um desalinhamento sistematico, presente em TODO ciclo de regime
// permanente, nao so na transicao de aquecimento.
//
// A correcao: registrar o_curr/o_curr_tag/o_valid por 1 ciclo,
// igualando sua latencia "efetiva vista pelo consumidor" a que
// o_line1/o_line2 ja tinham por construcao. curr_r acompanha i_valid
// INCONDICIONALMENTE (e o proprio "valid" deste estagio - precisa
// cair corretamente numa folga externa). curr_pix_r/curr_tag_r, por
// outro lado, SO atualizam quando i_valid=1 - mesma convencao
// "else if (i_valid)" ja usada no resto do modulo (warmup1_cnt_r,
// mem1, mem2). Sem esse "if", curr_tag_r capturaria i_tag "ao vivo"
// mesmo em ciclos sem pixel real - inclusive no proprio ciclo de um
// pulso de i_rearm - criando, por 1 ciclo, um item com curr_tag
// desalinhado de line1_tag/line2_tag (que reagem ao rearm no mesmo
// ciclo, sem este registro extra). Bug real, encontrado e corrigido
// durante a investigacao (driver de teste que zerava i_tag em folga
// mascarou esse efeito por varias rodadas - ver RESUMO_ESTADO_PROJETO.md,
// secao 6-bis, para o diagnostico completo).
//
// CONTRATO DE INTERFACE (documentado, sem defesa interna - decisao
// registrada em RESUMO_ESTADO_PROJETO.md, secao 11, Opcao A escolhida
// sobre Opcao B): line1_tag/line2_tag continuam lendo i_tag AO VIVO
// (sem registro) no ramo "nao aquecido" (tag1_val/tag2_val, abaixo) -
// isso so e seguro se i_tag permanecer ESTAVEL durante qualquer ciclo,
// valido ou nao (o mesmo tipo de contrato ja exigido por window_3x3.sv
// para o gap horizontal entre linhas). O unico uso real deste modulo
// (sobel_multicycle.sv) ja respeita isso: i_tag = frame_tag_r, um
// registrador que so muda 1x por frame, nunca durante uma folga. Um
// registrador defensivo aqui (ex: capturando i_tag so em i_valid=1
// para uso interno) reintroduziria exatamente a categoria de risco -
// mais um registrador com latencia propria, mais uma chance de
// descompasso - que esta correcao inteira existe para eliminar.
//
// Consequencia da correcao: a saida deste modulo (curr/curr_tag/valid)
// passa a ter 1 ciclo A MAIS de latencia total do que antes. Um
// consumidor sincrono ligado DIRETAMENTE (sem nenhum estagio elastico
// entre os dois) deixa de funcionar corretamente, porque a decisao de
// aceite (baseada no o_ready do consumidor) e a disponibilidade real
// do dado deixam de coincidir no mesmo ciclo. Por isso, esta correcao
// e usada em conjunto com um novo modulo elastico
// (line_window_skid.sv) entre este modulo e window_3x3 - ver esse
// modulo e sobel_multicycle.sv para o desenho completo do handshake.
module line_buffer_2line #(
    parameter int DATA_WIDTH = 8,
    parameter int IMG_WIDTH  = 8
) (
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic                  i_valid,
    input  logic [DATA_WIDTH-1:0] i_pixel,
    input  logic                  i_tag,        // tag de proveniencia (Alternativa 3-B)
    input  logic                  i_rearm,      // pulso: re-arma aquecimento (Alternativa 3-C)
    output logic                  o_valid,
    output logic [DATA_WIDTH-1:0] o_curr,
    output logic [DATA_WIDTH-1:0] o_line1,      // linha y-1
    output logic [DATA_WIDTH-1:0] o_line2,      // linha y-2
    output logic                  o_curr_tag,   // tag registrada em lockstep com o_curr
    output logic                  o_line1_tag,  // tag em lockstep c/ o_line1
    output logic                  o_line2_tag   // tag em lockstep c/ o_line2
);

  localparam int PtrWidth = $clog2(IMG_WIDTH);
  // +1: precisa contar ate IMG_WIDTH+1 (nao so IMG_WIDTH), ver comentario
  // no limiar de warm1/warm2 abaixo.
  localparam int WarmupWidth = $clog2(IMG_WIDTH + 2);
  localparam logic [PtrWidth-1:0] LastPtr = PtrWidth'(IMG_WIDTH - 1);
  // Limiar de "aquecido": IMG_WIDTH+1, nao IMG_WIDTH. A leitura de mem1 e
  // registrada (read-antes-do-write no MESMO endereco do write deste
  // ciclo, resultado disponivel so no ciclo SEGUINTE) - isso da IMG_WIDTH
  // ciclos de atraso de armazenamento + 1 ciclo de latencia do proprio
  // registro de leitura = IMG_WIDTH+1 ciclos totais ate o primeiro dado
  // real e valido aparecer.
  localparam logic [WarmupWidth-1:0] WarmThresh = WarmupWidth'(IMG_WIDTH + 1);

  // Largura da palavra armazenada em mem1/mem2 inclui a tag de
  // proveniencia, empacotada junto do pixel. Layout de cada palavra:
  // bit MSB (indice DATA_WIDTH) = tag; bits [DATA_WIDTH-1:0] = pixel.
  localparam int PixTagWidth = DATA_WIDTH + 1;

  // ---------------------------------------------------------------------
  // Estagio 1: atraso de 1 linha completa (IMG_WIDTH ciclos de i_valid)
  // ---------------------------------------------------------------------
  logic [PixTagWidth-1:0] mem1          [IMG_WIDTH];
  logic [   PtrWidth-1:0] wr_ptr1_r;
  logic [PixTagWidth-1:0] rd_data1_r;
  logic [WarmupWidth-1:0] warmup1_cnt_r;
  logic                   warm1;

  // warm1 e combinacional sobre warmup1_cnt_r, que so reflete o rearm 1
  // ciclo DEPOIS de i_rearm=1 (reset sincrono). Sem este AND, no proprio
  // ciclo do rearm warm1 ainda mostra o valor SATURADO do fim do frame
  // anterior, lendo mem1 com dado residual antes da 1a escrita do novo
  // frame.
  assign warm1 = (warmup1_cnt_r >= WarmThresh) && !i_rearm;

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
      mem1[wr_ptr1_r] <= {i_tag, i_pixel};
      wr_ptr1_r <= (wr_ptr1_r == LastPtr) ? '0 : (wr_ptr1_r + 1'b1);
      // i_rearm tem prioridade sobre o incremento normal - forca
      // warmup1_cnt_r de volta a 1 (contando o proprio pulso) no primeiro
      // ciclo de cada novo frame, fazendo warm1 voltar a falso e o
      // zero-padding de borda superior se repetir a cada fronteira de
      // frame, nao so no power-up.
      if (i_rearm) warmup1_cnt_r <= 1'b1;
      else if (!warm1) warmup1_cnt_r <= warmup1_cnt_r + 1'b1;
    end
  end

  logic [DATA_WIDTH-1:0] line1_val;
  logic                  tag1_val;
  // Zero-padding enquanto nao aquecido - nao dependemos do conteudo de
  // mem1 estar zerado no reset (memorias reais/BRAM nao resetam
  // instantaneamente de qualquer forma).
  assign line1_val = warm1 ? rd_data1_r[DATA_WIDTH-1:0] : {DATA_WIDTH{1'b0}};
  // Enquanto nao aquecido, o zero-padding representa a BORDA SUPERIOR
  // da imagem (dentro do MESMO frame que esta entrando agora) - herda
  // i_tag, para nao ser confundido com contaminacao de fronteira entre
  // frames. Depois de aquecido, e a tag REAL empacotada quem decide - e
  // e exatamente essa tag real que revela dado remanescente do frame
  // ANTERIOR ainda residente na memoria circular (a causa raiz do
  // Achado F-02, resolvida pela Alternativa 3-C via i_rearm).
  assign tag1_val = warm1 ? rd_data1_r[DATA_WIDTH] : i_tag;

  // ---------------------------------------------------------------------
  // Estagio 2: mais 1 linha de atraso, alimentado pela saida do estagio 1
  // ---------------------------------------------------------------------
  // Leitura COMBINACIONAL aqui (nao registrada como no estagio 1) e
  // proposital: line1_val (o dado escrito em mem2) ja e ele mesmo
  // derivado de um registro (rd_data1_r) do estagio 1. Se o estagio 2
  // TAMBEM usasse leitura registrada, os 2 ciclos de latencia de leitura
  // se acumulariam, dando 2*IMG_WIDTH+1 ciclos de atraso total em vez de
  // exatamente 2*IMG_WIDTH.
  logic [PixTagWidth-1:0] mem2          [IMG_WIDTH];
  logic [   PtrWidth-1:0] wr_ptr2_r;
  logic [WarmupWidth-1:0] warmup2_cnt_r;
  logic                   warm2;

  // Limiar SIMPLES (IMG_WIDTH, sem +1) - o estagio 2 nao precisa da
  // mesma compensacao do estagio 1 (ver justificativa acima).
  assign warm2 = (warmup2_cnt_r >= IMG_WIDTH[WarmupWidth-1:0]) && !i_rearm;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wr_ptr2_r     <= '0;
      warmup2_cnt_r <= '0;
    end else if (i_valid) begin
      mem2[wr_ptr2_r] <= {tag1_val, line1_val};
      wr_ptr2_r <= (wr_ptr2_r == LastPtr) ? '0 : (wr_ptr2_r + 1'b1);
      if (i_rearm) warmup2_cnt_r <= 1'b1;
      else if (!warm2) warmup2_cnt_r <= warmup2_cnt_r + 1'b1;
    end
  end

  logic [DATA_WIDTH-1:0] line2_val;
  logic                  tag2_val;
  assign line2_val = warm2 ? mem2[wr_ptr2_r][DATA_WIDTH-1:0] : {DATA_WIDTH{1'b0}};
  // Mesmo raciocinio do estagio 1 - borda superior (nao aquecido)
  // herda i_tag; depois de aquecido, a tag empacotada real decide.
  assign tag2_val = warm2 ? mem2[wr_ptr2_r][DATA_WIDTH] : i_tag;

  // ---------------------------------------------------------------------
  // ALTERADO AQUI (correcao do Achado F-16, Alternativa 1 - Metade 1):
  // curr/curr_tag/valid passam a ser registrados, ver justificativa
  // completa no cabecalho do modulo. curr_r acompanha i_valid
  // incondicionalmente; curr_pix_r/curr_tag_r so atualizam quando
  // i_valid=1, evitando capturar i_tag "ao vivo" em ciclos sem pixel
  // real.
  // ---------------------------------------------------------------------
  logic                  curr_r;
  logic [DATA_WIDTH-1:0] curr_pix_r;
  logic                  curr_tag_r;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      curr_r     <= 1'b0;
      curr_pix_r <= '0;
      curr_tag_r <= 1'b0;
    end else begin
      curr_r <= i_valid;
      if (i_valid) begin
        curr_pix_r <= i_pixel;
        curr_tag_r <= i_tag;
      end
    end
  end

  assign o_valid = curr_r;
  assign o_curr = curr_pix_r;
  assign o_line1 = line1_val;
  assign o_line2 = line2_val;
  assign o_curr_tag = curr_tag_r;
  assign o_line1_tag = tag1_val;
  assign o_line2_tag = tag2_val;

endmodule
