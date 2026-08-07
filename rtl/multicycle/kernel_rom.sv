`include "timescale.svh"

// kernel_rom
//
// Modulo especifico da arquitetura multiciclo. Dado "qual kernel"
// (Gx ou Gy) e "qual dos 6 taps nao-nulos" (0..5), devolve a posicao
// na janela 3x3 (0..8, linha-major, mesma convencao do window_3x3) e o
// coeficiente correspondente. Puramente combinacional (sem clk).
//
// Coeficientes confirmados em docs/ARQUITETURA_MULTICICLO.md, secao
// 6.2 - e cross-validados de forma independente contra uma segunda
// especificacao (formulacao algebrica Gx=(c+2f+i)-(a+2d+g), mesma
// convencao de indices), ver historico de decisoes do projeto.
//
//   Gx: indices 0,2,3,5,6,8 -> coeficientes -1,+1,-2,+2,-1,+1
//   Gy: indices 0,1,2,6,7,8 -> coeficientes -1,-2,-1,+1,+2,+1
//
// TRAVA ATIVA (nao so alarme passivo): o_win_pos e SEMPRE um valor
// dentro de 0..8, mesmo se i_tap_idx vier invalido (6 ou 7) - qualquer
// consumidor pode indexar um array de 9 posicoes com o_win_pos sem
// checar nada antes, e NUNCA vai estourar os limites do array, mesmo
// em caso de mau uso. o_addr_valid (sintetizavel, sobrevive em
// hardware real - diferente do $error abaixo, que so existe em
// simulacao) informa se o par (o_win_pos, o_coeff) devolvido
// corresponde de fato a um tap real (1) ou e so o valor seguro de
// fallback (0). Quem nao se importa pode ignorar o_addr_valid sem
// risco; quem quiser reagir ativamente a um endereco invalido (mesmo
// em hardware sintetizado) agora tem como.
module kernel_rom #(
    parameter int COEFF_WIDTH = 3
) (
    input logic i_gy,  // 0=tabela de Gx, 1=tabela de Gy
    input logic [2:0] i_tap_idx,  // 0..5
    output logic [3:0] o_win_pos,  // posicao 0..8 na janela - SEMPRE valida
    output logic signed [COEFF_WIDTH-1:0] o_coeff,
    output logic o_addr_valid  // 1=tap real, 0=i_tap_idx estava fora de 0..5
);

  always_comb begin
    o_addr_valid = 1'b1;  // sobrescrito para 0 so nos ramos 'default' do case abaixo
    if (!i_gy) begin
      unique case (i_tap_idx)
        3'd0: begin
          o_win_pos = 4'd0;
          o_coeff   = -3'sd1;
        end
        3'd1: begin
          o_win_pos = 4'd2;
          o_coeff   = 3'sd1;
        end
        3'd2: begin
          o_win_pos = 4'd3;
          o_coeff   = -3'sd2;
        end
        3'd3: begin
          o_win_pos = 4'd5;
          o_coeff   = 3'sd2;
        end
        3'd4: begin
          o_win_pos = 4'd6;
          o_coeff   = -3'sd1;
        end
        3'd5: begin
          o_win_pos = 4'd8;
          o_coeff   = 3'sd1;
        end
        default: begin
          // valor seguro, SEMPRE dentro de 0..8 - trava ativa: nunca
          // causa acesso fora dos limites de um array de 9 posicoes,
          // mesmo que o consumidor nao cheque o_addr_valid.
          o_win_pos    = 4'd0;
          o_coeff      = '0;
          o_addr_valid = 1'b0;
        end
      endcase
    end else begin
      unique case (i_tap_idx)
        3'd0: begin
          o_win_pos = 4'd0;
          o_coeff   = -3'sd1;
        end
        3'd1: begin
          o_win_pos = 4'd1;
          o_coeff   = -3'sd2;
        end
        3'd2: begin
          o_win_pos = 4'd2;
          o_coeff   = -3'sd1;
        end
        3'd3: begin
          o_win_pos = 4'd6;
          o_coeff   = 3'sd1;
        end
        3'd4: begin
          o_win_pos = 4'd7;
          o_coeff   = 3'sd2;
        end
        3'd5: begin
          o_win_pos = 4'd8;
          o_coeff   = 3'sd1;
        end
        default: begin
          o_win_pos    = 4'd0;
          o_coeff      = '0;
          o_addr_valid = 1'b0;
        end
      endcase
    end
  end

  // synthesis translate_off
  // Checagem de simulacao: i_tap_idx fora do intervalo valido (0..5).
  // Complementa a trava ativa acima (o_win_pos seguro + o_addr_valid) -
  // o hardware ja se protege sozinho contra o mau uso mesmo sem este
  // bloco, mas o $error torna a violacao IMEDIATAMENTE visivel no log
  // de simulacao, sem depender de alguem lembrar de checar
  // o_addr_valid explicitamente em todo teste futuro.
  always_comb begin
    if (i_tap_idx > 3'd5) begin
      $error("kernel_rom: i_tap_idx fora do intervalo valido (0..5) - ",
             "so existem 6 taps nao-nulos por kernel (i_tap_idx=%0d)", i_tap_idx);
    end
  end
  // synthesis translate_on

endmodule
