`include "timescale.svh"

// mac_control_fsm
//
// Modulo especifico da arquitetura multiciclo - a peca central que
// reaproveita 1 unico mac_unit ao longo de 12 ciclos uteis de MAC (6
// para Gx + 6 para Gy) mais alguns ciclos de controle, para computar a
// magnitude L1 do gradiente Sobel de UMA janela 3x3. Ver
// docs/ARQUITETURA_MULTICICLO.md, secao "Modulos Especificos >
// mac_control_fsm" para a derivacao completa da sequencia de estados
// (incluindo a correcao do ciclo extra S_SAVE_GX e a simplificacao que
// elimina os antigos S_FINALIZE/S_ADD_SAT como estados separados).
//
// Apesar do nome "_fsm", este modulo tambem instancia o datapath
// completo (mac_unit, kernel_rom, abs_saturate x2, magnitude_l1) -
// decisao deliberada: a responsabilidade unica deste modulo e "dada
// uma janela 3x3, produzir a magnitude Sobel reaproveitando hardware
// minimo no tempo", o que inclui tanto o controle quanto os blocos que
// ele orquestra. O top-level (sobel_multicycle, ainda nao construido)
// so precisa conectar line_buffer_2line -> window_3x3 -> este modulo.
//
// Contrato de interface: a fonte de i_valid/i_window (window_3x3, via
// sobel_multicycle) so deve apresentar uma nova janela quando
// o_ready=1 - apresentar i_valid=1 com o_ready=0 faz a janela ser
// perdida silenciosamente (ver assertion de simulacao no final do
// modulo).
module mac_control_fsm #(
    parameter int DATA_WIDTH  = 8,
    parameter int COEFF_WIDTH = 3,
    parameter int ACC_WIDTH   = 11
) (
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    i_valid,
    input  logic [9*DATA_WIDTH-1:0] i_window,  // vetor achatado, layout igual ao window_3x3
    output logic                    o_ready,
    output logic                    o_valid,
    output logic [  DATA_WIDTH-1:0] o_pixel
);

  // ---------------------------------------------------------------------
  // Estados: 16 no total. LOAD_WIN(1) + MAC_GX(6) + SAVE_GX(1) +
  // MAC_GY(6) + OUTPUT(1) = 15 ciclos uteis por pixel (fora o IDLE, que
  // fica parado esperando).
  // ---------------------------------------------------------------------
  typedef enum logic [4:0] {
    S_IDLE     = 5'd0,
    S_LOAD_WIN = 5'd1,
    S_MAC_GX_0 = 5'd2,
    S_MAC_GX_1 = 5'd3,
    S_MAC_GX_2 = 5'd4,
    S_MAC_GX_3 = 5'd5,
    S_MAC_GX_4 = 5'd6,
    S_MAC_GX_5 = 5'd7,
    S_SAVE_GX  = 5'd8,
    S_MAC_GY_0 = 5'd9,
    S_MAC_GY_1 = 5'd10,
    S_MAC_GY_2 = 5'd11,
    S_MAC_GY_3 = 5'd12,
    S_MAC_GY_4 = 5'd13,
    S_MAC_GY_5 = 5'd14,
    S_OUTPUT   = 5'd15
  } state_e;

  state_e state_r;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state_r <= S_IDLE;
    end else begin
      unique case (state_r)
        S_IDLE:     state_r <= i_valid ? S_LOAD_WIN : S_IDLE;
        S_LOAD_WIN: state_r <= S_MAC_GX_0;
        S_MAC_GX_0: state_r <= S_MAC_GX_1;
        S_MAC_GX_1: state_r <= S_MAC_GX_2;
        S_MAC_GX_2: state_r <= S_MAC_GX_3;
        S_MAC_GX_3: state_r <= S_MAC_GX_4;
        S_MAC_GX_4: state_r <= S_MAC_GX_5;
        S_MAC_GX_5: state_r <= S_SAVE_GX;
        S_SAVE_GX:  state_r <= S_MAC_GY_0;
        S_MAC_GY_0: state_r <= S_MAC_GY_1;
        S_MAC_GY_1: state_r <= S_MAC_GY_2;
        S_MAC_GY_2: state_r <= S_MAC_GY_3;
        S_MAC_GY_3: state_r <= S_MAC_GY_4;
        S_MAC_GY_4: state_r <= S_MAC_GY_5;
        S_MAC_GY_5: state_r <= S_OUTPUT;
        S_OUTPUT:   state_r <= S_IDLE;
        default:    state_r <= S_IDLE;
      endcase
    end
  end

  assign o_ready = (state_r == S_IDLE);

  // ---------------------------------------------------------------------
  // Janela congelada: window_3x3 continua deslizando mesmo com a FSM
  // ocupada (ver nota em window_3x3.sv) - por isso copiamos os 9
  // valores para registradores proprios, e usamos so essa copia dali
  // em diante, nunca i_window diretamente durante o processamento.
  //
  // BUG REAL corrigido nesta sessao: a captura acontecia em
  // "state_r == S_LOAD_WIN" (ou seja, 1 ciclo inteiro DEPOIS de
  // i_valid ter sido aceito em S_IDLE) - mas o contrato de interface
  // (ver cabecalho do modulo) so garante i_window valido ENQUANTO
  // o_ready=1 (durante S_IDLE), nao no ciclo seguinte. Como quem
  // dirige i_window (window_3x3, sem backpressure) nao segura o valor
  // parado, por essa altura i_window ja tinha avancado (ou zerado, no
  // teste) - win_reg ficava permanentemente zerado, magnitude sempre
  // saia 0. Corrigido capturando na propria transicao de saida de
  // S_IDLE (S_IDLE && i_valid), que e exatamente o ciclo em que
  // o_ready=1 e i_window ainda e garantido valido. S_LOAD_WIN continua
  // existindo como estado, agora servindo so para dar 1 ciclo de folga
  // pro i_clear do mac_unit assentar antes do 1o MAC.
  // ---------------------------------------------------------------------
  logic [DATA_WIDTH-1:0] win_reg[9];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int i = 0; i < 9; i++) win_reg[i] <= '0;
    end else if (state_r == S_IDLE && i_valid) begin
      for (int i = 0; i < 9; i++) win_reg[i] <= i_window[(9-i)*DATA_WIDTH-1-:DATA_WIDTH];
    end
  end

  // ---------------------------------------------------------------------
  // Derivacao combinacional de "em qual tap estamos" a partir do
  // proprio estado - evita um contador redundante.
  // ---------------------------------------------------------------------
  logic is_gx_mac, is_gy_mac;
  logic [2:0] tap_idx;

  assign is_gx_mac = (state_r >= S_MAC_GX_0) && (state_r <= S_MAC_GX_5);
  assign is_gy_mac = (state_r >= S_MAC_GY_0) && (state_r <= S_MAC_GY_5);
  assign tap_idx = is_gx_mac ? (3'(state_r) - 3'(S_MAC_GX_0)) :
      is_gy_mac ? (3'(state_r) - 3'(S_MAC_GY_0)) : 3'd0;

  logic                          kr_gy;
  logic        [            3:0] kr_win_pos;
  logic signed [COEFF_WIDTH-1:0] kr_coeff;

  assign kr_gy = is_gy_mac;

  kernel_rom #(
      .COEFF_WIDTH(COEFF_WIDTH)
  ) u_kernel_rom (
      .i_gy(kr_gy),
      .i_tap_idx(tap_idx),
      .o_win_pos(kr_win_pos),
      .o_coeff(kr_coeff)
  );

  // ---------------------------------------------------------------------
  // mac_unit: 1 unica instancia, reaproveitada para Gx e depois Gy.
  // clear acontece em S_LOAD_WIN (zera antes de Gx) e em S_SAVE_GX
  // (zera antes de Gy, apos salvar o resultado de Gx - ver abaixo).
  // ---------------------------------------------------------------------
  logic mac_clear, mac_en;
  logic [DATA_WIDTH-1:0] mac_pixel;
  logic signed [ACC_WIDTH-1:0] mac_acc;

  assign mac_clear = (state_r == S_LOAD_WIN) || (state_r == S_SAVE_GX);
  assign mac_en = is_gx_mac || is_gy_mac;
  assign mac_pixel = win_reg[kr_win_pos];

  mac_unit #(
      .DATA_WIDTH (DATA_WIDTH),
      .COEFF_WIDTH(COEFF_WIDTH),
      .ACC_WIDTH  (ACC_WIDTH)
  ) u_mac_unit (
      .clk(clk),
      .rst_n(rst_n),
      .i_clear(mac_clear),
      .i_mac_en(mac_en),
      .i_pixel(mac_pixel),
      .i_coeff(kr_coeff),
      .o_acc(mac_acc)
  );

  // ---------------------------------------------------------------------
  // Resultado de Gx: salvo em S_SAVE_GX (o mesmo ciclo em que o
  // mac_unit e limpo para Gy - sao registradores diferentes, sem
  // conflito. Alternativa A da discussao de projeto: aceita 1 ciclo
  // extra em vez de reabrir o mac_unit).
  // ---------------------------------------------------------------------
  logic signed [ACC_WIDTH-1:0] gx_result_r;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) gx_result_r <= '0;
    else if (state_r == S_SAVE_GX) gx_result_r <= mac_acc;
  end

  // ---------------------------------------------------------------------
  // Finalizacao: |Gx|+|Gy| saturado - puramente combinacional (nenhum
  // dos 2 modulos abaixo tem clk), por isso NAO precisa de estados
  // dedicados (S_FINALIZE/S_ADD_SAT de uma versao anterior deste
  // projeto foram eliminados) - o valor ja esta pronto assim que
  // gx_result_r e mac_acc ficam estaveis, exatamente em S_OUTPUT.
  // ---------------------------------------------------------------------
  logic [DATA_WIDTH-1:0] gx_abs, gy_abs;

  abs_saturate #(
      .IN_WIDTH (ACC_WIDTH),
      .OUT_WIDTH(DATA_WIDTH)
  ) u_abs_gx (
      .i_value(gx_result_r),
      .o_value(gx_abs)
  );

  abs_saturate #(
      .IN_WIDTH (ACC_WIDTH),
      .OUT_WIDTH(DATA_WIDTH)
  ) u_abs_gy (
      .i_value(mac_acc),
      .o_value(gy_abs)
  );

  logic [DATA_WIDTH-1:0] magnitude;

  magnitude_l1 #(
      .DATA_WIDTH(DATA_WIDTH)
  ) u_magnitude (
      .i_abs_gx(gx_abs),
      .i_abs_gy(gy_abs),
      .o_magnitude(magnitude)
  );

  assign o_valid = (state_r == S_OUTPUT);
  assign o_pixel = magnitude;

  // synthesis translate_off
  // Checagem de simulacao: violacao do contrato de interface (janela
  // nova apresentada enquanto a FSM ainda esta ocupada).
  always_ff @(posedge clk) begin
    if (rst_n && i_valid && !o_ready) begin
      $error("mac_control_fsm: violacao de contrato - i_valid ativo com o_ready=0 ",
             "(janela seria perdida, FSM ainda ocupada)");
    end
  end
  // synthesis translate_on

endmodule
