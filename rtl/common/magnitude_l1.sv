`include "timescale.svh"

// magnitude_l1
//
// Modulo comum (usado pelas 3 arquiteturas). Soma |Gx| e |Gy| (ja
// calculados e saturados por 2 instancias de abs_saturate) e satura o
// resultado da soma para DATA_WIDTH bits - a aproximacao L1 da
// magnitude do gradiente (|Gx|+|Gy|), evitando a raiz quadrada da
// magnitude L2 verdadeira. Ver docs/ARQUITETURA_MULTICICLO.md, secao
// "Modulos Comuns > magnitude_l1" para a justificativa completa.
//
// Puramente combinacional (sem clk/rst_n) - uma funcao pura.
module magnitude_l1 #(
    parameter int DATA_WIDTH = 8
) (
    input  logic [DATA_WIDTH-1:0] i_abs_gx,
    input  logic [DATA_WIDTH-1:0] i_abs_gy,
    output logic [DATA_WIDTH-1:0] o_magnitude
);

  localparam int SumWidth = DATA_WIDTH + 1;  // soma de 2 valores de DATA_WIDTH bits

  logic [SumWidth-1:0] sum;
  assign sum = i_abs_gx + i_abs_gy;

  localparam logic [SumWidth-1:0] MaxOut = (1 << DATA_WIDTH) - 1;

  assign o_magnitude = (sum > MaxOut) ? {DATA_WIDTH{1'b1}} : sum[DATA_WIDTH-1:0];

endmodule
