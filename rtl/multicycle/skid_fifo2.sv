`include "timescale.svh"

// skid_fifo2
//
// Modulo especifico da arquitetura multiciclo. Desacopla o stream de
// janelas 3x3 que window_3x3 produz (potencialmente varias seguidas,
// sem gap) do ritmo de consumo de mac_control_fsm (que leva ~15
// ciclos/pixel). Substitui o skid buffer de profundidade 1 anterior
// (bypass combinacional + 1 slot de reserva) por uma FIFO SINCRONA
// PURA de profundidade 2 (Alternativa "Opcao B", ver
// RESUMO_ESTADO_PROJETO.md, secao "Achado adicional... skid buffer",
// e docs/ARQUITETURA_MULTICICLO.md, secao do skid buffer, para a
// comparacao completa de trade-offs contra a Opcao A).
//
// Decisao de projeto central: o_valid/o_data SEMPRE vem de um
// registrador (skid_mem_r), nunca ha bypass combinacional de
// i_push_data direto para a saida. Custo: +1 ciclo de latencia fixa
// por janela, mesmo quando o consumidor ja estava pronto (irrelevante
// frente aos ~15 ciclos/pixel de mac_control_fsm). Beneficio: elimina
// por construcao a classe de bug de corrida entre modulos sincronos
// ligados combinacionalmente que ja causou o Achado F-16
// (line_buffer_2line <-> window_3x3, ver docs/ARQUITETURA_MULTICICLO.md
// secao 4.2.1) - aqui nao existe esse caminho combinacional para
// comecar.
//
// Contrato de interface (violavel, ver CLAUDE.md secao 15.3): quem
// dirige i_push NUNCA deveria apresentar i_push=1 com o buffer ja
// cheio (2 itens) E sem um pop simultaneo neste mesmo ciclo (i.e., sem
// i_downstream_ready=1 no mesmo ciclo, que libera 1 vaga). Isso ainda
// nao foi provado estruturalmente impossivel para toda configuracao/
// timing (ver RESUMO_ESTADO_PROJETO.md - o maximo de win_valid_real
// consecutivos observado empiricamente foi 2, nao 3) - por isso o
// modulo mantem o alarme de simulacao (`$error`) e o dado e descartado
// com seguranca (nunca sobrescreve um slot com dado ainda nao
// consumido) em vez de corromper a FIFO.
//
// Tratamento da corrida push+pop com o buffer CHEIO (o ponto central
// desta implementacao, ver ressalva registrada no
// RESUMO_ESTADO_PROJETO.md sobre nao copiar o esboço externo sem
// tratar este caso): quando skid_count_r==2, skid_wr_ptr_r e
// skid_rd_ptr_r apontam necessariamente para o MESMO endereco (unico
// jeito de uma FIFO circular de profundidade 2 estar cheia usando 1
// bit de ponteiro cada) - NAO usamos comparacao wr_ptr==rd_ptr para
// decidir cheio/vazio (essa comparacao e estruturalmente ambigua:
// tanto vazio quanto cheio tem wr_ptr==rd_ptr para profundidade 2);
// skid_count_r e a UNICA fonte de verdade para isso. Se, alem de
// cheia, houver push E pop no MESMO ciclo, a escrita e ACEITA (grava
// no endereco que o pop esta liberando neste mesmo ciclo) sem
// corromper o dado antigo: a leitura combinacional de o_data usa o
// valor do registrador ANTES da borda de clock (semantica padrao de
// flip-flop, dado visivel ate a borda), enquanto a escrita sincrona so
// passa a valer no ciclo seguinte - nao ha conflito real de dado,
// apenas a aparencia de 1 endereco compartilhado no mesmo ciclo.
// Validado por reproducao isolada com teste direcionado cobrindo
// exatamente este cenario (push+pop simultaneos com buffer cheio,
// verificando ordem FIFO preservada em toda a sequencia) - ver
// tb_python/test_skid_fifo2.py, teste
// test_race_push_pop_simultaneous_when_full.
module skid_fifo2 #(
    parameter int DATA_WIDTH = 9 * 8  // largura de 1 janela 3x3 achatada (9*DATA_WIDTH do pixel)
) (
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic                  i_push,             // equivalente a win_valid_real
    input  logic [DATA_WIDTH-1:0] i_push_data,        // equivalente a win_window
    input  logic                  i_downstream_ready, // equivalente a fsm_ready
    output logic                  o_valid,            // equivalente a fsm_i_valid
    output logic [DATA_WIDTH-1:0] o_data,             // equivalente a fsm_i_window
    output logic                  o_overflow,         // 1 = i_push descartado (cheio, sem pop)
    output logic                  o_room              // 1 = buffer completamente vazio (Alternativa A3)
);

  localparam int SkidDepth = 2;

  (* ramstyle = "logic" *)
  logic [DATA_WIDTH-1:0] skid_mem_r[SkidDepth];
  logic                  skid_wr_ptr_r;
  logic                  skid_rd_ptr_r;
  logic [           1:0] skid_count_r;  // 0/1/2 itens - unica fonte de verdade p/ cheio/vazio

  logic skid_full;
  logic skid_pop;
  logic skid_push_accepted;

  assign skid_full = (skid_count_r == 2'd2);

  // ALTERADO AQUI (Alternativa A3, correcao 2 - confirmada por trace real,
  // tb_python/test_a3_stale_room_race_trace.py, ciclo 89): a 1a versao de
  // o_room usava so skid_count_r (registrador), que so reflete um push ou
  // pop 1 ciclo DEPOIS dele acontecer - permitindo, no MESMO ciclo de um
  // push/pop ainda nao assentado, uma leitura desatualizada que deixou
  // passar um 3o aceite indevido em window_3x3 (2 aceites seguidos sem
  // gap, o 2o baseado em room stale). Corrigido com a MESMA formula
  // "olhando a frente" ja usada e validada em line_window_skid.sv (o_room,
  // "formula v2") - soma i_push e subtrai skid_pop deste MESMO ciclo antes
  // de decidir se o buffer ficara REALMENTE vazio apos este ciclo resolver.
  logic [2:0] room_calc;
  assign room_calc = {1'b0, skid_count_r} + {2'b0, i_push} - {2'b0, skid_pop};
  assign o_room = (room_calc == 3'd0);

  // o_valid so pode ser 1 quando i_downstream_ready=1: mac_control_fsm.sv
  // tem seu PROPRIO contrato de interface (dispara $error se i_valid=1
  // com o_ready=0) - reter o item no buffer (count_r>0) sem apresentar
  // o_valid enquanto o consumidor nao esta pronto e o que evita violar
  // esse contrato do lado de fora deste modulo.
  assign o_valid = (skid_count_r != 2'd0) && i_downstream_ready;
  assign o_data  = skid_mem_r[skid_rd_ptr_r];

  // skid_pop = o item na cabeca da fila foi de fato consumido neste
  // ciclo - ja inclui i_downstream_ready por construcao (ver acima).
  assign skid_pop = o_valid;

  // Uma nova janela so e ACEITA se houver espaco (!skid_full) OU se,
  // mesmo cheia, o pop deste mesmo ciclo libera a vaga - ver
  // justificativa completa no cabecalho do modulo.
  assign skid_push_accepted = i_push && !(skid_full && !skid_pop);
  assign o_overflow = i_push && skid_full && !skid_pop;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      skid_wr_ptr_r <= 1'b0;
      skid_rd_ptr_r <= 1'b0;
      skid_count_r  <= 2'd0;
    end else begin
      if (skid_push_accepted) begin
        skid_mem_r[skid_wr_ptr_r] <= i_push_data;
        skid_wr_ptr_r <= ~skid_wr_ptr_r;
      end
      if (skid_pop) begin
        skid_rd_ptr_r <= ~skid_rd_ptr_r;
      end
      // 4 combinacoes de {push_aceito, pop}: so push -> +1; so pop ->
      // -1; os dois juntos (full+push+pop, ou count==1+push+pop) -> 1
      // entra e 1 sai, sem variacao liquida; nenhum dos dois -> sem
      // variacao. unique case documenta essa exaustividade.
      unique case ({
        skid_push_accepted, skid_pop
      })
        2'b10:   skid_count_r <= skid_count_r + 2'd1;
        2'b01:   skid_count_r <= skid_count_r - 2'd1;
        default: skid_count_r <= skid_count_r;
      endcase
    end
  end

  // synthesis translate_off
  /* verilator lint_off SYNCASYNCNET */
  always_ff @(posedge clk) begin
    if (rst_n && o_overflow) begin
      $error("skid_fifo2: FIFO (profundidade 2) transbordou - i_push com o buffer cheio ",
             "e sem pop simultaneo, janela seria perdida");
    end
  end
  /* verilator lint_on SYNCASYNCNET */
  // synthesis translate_on

endmodule
