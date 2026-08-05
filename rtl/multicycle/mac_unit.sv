`include "timescale.svh"

// mac_unit
//
// Unidade generica de multiplicacao-acumulacao (MAC), pensada para ser
// reaproveitada pela mac_control_fsm (arquitetura multiciclo) ao longo
// dos 12 ciclos uteis de MAC por pixel (6 para Gx + 6 para Gy - ver
// docs/ARQUITETURA_MULTICICLO.md, secao "Modulos Especificos > mac_unit"
// para a derivacao completa de cada decisao de projeto abaixo).
//
// O "multiplicador" nao existe de fato em hardware: como os coeficientes
// do Sobel valem apenas {+1,-1,+2,-2} apos a otimizacao que pula os
// coeficientes zero (a FSM nunca deveria enviar i_coeff=0 para este
// modulo), a multiplicacao e substituida por deslocamento + negacao -
// 0 multiplicadores/DSPs por construcao, nao por otimizacao da
// ferramenta de sintese.
module mac_unit #(
    parameter int DATA_WIDTH  = 8,  // largura do pixel (sem sinal)
    parameter int COEFF_WIDTH = 3,  // largura do coeficiente (com sinal, cobre -2..2)
    parameter int ACC_WIDTH   = 11  // largura do acumulador (minimo exato - ver doc)
) (
    input  logic                          clk,
    input  logic                          rst_n,
    input  logic                          i_clear,   // zera o acumulador neste ciclo
    input  logic                          i_mac_en,  // realiza 1 passo de MAC neste ciclo
    input  logic        [ DATA_WIDTH-1:0] i_pixel,   // pixel sem sinal
    input  logic signed [COEFF_WIDTH-1:0] i_coeff,   // coeficiente com sinal: +1,-1,+2,-2
    output logic signed [  ACC_WIDTH-1:0] o_acc      // acumulador corrente (sempre visivel)
);

  // Pixel "esticado" para ACC_WIDTH bits, como valor positivo com sinal
  // explicito (zero-extend por replicacao) - construido no tamanho
  // final de uma vez, sem depender de extensao implicita em atribuicao.
  logic signed [ACC_WIDTH-1:0] pixel_ext;
  assign pixel_ext = {{(ACC_WIDTH - DATA_WIDTH) {1'b0}}, i_pixel};

  // "Multiplicador" via desloca+inverte - ver tabela na justificativa.
  // i_coeff=0 nunca deveria ocorrer (filtrado na FSM); o default cobre
  // esse caso por seguranca, sem propagar X para o acumulador.
  logic signed [ACC_WIDTH-1:0] product;

  always_comb begin
    unique case (i_coeff)
      3'sd1:   product = pixel_ext;
      -3'sd1:  product = -pixel_ext;
      3'sd2:   product = pixel_ext <<< 1;
      -3'sd2:  product = -(pixel_ext <<< 1);
      default: product = '0;
    endcase
  end

  // Acumulador: reset assincrono, clear sincrono tem prioridade sobre
  // mac_en (se os dois vierem juntos no mesmo ciclo, o produto deste
  // ciclo e descartado - nao deveria acontecer no uso normal da FSM,
  // mas o comportamento fica bem definido).
  logic signed [ACC_WIDTH-1:0] acc_r;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) acc_r <= '0;
    else if (i_clear) acc_r <= '0;
    else if (i_mac_en) acc_r <= acc_r + product;
  end

  assign o_acc = acc_r;

endmodule
