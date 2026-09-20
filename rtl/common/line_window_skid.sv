`include "timescale.svh"

// line_window_skid
//
// Modulo comum, novo (Alternativa 1, "Metade 2", correcao do Achado
// F-16 - RESUMO_ESTADO_PROJETO.md, secao "Investigacao da Alternativa
// 1 para o F-16"). Absorve o descompasso de 1 ciclo que a Metade 1
// (curr/curr_tag/valid registrados em line_buffer_2line.sv) introduz
// entre a decisao de aceite de um pixel externo e a disponibilidade
// real do dado correspondente - sem essa peca, um gating direto do
// tipo "o_ready de window_3x3 deste ciclo libera i_valid deste mesmo
// ciclo" (usado ANTES desta correcao) fica incorreto, porque decisao e
// chegada do dado deixam de coincidir no tempo.
//
// Fica entre line_buffer_2line (ja com curr/curr_tag/valid
// registrados) e window_3x3, sem acoplar os dois modulos comuns entre
// si - cada um continua testavel isoladamente, exatamente como ja e
// hoje.
//
// Mesmo padrao ja validado em skid_fifo2.sv (usado entre window_3x3 e
// mac_control_fsm): contador de ocupacao (count_r) como UNICA fonte de
// verdade para cheio/vazio - nao comparacao de ponteiros (wr_ptr==
// rd_ptr e estruturalmente ambigua para profundidade >1: tanto vazio
// quanto cheio dao a mesma comparacao). Push aceito mesmo com o buffer
// cheio se houver pop simultaneo no mesmo ciclo (leitura combinacional
// usa o valor do registrador ANTES da borda; a escrita sincrona so
// vale a partir do ciclo seguinte - sem corrupcao real, mesmo
// escrevendo no endereco que esta sendo lido).
//
// DECISAO DE PROJETO (RESUMO_ESTADO_PROJETO.md, secao "Trade-off de
// fundir skid_fifo2.sv... com o novo skid"): module deliberadamente
// SEPARADO de skid_fifo2.sv, apesar da semelhanca estrutural. As 2
// profundidades resolvem perguntas empiricas DIFERENTES, medidas em
// pontos DIFERENTES do pipeline (aqui: descompasso de registro de 1
// ciclo entre line_buffer_2line e window_3x3; la: rajadas de janelas
// validas sem gap entre window_3x3 e mac_control_fsm) - coincidirem em
// profundidade 2 agora e acaso, nao motivo para uma abstracao unica
// prematura. Reabrir skid_fifo2.sv (ja fechado, testado, em uso real)
// sem necessidade funcional nova contraria CLAUDE.md secao 15.10/15.11.
//
// FORMULA DE o_room ("v2", menos conservadora que a 1a tentativa
// testada): considera tambem o `pop` deste MESMO ciclo (ja disponivel
// combinacionalmente), em vez de assumir o pior caso (pop=0) sempre -
// mesmo raciocinio ja validado em skid_fifo2.sv (push+pop na mesma
// posicao fisica, no mesmo ciclo, quando a fila esta cheia mas tambem
// esvaziando). Medido empiricamente (RESUMO_ESTADO_PROJETO.md, secao
// 3): com DEPTH=2, esta formula atinge o mesmo teto de throughput que
// uma formula mais conservadora so atingia com DEPTH=3 - DEPTH=2 e a
// profundidade recomendada, mesmo custo de area que uma formula pior,
// throughput no teto observado.
//
// NAO TESTADO AINDA no repositorio real: este modulo foi validado
// exaustivamente em ambiente de reproducao isolado (conteudo,
// handshake sob alimentacao continua, interacao com fronteira de
// frame/rearm), mas nunca dentro de sobel_multicycle.sv por completo,
// nem com uma imagem real (640x480) - ver RESUMO_ESTADO_PROJETO.md,
// "Proximos passos imediatos", item 4, para o que falta verificar.
//
// DIFERENCA DELIBERADA em relacao a skid_fifo2.sv, sinalizada aqui de
// proposito (nao escondida): skid_fifo2.sv PROTEGE a escrita em si
// contra overflow (skid_push_accepted exclui o caso cheio-sem-pop, a
// escrita simplesmente nao acontece). Este modulo, na forma
// EFETIVAMENTE TESTADA na investigacao, NAO tem essa protecao na
// escrita - a escrita acontece incondicionalmente em i_push, contando
// com o contrato de o_room (respeitado por quem gateia i_push) para
// que o caso de overflow nunca ocorra na pratica; o $error abaixo
// existe para pegar uma violacao desse contrato, nao para tornar o
// overflow seguro por si so. Adotar a mesma protecao de skid_fifo2.sv
// aqui e uma melhoria de robustez razoavel a considerar - mas NAO foi
// o que foi testado, entao nao esta incluida sem sinalizacao explicita.
module line_window_skid #(
    parameter int DATA_WIDTH = 8,
    parameter int DEPTH      = 2
) (
    input  logic                  clk,
    input  logic                  rst_n,
    // lado de entrada - line_buffer_2line (ja com curr/tag/valid registrados)
    input  logic                  i_push,
    input  logic [DATA_WIDTH-1:0] i_curr,
    input  logic [DATA_WIDTH-1:0] i_line1,
    input  logic [DATA_WIDTH-1:0] i_line2,
    input  logic                  i_curr_tag,
    input  logic                  i_line1_tag,
    input  logic                  i_line2_tag,
    output logic                  o_room,             // 1 = seguro aceitar novo pixel externo agora
    // lado de saida - window_3x3
    input  logic                  i_downstream_ready, // window_3x3.o_ready
    output logic                  o_valid,
    output logic [DATA_WIDTH-1:0] o_curr,
    output logic [DATA_WIDTH-1:0] o_line1,
    output logic [DATA_WIDTH-1:0] o_line2,
    output logic                  o_curr_tag,
    output logic                  o_line1_tag,
    output logic                  o_line2_tag,
    output logic                  o_overflow          // 1 = i_push descartado (cheio, sem pop) - contrato violado
);

  localparam int PW = 3 * DATA_WIDTH + 3;  // curr+line1+line2+3 tags
  localparam int PtrW = (DEPTH > 1) ? $clog2(DEPTH) : 1;
  localparam int CntW = $clog2(DEPTH + 1);

  logic [PW-1:0] mem[DEPTH];
  logic [PtrW-1:0] wr_ptr_r, rd_ptr_r;
  logic [CntW-1:0] count_r;

  logic pop;
  assign o_valid = (count_r != '0);
  assign pop = o_valid && i_downstream_ready;

  // o_room (formula v2): considera o pop deste mesmo ciclo, alem do
  // push que este ciclo ja vai empurrar (i_push, reflexo da decisao do
  // ciclo anterior) - evita superestimar ocupacao futura assumindo
  // sempre o pior caso (pop=0). pop so pode ser 1 quando count_r>=1
  // (o_valid=count_r!=0), entao a subtracao nunca fica negativa.
  logic [CntW:0] room_calc;
  assign room_calc = {1'b0, count_r} + {1'b0, CntW'(i_push)} - {1'b0, CntW'(pop)};
  assign o_room = room_calc < (CntW + 1)'(DEPTH);

  wire [PW-1:0] push_data = {i_curr, i_line1, i_line2, i_curr_tag, i_line1_tag, i_line2_tag};

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wr_ptr_r <= '0;
      rd_ptr_r <= '0;
      count_r  <= '0;
    end else begin
      if (i_push) begin
        mem[wr_ptr_r] <= push_data;
        wr_ptr_r <= (DEPTH == 1) ? '0 : ((wr_ptr_r == PtrW'(DEPTH - 1)) ? '0 : wr_ptr_r + 1'b1);
      end
      if (pop) begin
        rd_ptr_r <= (DEPTH == 1) ? '0 : ((rd_ptr_r == PtrW'(DEPTH - 1)) ? '0 : rd_ptr_r + 1'b1);
      end
      unique case ({i_push, pop})
        2'b10:   count_r <= count_r + 1'b1;
        2'b01:   count_r <= count_r - 1'b1;
        default: count_r <= count_r;
      endcase
    end
  end

  logic [PW-1:0] rd_word;
  assign rd_word = mem[rd_ptr_r];
  assign {o_curr, o_line1, o_line2, o_curr_tag, o_line1_tag, o_line2_tag} = rd_word;

  assign o_overflow = i_push && (count_r == CntW'(DEPTH)) && !pop;

  // synthesis translate_off
  // Checagem de simulacao: violacao do contrato de interface (push com
  // o buffer cheio e sem pop simultaneo - quem gateia i_push via
  // o_room, seguindo o contrato, nunca deveria fazer isso acontecer).
  always_ff @(posedge clk) begin
    if (rst_n && o_overflow) begin
      $error("line_window_skid: overflow - i_push com o buffer cheio ",
             "e sem pop simultaneo, amostra seria perdida");
    end
  end
  // synthesis translate_on

endmodule
