# Arquitetura Paralela - Filtro Sobel

**Versão:** 1.0  
**Data:** 2025  
**Status:** Planejamento / Em desenvolvimento

---

## 1. Visão Geral

A arquitetura **paralela** processa múltiplos pixels por ciclo de clock, maximizando throughput à custo de área significativamente maior. Duas variantes são implementadas:

| Variante | Pixels/Ciclo | MACs Gx | MACs Gy | DSPs Total | Latência |
|----------|--------------|---------|---------|------------|----------|
| **Paralela 2×2** | 4 | 36 | 36 | 72 | ~2 ciclos |
| **Paralela 3×3** | 9 | 81 | 81 | 162 | ~1 ciclo |

### 1.1 Características Principais

| Métrica | Paralela 2×2 | Paralela 3×3 |
|---------|--------------|--------------|
| **Throughput** | 4 pix/clk | 9 pix/clk |
| **Latência** | 2-3 ciclos | 1-2 ciclos |
| **LUTs** | ~2.500 | ~5.500 |
| **FFs** | ~2.000 | ~4.500 |
| **DSPs** | 72 | 162 |
| **BRAM (18Kb)** | 4 | 6 |
| **Fmax (Artix-7)** | ~150 MHz | ~120 MHz |
| **Potência** | Alta | Muito Alta |

---

## 2. Diagrama de Blocos - Paralela 3×3 (9 pixels/ciclo)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          SOBEL_PARALLEL_3x3                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐    ┌──────────────────────┐    ┌────────────────────┐   │
│  │ line_buffer_ │───▶│  window_3x3_         │───▶│  sobel_kernel_     │   │
│  │ 3line        │    │  parallel            │    │  parallel_gx       │   │
│  │ (3 BRAMs)    │    │  (9 janelas 3×3)     │    │  (81 MACs +        │   │
│  └──────────────┘    └──────────────────────┘    │   adder trees)     │   │
│                                                   └─────────┬──────────┘   │
│                                                             │              │
│                                                   ┌─────────┴──────────┐   │
│                                                   │                   │   │
│                                          ┌────────▼────────┐ ┌────────▼────────┐│
│                                          │  abs_array_gx   │ │  abs_array_gy   ││
│                                          │  (9 ABS paralelos)│ │  (9 ABS paralelos)│
│                                          └────────┬────────┘ └────────┬────────┘│
│                                                   │                   │        │
│                                                   ▼                   ▼        │
│                                          ┌───────────────────────────────────┐  │
│                                          │     magnitude_l1_parallel         │  │
│                                          │  (9 adders + 9 saturate 8-bit)   │  │
│                                          └──────────────────┬────────────────┘  │
│                                                             │                   │
│                                                             ▼                   │
│                                                   ┌────────────────┐           │
│                                                   │  pixel_out[8:0]│           │
│                                                   │  valid_out[8:0]│           │
│                                                   └────────────────┘           │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Módulos Específicos

### 3.1 Line Buffer 3 Linhas (`line_buffer_3line.sv`)

Armazena **3 linhas completas** para fornecer 3 linhas simultâneas à janela paralela.

```systemverilog
module line_buffer_3line #(
    parameter int WIDTH = 640,
    parameter int DATA_WIDTH = 8
)(
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    valid_in,
    input  logic [DATA_WIDTH-1:0]   pixel_in,
    input  logic                    last_pixel_in,
    input  logic                    last_line_in,
    output logic                    valid_out,
    output logic [DATA_WIDTH-1:0]   line0_out,  // linha y-3
    output logic [DATA_WIDTH-1:0]   line1_out,  // linha y-2
    output logic [DATA_WIDTH-1:0]   line2_out,  // linha y-1
    output logic [DATA_WIDTH-1:0]   curr_out,   // pixel atual (linha y)
    output logic                    last_pixel_out,
    output logic                    last_line_out
);

    // 3 BRAMs de WIDTH × DATA_WIDTH
    logic [DATA_WIDTH-1:0] bram0 [0:WIDTH-1];
    logic [DATA_WIDTH-1:0] bram1 [0:WIDTH-1];
    logic [DATA_WIDTH-1:0] bram2 [0:WIDTH-1];
    
    logic [$clog2(WIDTH):0] wr_addr;
    logic [1:0] line_sel;  // 0, 1, 2 para rotação de BRAMs
    
    // Escrita rotativa entre as 3 BRAMs
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_addr <= '0;
            line_sel <= '0;
            valid_out <= 1'b0;
        end else if (valid_in) begin
            case (line_sel)
                2'd0: bram0[wr_addr] <= pixel_in;
                2'd1: bram1[wr_addr] <= pixel_in;
                2'd2: bram2[wr_addr] <= pixel_in;
            endcase
            
            if (last_pixel_in) begin
                wr_addr <= '0;
                line_sel <= line_sel + 1'b1;
            end else begin
                wr_addr <= wr_addr + 1'b1;
            end
            
            valid_out <= 1'b1;
            last_pixel_out <= last_pixel_in;
            last_line_out <= last_line_in;
        end else begin
            valid_out <= 1'b0;
        end
    end
    
    // Leitura combinacional (saída registrada no window_parallel)
    always_comb begin
        case (line_sel)
            2'd0: begin // escrevendo na 0, lendo 1,2,0
                line0_out = bram1[wr_addr];
                line1_out = bram2[wr_addr];
                line2_out = bram0[wr_addr];
                curr_out  = pixel_in;
            end
            2'd1: begin // escrevendo na 1, lendo 2,0,1
                line0_out = bram2[wr_addr];
                line1_out = bram0[wr_addr];
                line2_out = bram1[wr_addr];
                curr_out  = pixel_in;
            end
            2'd2: begin // escrevendo na 2, lendo 0,1,2
                line0_out = bram0[wr_addr];
                line1_out = bram1[wr_addr];
                line2_out = bram2[wr_addr];
                curr_out  = pixel_in;
            end
        endcase
    end
endmodule
```

---

### 3.2 Janela 3×3 Paralela (`window_3x3_parallel.sv`)

Gera **9 janelas 3×3 simultâneas** (para processamento 3×3 pixels/ciclo) ou **4 janelas** (para 2×2).

```systemverilog
module window_3x3_parallel #(
    parameter int DATA_WIDTH = 8,
    parameter int PARALLEL_FACTOR = 9  // 4 para 2x2, 9 para 3x3
)(
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    valid_in,
    input  logic [DATA_WIDTH-1:0]   line0,  // y-3
    input  logic [DATA_WIDTH-1:0]   line1,  // y-2
    input  logic [DATA_WIDTH-1:0]   line2,  // y-1
    input  logic [DATA_WIDTH-1:0]   curr,   // y
    input  logic                    last_pixel_in,
    input  logic                    last_line_in,
    output logic                    valid_out,
    output logic [DATA_WIDTH-1:0]   windows [0:PARALLEL_FACTOR-1][0:2][0:2],
    output logic                    last_pixel_out,
    output logic                    last_line_out
);

    // Shift registers por linha (3 pixels de histórico por linha)
    logic [DATA_WIDTH-1:0] line0_sr [0:2];
    logic [DATA_WIDTH-1:0] line1_sr [0:2];
    logic [DATA_WIDTH-1:0] line2_sr [0:2];
    logic [DATA_WIDTH-1:0] curr_sr  [0:2];
    
    logic valid_r;
    logic last_pixel_r, last_line_r;
    
    // Para paralelismo 3x3: precisamos de 3 pixels da linha atual por ciclo
    // Para paralelismo 2x2: precisamos de 2 pixels da linha atual
    
    // Implementação simplificada para 3x3 (9 janelas)
    // Cada janela[i] = pixels [i:i+2] das 3 linhas + corrente
    
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            line0_sr[0] <= '0; line0_sr[1] <= '0; line0_sr[2] <= '0;
            line1_sr[0] <= '0; line1_sr[1] <= '0; line1_sr[2] <= '0;
            line2_sr[0] <= '0; line2_sr[1] <= '0; line2_sr[2] <= '0;
            curr_sr[0]  <= '0; curr_sr[1]  <= '0; curr_sr[2]  <= '0;
            valid_r <= 1'b0;
            last_pixel_r <= 1'b0;
            last_line_r <= 1'b0;
        end else if (valid_in) begin
            // Shift registers
            line0_sr[0] <= line0_sr[1];
            line0_sr[1] <= line0_sr[2];
            line0_sr[2] <= line0;
            
            line1_sr[0] <= line1_sr[1];
            line1_sr[1] <= line1_sr[2];
            line1_sr[2] <= line1;
            
            line2_sr[0] <= line2_sr[1];
            line2_sr[1] <= line2_sr[2];
            line2_sr[2] <= line2;
            
            curr_sr[0] <= curr_sr[1];
            curr_sr[1] <= curr_sr[2];
            curr_sr[2] <= curr;
            
            valid_r <= 1'b1;
            last_pixel_r <= last_pixel_in;
            last_line_r <= last_line_in;
        end else begin
            valid_r <= 1'b0;
        end
    end
    
    // Monta 9 janelas 3x3 (paralelo 3x3)
    generate
        if (PARALLEL_FACTOR == 9) begin : gen_3x3
            for (genvar i = 0; i < 3; i++) begin : row
                for (genvar j = 0; j < 3; j++) begin : col
                    localparam int idx = i * 3 + j;
                    assign windows[idx][0][0] = line0_sr[j];
                    assign windows[idx][0][1] = line0_sr[j+1];
                    assign windows[idx][0][2] = line0_sr[j+2];
                    assign windows[idx][1][0] = line1_sr[j];
                    assign windows[idx][1][1] = line1_sr[j+1];
                    assign windows[idx][1][2] = line1_sr[j+2];
                    assign windows[idx][2][0] = line2_sr[j];
                    assign windows[idx][2][1] = line2_sr[j+1];
                    assign windows[idx][2][2] = line2_sr[j+2];
                    // Linha atual vai para próxima iteração via shift
                end
            end
        end else if (PARALLEL_FACTOR == 4) begin : gen_2x2
            // 4 janelas 2x2 (cada uma gera 1 pixel de saída)
            // Implementação similar mas 2x2
        end
    endgenerate
    
    assign valid_out = valid_r;
    assign last_pixel_out = last_pixel_r;
    assign last_line_out = last_line_r;
endmodule
```

---

### 3.3 Kernel Paralelo Gx/Gy (`sobel_kernel_parallel.sv`)

**81 multiplicadores paralelos + adder trees** para processar 9 janelas simultaneamente.

```systemverilog
module sobel_kernel_parallel #(
    parameter int DATA_WIDTH = 8,
    parameter int KERNEL_WIDTH = 4,
    parameter int ACC_WIDTH = 16,
    parameter int PARALLEL_FACTOR = 9,  // 4 ou 9
    parameter bit IS_GX = 1'b1  // 1=Gx, 0=Gy
)(
    input  logic                              clk,
    input  logic                              rst_n,
    input  logic                              valid_in,
    input  logic [DATA_WIDTH-1:0]             windows [0:PARALLEL_FACTOR-1][0:2][0:2],
    output logic                              valid_out,
    output logic signed [ACC_WIDTH-1:0]       sums [0:PARALLEL_FACTOR-1]
);

    // Kernels hardcoded (síntese otimiza constantes)
    localparam logic signed [KERNEL_WIDTH-1:0] KERNEL_GX [0:8] = '{
        -1,  0,  1,
        -2,  0,  2,
        -1,  0,  1
    };
    
    localparam logic signed [KERNEL_WIDTH-1:0] KERNEL_GY [0:8] = '{
        -1, -2, -1,
         0,  0,  0,
         1,  2,  1
    };
    
    // Seleciona kernel
    localparam logic signed [KERNEL_WIDTH-1:0] KERNEL [0:8] = IS_GX ? KERNEL_GX : KERNEL_GY;
    
    // Produtos: PARALLEL_FACTOR × 9 multiplicadores
    logic signed [DATA_WIDTH+KERNEL_WIDTH-1:0] products [0:PARALLEL_FACTOR-1][0:8];
    
    // Multiplicação combinacional (mapeia para DSPs)
    generate
        for (genvar p = 0; p < PARALLEL_FACTOR; p++) begin : gen_products
            for (genvar k = 0; k < 9; k++) begin : gen_kernel
                localparam int row = k / 3;
                localparam int col = k % 3;
                always_comb begin
                    products[p][k] = $signed({1'b0, windows[p][row][col]}) * KERNEL[k];
                end
            end
        end
    endgenerate
    
    // Adder trees registrados (3 níveis para 9 elementos)
    logic signed [ACC_WIDTH-1:0] sum_l1 [0:PARALLEL_FACTOR-1][0:3];
    logic signed [ACC_WIDTH-1:0] sum_l2 [0:PARALLEL_FACTOR-1][0:1];
    logic valid_l1, valid_l2;
    
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sum_l1 <= '0;
            sum_l2 <= '0;
            sums <= '0;
            valid_l1 <= 1'b0;
            valid_l2 <= 1'b0;
            valid_out <= 1'b0;
        end else begin
            // Nível 1: 4 somas de 2 + 1 passa direto
            for (int p = 0; p < PARALLEL_FACTOR; p++) begin
                sum_l1[p][0] <= products[p][0] + products[p][1];
                sum_l1[p][1] <= products[p][2] + products[p][3];
                sum_l1[p][2] <= products[p][4] + products[p][5];
                sum_l1[p][3] <= products[p][6] + products[p][7];
                // products[p][8] vai para nível 2
            end
            valid_l1 <= valid_in;
            
            // Nível 2
            for (int p = 0; p < PARALLEL_FACTOR; p++) begin
                sum_l2[p][0] <= sum_l1[p][0] + sum_l1[p][1];
                sum_l2[p][1] <= sum_l1[p][2] + sum_l1[p][3];
            end
            valid_l2 <= valid_l1;
            
            // Nível 3 (final)
            for (int p = 0; p < PARALLEL_FACTOR; p++) begin
                sums[p] <= sum_l2[p][0] + sum_l2[p][1] + products[p][8];
            end
            valid_out <= valid_l2;
        end
    end
endmodule
```

---

### 3.4 Array ABS Paralelo (`abs_array.sv`)

```systemverilog
module abs_array #(
    parameter int IN_WIDTH = 16,
    parameter int OUT_WIDTH = 16,
    parameter int PARALLEL_FACTOR = 9
)(
    input  logic                              clk,
    input  logic                              rst_n,
    input  logic                              valid_in,
    input  logic signed [IN_WIDTH-1:0]        in_vals [0:PARALLEL_FACTOR-1],
    output logic                              valid_out,
    output logic [OUT_WIDTH-1:0]              out_vals [0:PARALLEL_FACTOR-1]
);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            out_vals <= '0;
            valid_out <= 1'b0;
        end else if (valid_in) begin
            for (int i = 0; i < PARALLEL_FACTOR; i++) begin
                if (in_vals[i][IN_WIDTH-1]) begin // negativo
                    out_vals[i] <= (in_vals[i] == {1'b1, {(IN_WIDTH-1){1'b0}}}) ? 
                                   {1'b0, {(OUT_WIDTH-1){1'b1}}} : (~in_vals[i] + 1'b1);
                end else begin
                    out_vals[i] <= in_vals[i][OUT_WIDTH-1:0];
                end
            end
            valid_out <= 1'b1;
        end else begin
            valid_out <= 1'b0;
        end
    end
endmodule
```

---

### 3.5 Magnitude L1 Paralela (`magnitude_l1_parallel.sv`)

```systemverilog
module magnitude_l1_parallel #(
    parameter int IN_WIDTH = 16,
    parameter int OUT_WIDTH = 8,
    parameter int PARALLEL_FACTOR = 9
)(
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    valid_in,
    input  logic [IN_WIDTH-1:0]     abs_gx [0:PARALLEL_FACTOR-1],
    input  logic [IN_WIDTH-1:0]     abs_gy [0:PARALLEL_FACTOR-1],
    output logic                    valid_out,
    output logic [OUT_WIDTH-1:0]    magnitude [0:PARALLEL_FACTOR-1]
);

    localparam int MAX_VAL = (1 << OUT_WIDTH) - 1; // 255
    
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            magnitude <= '0;
            valid_out <= 1'b0;
        end else if (valid_in) begin
            for (int i = 0; i < PARALLEL_FACTOR; i++) begin
                logic [IN_WIDTH:0] sum;
                sum = abs_gx[i] + abs_gy[i];
                magnitude[i] <= (sum > MAX_VAL) ? MAX_VAL : sum[OUT_WIDTH-1:0];
            end
            valid_out <= 1'b1;
        end else begin
            valid_out <= 1'b0;
        end
    end
endmodule
```

---

## 4. Top-Level Paralelo (`sobel_parallel.sv`)

```systemverilog
module sobel_parallel #(
    parameter int IMG_WIDTH = 640,
    parameter int IMG_HEIGHT = 480,
    parameter int DATA_WIDTH = 8,
    parameter int PARALLEL_FACTOR = 9,  // 4 ou 9
    parameter int KERNEL_WIDTH = 4,
    parameter int ACC_WIDTH = 16
)(
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    valid_in,
    input  logic [DATA_WIDTH-1:0]   pixel_in,
    input  logic                    last_pixel_in,
    input  logic                    last_line_in,
    output logic                    valid_out,
    output logic [DATA_WIDTH-1:0]   pixels_out [0:PARALLEL_FACTOR-1],
    output logic                    last_pixel_out,
    output logic                    last_line_out,
    output logic                    frame_done
);

    // Sinais internos
    logic v_lb, v_win, v_gx, v_gy, v_abs_gx, v_abs_gy, v_mag;
    logic lp_lb, lp_win, lp_gx, lp_gy, lp_abs_gx, lp_abs_gy, lp_mag;
    logic ll_lb, ll_win, ll_gx, ll_gy, ll_abs_gx, ll_abs_gy, ll_mag;
    
    logic [DATA_WIDTH-1:0] line0, line1, line2, curr;
    logic [DATA_WIDTH-1:0] windows [0:PARALLEL_FACTOR-1][0:2][0:2];
    logic signed [ACC_WIDTH-1:0] gx_sums [0:PARALLEL_FACTOR-1];
    logic signed [ACC_WIDTH-1:0] gy_sums [0:PARALLEL_FACTOR-1];
    logic [ACC_WIDTH-1:0] abs_gx [0:PARALLEL_FACTOR-1];
    logic [ACC_WIDTH-1:0] abs_gy [0:PARALLEL_FACTOR-1];
    logic [DATA_WIDTH-1:0] mags [0:PARALLEL_FACTOR-1];

    // Line Buffer 3 linhas
    line_buffer_3line #(.WIDTH(IMG_WIDTH), .DATA_WIDTH(DATA_WIDTH)) lb_inst (
        .clk(clk), .rst_n(rst_n),
        .valid_in(valid_in), .pixel_in(pixel_in),
        .last_pixel_in(last_pixel_in), .last_line_in(last_line_in),
        .valid_out(v_lb),
        .line0_out(line0), .line1_out(line1), .line2_out(line2), .curr_out(curr),
        .last_pixel_out(lp_lb), .last_line_out(ll_lb)
    );

    // Window 3x3 Paralelo
    window_3x3_parallel #(.DATA_WIDTH(DATA_WIDTH), .PARALLEL_FACTOR(PARALLEL_FACTOR)) win_inst (
        .clk(clk), .rst_n(rst_n),
        .valid_in(v_lb),
        .line0(line0), .line1(line1), .line2(line2), .curr(curr),
        .last_pixel_in(lp_lb), .last_line_in(ll_lb),
        .valid_out(v_win),
        .windows(windows),
        .last_pixel_out(lp_win), .last_line_out(ll_win)
    );

    // Kernel Paralelo Gx
    sobel_kernel_parallel #(.DATA_WIDTH(DATA_WIDTH), .KERNEL_WIDTH(KERNEL_WIDTH), 
                            .ACC_WIDTH(ACC_WIDTH), .PARALLEL_FACTOR(PARALLEL_FACTOR),
                            .IS_GX(1'b1)) gx_inst (
        .clk(clk), .rst_n(rst_n),
        .valid_in(v_win), .windows(windows),
        .valid_out(v_gx), .sums(gx_sums)
    );

    // Kernel Paralelo Gy
    sobel_kernel_parallel #(.DATA_WIDTH(DATA_WIDTH), .KERNEL_WIDTH(KERNEL_WIDTH),
                            .ACC_WIDTH(ACC_WIDTH), .PARALLEL_FACTOR(PARALLEL_FACTOR),
                            .IS_GX(1'b0)) gy_inst (
        .clk(clk), .rst_n(rst_n),
        .valid_in(v_win), .windows(windows),
        .valid_out(v_gy), .sums(gy_sums)
    );

    // ABS Array Gx
    abs_array #(.IN_WIDTH(ACC_WIDTH), .OUT_WIDTH(ACC_WIDTH), .PARALLEL_FACTOR(PARALLEL_FACTOR)) abs_gx_inst (
        .clk(clk), .rst_n(rst_n),
        .valid_in(v_gx), .in_vals(gx_sums),
        .valid_out(v_abs_gx), .out_vals(abs_gx)
    );

    // ABS Array Gy
    abs_array #(.IN_WIDTH(ACC_WIDTH), .OUT_WIDTH(ACC_WIDTH), .PARALLEL_FACTOR(PARALLEL_FACTOR)) abs_gy_inst (
        .clk(clk), .rst_n(rst_n),
        .valid_in(v_gy), .in_vals(gy_sums),
        .valid_out(v_abs_gy), .out_vals(abs_gy)
    );

    // Magnitude L1 Paralela
    magnitude_l1_parallel #(.IN_WIDTH(ACC_WIDTH), .OUT_WIDTH(DATA_WIDTH), .PARALLEL_FACTOR(PARALLEL_FACTOR)) mag_inst (
        .clk(clk), .rst_n(rst_n),
        .valid_in(v_abs_gx & v_abs_gy),  // ambos prontos no mesmo ciclo
        .abs_gx(abs_gx), .abs_gy(abs_gy),
        .valid_out(v_mag), .magnitude(mags)
    );

    // Saídas
    assign valid_out = v_mag;
    assign pixels_out = mags;
    assign last_pixel_out = lp_mag;  // propagar através de pipeline_reg
    assign last_line_out = ll_mag;
    assign frame_done = v_mag & lp_mag & ll_mag;

endmodule
```

---

## 5. Gerenciamento de Borda (Paralelo)

### 5.1 Desafio

No processamento paralelo, **múltiplas janelas** acessam pixels de borda simultaneamente. A replicação deve ser consistente.

### 5.2 Estratégia: Padding no Line Buffer

O `line_buffer_3line` já replica:
- **Linhas virtuais** antes da primeira linha real (line0 = line1 = primeira linha)
- **Linhas virtuais** após última linha real
- **Colunas virtuais** no `window_3x3_parallel` via shift register behavior

### 5.3 Janelas Parciais em Borda

Para imagem 640×480 com paralelismo 3×3:
- Último grupo de 3 pixels na linha: janelas 637, 638, 639
- Janela 639 usa colunas 639, 640(virtual), 641(virtual) → replica coluna 639

---

## 6. Timing e Throughput

### 6.1 Paralela 3×3 (9 pixels/ciclo)

| Métrica | Valor |
|---------|-------|
| **Latência** | 5-6 ciclos (LB + Win + Gx/Gy + ABS + Mag) |
| **Throughput** | 9 pixels/ciclo |
| **Ciclos/frame (640×480)** | (640/9) × 480 ≈ 34.133 ciclos |
| **Tempo @ 100MHz** | 341 µs/frame → **2.930 fps** |
| **Tempo @ 120MHz** | 284 µs/frame → **3.520 fps** |

### 6.2 Paralela 2×2 (4 pixels/ciclo)

| Métrica | Valor |
|---------|-------|
| **Latência** | 5-6 ciclos |
| **Throughput** | 4 pixels/ciclo |
| **Ciclos/frame** | (640/4) × 480 = 76.800 ciclos |
| **Tempo @ 100MHz** | 768 µs/frame → **1.300 fps** |

---

## 7. Verificação (Testbench cocotb)

### 7.1 Testes Específicos Paralelo

| Teste | Descrição |
|-------|-----------|
| `test_parallel_3x3_throughput` | Verifica 9 pixels/ciclo sustentado |
| `test_parallel_2x2_throughput` | Verifica 4 pixels/ciclo sustentado |
| `test_parallel_edge_handling` | Bordas com replicação correta |
| `test_parallel_3x3_golden` | Frame completo vs OpenCV |
| `test_parallel_2x2_golden` | Frame completo vs OpenCV |
| `test_parallel_corner_cases` | 1×1, 2×2, 3×3, linha única |

### 7.2 Modelo de Referência Paralelo

```python
# models/sobel_parallel_ref.py
import numpy as np
import cv2

def sobel_parallel_reference(img, parallel_factor=9):
    """Referência funcional (não ciclo-a-ciclo)"""
    h, w = img.shape
    gx = cv2.Sobel(img, cv2.CV_16S, 1, 0, ksize=3)
    gy = cv2.Sobel(img, cv2.CV_16S, 0, 1, ksize=3)
    mag = np.abs(gx) + np.abs(gy)
    return np.clip(mag, 0, 255).astype(np.uint8)

# Testbench compara saída pixel-a-pixel (reordenada se necessário)
```

---

## 8. Síntese e Constraints

### 8.1 XDC (Artix-7)

```tcl
create_clock -period 8.33 -name clk [get_ports clk]  # 120 MHz target

# Input/Output delays
set_input_delay -clock clk -max 1.5 [get_ports {pixel_in valid_in last_pixel_in last_line_in}]
set_output_delay -clock clk -max 1.5 [get_ports {pixels_out[*] valid_out last_pixel_out last_line_out frame_done}]

# False paths
set_false_path -from [get_ports rst_n]

# Multicycle para adder trees profundos (se necessário)
# set_multicycle_path 2 -from [get_pins sobel_kernel_parallel/*] -to [get_pins sobel_kernel_parallel/*]

# DSP inference
set_property DSP_FOLDING ALLOW [get_cells -hierarchical *sobel_kernel_parallel*]
```

### 8.2 Otimizações de Área

| Técnica | Aplicação |
|---------|-----------|
| **DSP sharing** | Não aplicável (paralelo = máximo throughput) |
| **BRAM packing** | `ram_style = "block"` em line buffers |
| **LUTRAM** | Shift registers pequenos em window_parallel |
| **Retiming** | `(* dont_touch = "true" *)` em pipeline stages críticos |
| **Floorplanning** | Pblocks para separar kernels Gx/Gy (opcional) |

---

## 9. Tabela Comparativa Final (Projeção)

| Métrica | Multiciclo | Pipeline | Paralela 2×2 | Paralela 3×3 |
|---------|------------|----------|--------------|--------------|
| **Latência** | ~15 ciclos | 7 ciclos | 6 ciclos | 5 ciclos |
| **Throughput** | 1/15 pix/clk | 1 pix/clk | 4 pix/clk | 9 pix/clk |
| **LUTs** | ~200 | ~800 | ~2.500 | ~5.500 |
| **FFs** | ~150 | ~600 | ~2.000 | ~4.500 |
| **DSPs** | 1 | 18 | 72 | 162 |
| **BRAM** | 2 | 2 | 4 | 6 |
| **Fmax (Artix-7)** | ~250 MHz | ~200 MHz | ~150 MHz | ~120 MHz |
| **Potência** | Muito Baixa | Baixa | Alta | Muito Alta |
| **FPS @ 100MHz (640×480)** | ~2.1M pix/s = 6.8 fps | ~100M pix/s = 325 fps | ~400M pix/s = 1.300 fps | ~900M pix/s = 2.930 fps |

---

## 10. Checklist de Implementação

### 10.1 RTL
- [ ] `line_buffer_3line.sv`
- [ ] `window_3x3_parallel.sv` (PARALLEL_FACTOR param)
- [ ] `sobel_kernel_parallel.sv` (IS_GX param)
- [ ] `abs_array.sv`
- [ ] `magnitude_l1_parallel.sv`
- [ ] `sobel_parallel.sv` (top-level)
- [ ] Verible lint **ZERO warnings**
- [ ] Verilator `--lint-only -Wall` **ZERO warnings**

### 10.2 Verificação
- [ ] `test_sobel_parallel.py` (ambas variantes)
- [ ] Cobertura código ≥ 95%
- [ ] Golden reference match (erro = 0)
- [ ] Throughput sustentado verificado

### 10.3 Síntese
- [ ] Vivado síntese sem warnings
- [ ] Timing met @ target Fmax
- [ ] Relatório recursos preenchido

---

## 11. Próximos Passos Imediatos

1. **Criar `line_buffer_3line.sv`** - Base para paralelismo
2. **Criar `window_3x3_parallel.sv`** - Gera N janelas
3. **Criar `sobel_kernel_parallel.sv`** - N×9 MACs + adder trees
4. **Criar `abs_array.sv` e `magnitude_l1_parallel.sv`** - Estágios finais
5. **Criar `sobel_parallel.sv`** - Integração
6. **Criar `test_sobel_parallel.py`** - Testes cocotb
7. **Executar `make lint` e `make cocotb TEST=test_sobel_parallel`**

---

## 12. Referências

- ESPECIFICACAO_SOBEL.md (Seção 3.3.3)
- Xilinx UG901 - DSP48E1 Slice (adder tree inference)
- Intel FPGA DSP Block User Guide
- "Parallel Image Processing Architectures" - IEEE papers