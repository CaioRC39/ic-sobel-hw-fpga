`include "timescale.svh"

// abs_saturate
//
// Modulo comum (usado pelas 3 arquiteturas). Calcula o valor absoluto
// de uma entrada com sinal e satura o resultado para caber em
// OUT_WIDTH bits sem sinal - se |i_value| > 2^OUT_WIDTH-1, a saida
// trava no maximo representavel em vez de estourar. Ver
// docs/ARQUITETURA_MULTICICLO.md, secao "Modulos Comuns > abs_saturate"
// para a justificativa completa.
//
// Puramente combinacional (sem clk/rst_n) - uma funcao pura, pensada
// para ser instanciada 2x (uma para Gx, outra para Gy) dentro do
// mesmo ciclo da FSM/pipeline que a usar.
module abs_saturate #(
    parameter int IN_WIDTH  = 11,  // largura da entrada (com sinal)
    parameter int OUT_WIDTH = 8    // largura da saida (sem sinal, saturada)
) (
    input  logic signed [ IN_WIDTH-1:0] i_value,
    output logic        [OUT_WIDTH-1:0] o_value
);

  // Entrada "esticada" em 1 bit extra antes de negar - evita o caso
  // extremo classico de complemento de 2, onde o valor mais negativo
  // representavel (ex: -1024 em 11 bits) nao tem um positivo
  // correspondente na MESMA largura (o maximo positivo em 11 bits e
  // soh 1023). Com 1 bit a mais, a negacao sempre cabe corretamente.
  // Na pratica, o uso real deste modulo (saida do mac_unit, +-1020)
  // nunca chega nesse extremo - mas o modulo trata o caso certo de
  // qualquer forma, por ser pensado para reuso generico.
  logic signed [IN_WIDTH:0] value_ext;
  assign value_ext = i_value;

  // Largura interna para o valor absoluto/limite: precisa caber tanto
  // a magnitude maxima (IN_WIDTH+1 bits) quanto o valor 2^OUT_WIDTH-1
  // usado na comparacao de saturacao - o MAIOR dos dois, nao soh
  // IN_WIDTH+1. Sem isso, combinacoes onde OUT_WIDTH > IN_WIDTH+1
  // (ex: IN_WIDTH=4, OUT_WIDTH=8) truncam MaxOut e geram bits X ao
  // selecionar abs_val[OUT_WIDTH-1:0] de um sinal mais estreito -
  // bug real, encontrado testando o caso extremo de complemento de 2
  // com IN_WIDTH pequeno (ver tb_python/test_abs_saturate.py).
  localparam int MagWidth = (IN_WIDTH + 1 > OUT_WIDTH) ? (IN_WIDTH + 1) : OUT_WIDTH;

  logic [MagWidth-1:0] abs_val;
  assign abs_val = value_ext[IN_WIDTH] ?
      MagWidth'(unsigned'(-value_ext)) : MagWidth'(unsigned'(value_ext));

  localparam logic [MagWidth-1:0] MaxOut = (1 << OUT_WIDTH) - 1;

  assign o_value = (abs_val > MaxOut) ? {OUT_WIDTH{1'b1}} : abs_val[OUT_WIDTH-1:0];

endmodule
