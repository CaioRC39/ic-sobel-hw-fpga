# Arquitetura Pipeline - Filtro Sobel

**Versão:** 1.0  
**Data:** 2025  
**Status:** Planejamento / Em desenvolvimento

---

## 1. Visão Geral

A arquitetura **pipeline** implementa um pipeline de 7 estágios que processa **1 pixel por ciclo** após o preenchimento inicial (latência). É o equilíbrio ideal entre área e throughput para a maioria das aplicações de visão computacional em tempo real.

### 1.1 Características Principais

| Métrica | Valor |
|---------|-------|
| **Latência** | 7 ciclos (pipeline depth) |
| **Throughput** | 1 pixel/ciclo (após latency) |
| **Área (LUTs)** | ~800 |
| **FFs** | ~600 |
| **DSPs** | 18 (9 para Gx + 9 para Gy) |
| **BRAM (18Kb)** | 2 (line buffers) |
| **Fmax (Artix-7)** | ~200 MHz |
| **Potência** | Média |

---

## 2. Diagrama de Blocos

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            SOBEL_PIPELINE                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────┐   ┌──────────┐   ┌────────────────┐   ┌────────────────┐     │
│  │ line_buf │──▶│ window_3x│──▶│  pipeline_     │──▶│  pipeline_     │     │
│  │ _2line   │   │ 3        │   │  stage_gx      │   │  stage_gy      │     │
│  └──────────┘   └──────────┘   │  (9 MACs +     │   │  (9 MACs +     │     │
│                                │   adder_tree)  │   │   adder_tree)  │     │
│                                └───────┬────────┘   └───────┬────────┘     │
│                                        │                  │               │
│                                        ▼                  ▼               │
│                               ┌────────────────┐   ┌────────────────┐     │
│                               │ pipeline_stage_│   │ pipeline_stage_│     │
│                               │ abs_gx         │   │ abs_gy         │     │
│                               └───────┬────────┘   └───────┬────────┘     │
│                                       │                  │               │
│                                       ▼                  ▼               │
│                               ┌─────────────────────────────────────┐   │
│                               │       pipeline_stage_add            │   │
│                               │    (|Gx| + |Gy|)                    │   │
│                               └──────────────────┬──────────────────┘   │
│                                                  │                      │
│                                                  ▼                      │
│                                         ┌────────────────┐             │
│                                         │ pipeline_stage_│             │
│                                         │ saturate       │             │
│                                         └───────┬────────┘             │
│                                                 │                      │
│                                                 ▼                      │
│                                         ┌────────────────┐             │
│                                         │   pixel_out    │             │
│                                         │   valid_out    │             │
│                                         └────────────────┘             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Estágios do Pipeline (7 Estágios)

### 3.1 Resumo dos Estágios

| Estágio | Nome | Latência | Função | Recursos |
|---------|------|----------|--------|----------|
| **S0** | Line Buffer + Window | 1 | Forma janela 3×3 | 2 BRAM + shift regs |
| **S1** | Convolução Gx | 1 | 9 MACs paralelos + adder tree | 9 DSPs |
| **S2** | Convolução Gy | 1 | 9 MACs paralelos + adder tree | 9 DSPs |
| **S3** | \|Gx\| (ABS) | 1 | Valor absoluto saturating | LUTs |
| **S4** | \|Gy\| (ABS) | 1 | Valor absoluto saturating | LUTs |
| **S5** | \|Gx\| + \|Gy\| | 1 | Soma + saturação parcial | 1 Adder |
| **S6** | Saturação Final | 1 | Clip 0-255 + output reg | LUTs + FFs |

---

### 3.2 Detalhamento por Estágio

---

#### **Estágio S0: Line Buffer + Window Formation**

**Módulos:** `line_buffer_2line` + `window_3x3` (já existem em `common/`)

```systemverilog
// Interface do estágio S0
input  logic                    clk;
input  logic                    rst_n;
input  logic                    valid_in;
input  logic [DATA_WIDTH-1:0]   pixel_in;
input  logic                    last_pixel_in;
input  logic                    last_line_in;

output logic                    valid_s0;
output logic [DATA_WIDTH-1:0]   window_s0 [0:2][0:2];
output logic                    last_pixel_s0;
output logic                    last_line_s0;
```

**Comportamento:**
- `line_buffer_2line` armazena 2 linhas completas (2 × IMG_WIDTH × 8 bits)
- `window_3x3` usa 3 shift registers de 3 elementos cada
- Primeiro pixel válido sai após **2×IMG_WIDTH + 3 ciclos** (preenchimento inicial)
- Em estado estacionário: **1 pixel/ciclo**

---

#### **Estágio S1: Convolução Gx (`pipeline_stage_gx.sv`)**

```systemverilog
module pipeline_stage_gx #(
    parameter int DATA_WIDTH = 8,
    parameter int KERNEL_WIDTH = 4,
    parameter int ACC_WIDTH = 16
)(
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    valid_in,
    input  logic [DATA_WIDTH-1:0]   window [0:2][0:2],
    input  logic                    last_pixel_in,
    input  logic                    last_line_in,
    output logic                    valid_out,
    output logic signed [ACC_WIDTH-1:0] gx_sum,
    output logic                    last_pixel_out,
    output logic                    last_line_out
);

    // Kernel Gx constante (síntese otimiza para constantes)
    localparam logic signed [KERNEL_WIDTH-1:0] KERNEL_GX [0:8] = '{
        -1,  0,  1,   // linha 0
        -2,  0,  2,   // linha 1
        -1,  0,  1    // linha 2
    };

    // 9 multiplicadores paralelos (mapeiam para 9 DSPs)
    logic signed [DATA_WIDTH+KERNEL_WIDTH-1:0] products [0:8];
    
    always_comb begin
        products[0] = $signed({1'b0, window[0][0]}) * KERNEL_GX[0];
        products[1] = $signed({1'b0, window[0][1]}) * KERNEL_GX[1];
        products[2] = $signed({1'b0, window[0][2]}) * KERNEL_GX[2];
        products[3] = $signed({1'b0, window[1][0]}) * KERNEL_GX[3];
        products[4] = $signed({1'b0, window[1][1]}) * KERNEL_GX[4];
        products[5] = $signed({1'b0, window[1][2]}) * KERNEL_GX[5];
        products[6] = $signed({1'b0, window[2][0]}) * KERNEL_GX[6];
        products[7] = $signed({1'b0, window[2][1]}) * KERNEL_GX[7];
        products[8] = $signed({1'b0, window[2][2]}) * KERNEL_GX[8];
    end

    // Adder tree pipelineado (3 níveis registrados)
    logic signed [ACC_WIDTH-1:0] sum_l1 [0:3];
    logic signed [ACC_WIDTH-1:0] sum_l2 [0:1];
    
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sum_l1 <= '0;
            sum_l2 <= '0;
            gx_sum <= '0;
            valid_out <= 1'b0;
            last_pixel_out <= 1'b0;
            last_line_out <= 1'b0;
        end else if (valid_in) begin
            // Nível 1: 4 somas de 2 elementos
            sum_l1[0] <= products[0] + products[1];
            sum_l1[1] <= products[2] + products[3];
            sum_l1[2] <= products[4] + products[5];
            sum_l1[3] <= products[6] + products[7];
            // products[8] passa direto para nível 2
            
            // Nível 2: 2 somas
            sum_l2[0] <= sum_l1[0] + sum_l1[1];
            sum_l2[1] <= sum_l1[2] + sum_l1[3];
            
            // Nível 3: soma final + products[8]
            gx_sum <= sum_l2[0] + sum_l2[1] + products[8];
            
            valid_out <= 1'b1;
            last_pixel_out <= last_pixel_in;
            last_line_out <= last_line_in;
        end else begin
            valid_out <= 1'b0;
        end
    end
endmodule
```

**Recursos:** 9 DSPs (multiplicadores 8×4 → 12 bits) + adder tree em LUTs/FFs

---

#### **Estágio S2: Convolução Gy (`pipeline_stage_gy.sv`)**

Idêntico ao S1, mas com kernel Gy:

```systemverilog
localparam logic signed [KERNEL_WIDTH-1:0] KERNEL_GY [0:8] = '{
    -1, -2, -1,   // linha 0
     0,  0,  0,   // linha 1
     1,  2,  1    // linha 2
};
```

---

#### **Estágio S3: |Gx| ABS (`pipeline_stage_abs.sv`)**

```systemverilog
module pipeline_stage_abs #(
    parameter int IN_WIDTH = 16,
    parameter int OUT_WIDTH = 16
)(
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    valid_in,
    input  logic signed [IN_WIDTH-1:0] in_val,
    input  logic                    last_pixel_in,
    input  logic                    last_line_in,
    output logic                    valid_out,
    output logic [OUT_WIDTH-1:0]    abs_val,
    output logic                    last_pixel_out,
    output logic                    last_line_out
);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            abs_val <= '0;
            valid_out <= 1'b0;
            last_pixel_out <= 1'b0;
            last_line_out <= 1'b0;
        end else if (valid_in) begin
            // Valor absoluto com saturação para MSB
            if (in_val[IN_WIDTH-1]) begin // negativo
                // Tratamento especial: -32768 não tem positivo em 16 bits
                abs_val <= (in_val == {1'b1, {(IN_WIDTH-1){1'b0}}}) ? 
                           {1'b0, {(OUT_WIDTH-1){1'b1}}} : (~in_val + 1'b1);
            end else begin
                abs_val <= in_val[OUT_WIDTH-1:0];
            end
            valid_out <= 1'b1;
            last_pixel_out <= last_pixel_in;
            last_line_out <= last_line_in;
        end else begin
            valid_out <= 1'b0;
        end
    end
endmodule
```

---

#### **Estágio S4: |Gy| ABS**

Instância idêntica do `pipeline_stage_abs` conectada à saída do S2.

---

#### **Estágio S5: Soma |Gx| + |Gy| (`pipeline_stage_add.sv`)**

```systemverilog
module pipeline_stage_add #(
    parameter int IN_WIDTH = 16,
    parameter int OUT_WIDTH = 17  // 16+1 para soma
)(
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    valid_in,
    input  logic [IN_WIDTH-1:0]     abs_gx,
    input  logic [IN_WIDTH-1:0]     abs_gy,
    input  logic                    last_pixel_in,
    input  logic                    last_line_in,
    output logic                    valid_out,
    output logic [OUT_WIDTH-1:0]    magnitude,
    output logic                    last_pixel_out,
    output logic                    last_line_out
);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            magnitude <= '0;
            valid_out <= 1'b0;
            last_pixel_out <= 1'b0;
            last_line_out <= 1'b0;
        end else if (valid_in) begin
            logic [IN_WIDTH:0] sum;
            sum = abs_gx + abs_gy;
            magnitude <= sum[OUT_WIDTH-1:0];
            valid_out <= 1'b1;
            last_pixel_out <= last_pixel_in;
            last_line_out <= last_line_in;
        end else begin
            valid_out <= 1'b0;
        end
    end
endmodule
```

---

#### **Estágio S6: Saturação Final (`pipeline_stage_saturate.sv`)**

```systemverilog
module pipeline_stage_saturate #(
    parameter int IN_WIDTH = 17,
    parameter int OUT_WIDTH = 8
)(
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    valid_in,
    input  logic [IN_WIDTH-1:0]     magnitude_in,
    input  logic                    last_pixel_in,
    input  logic                    last_line_in,
    output logic                    valid_out,
    output logic [OUT_WIDTH-1:0]    pixel_out,
    output logic                    last_pixel_out,
    output logic                    last_line_out
);

    localparam int MAX_VAL = (1 << OUT_WIDTH) - 1; // 255

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pixel_out <= '0;
            valid_out <= 1'b0;
            last_pixel_out <= 1'b0;
            last_line_out <= 1'b0;
        end else if (valid_in) begin
            pixel_out <= (magnitude_in > MAX_VAL) ? MAX_VAL : magnitude_in[OUT_WIDTH-1:0];
            valid_out <= 1'b1;
            last_pixel_out <= last_pixel_in;
            last_line_out <= last_line_in;
        end else begin
            valid_out <= 1'b0;
        end
    end
endmodule
```

---

## 4. Pipeline Register Genérico (`pipeline_reg.sv`)

Já existe em `common/` - usado para propagar sinais de controle (`valid`, `last_pixel`, `last_line`) entre estágios.

```systemverilog
module pipeline_reg #(
    parameter int WIDTH = 1
)(
    input  logic             clk,
    input  logic             rst_n,
    input  logic             valid_in,
    input  logic [WIDTH-1:0] data_in,
    output logic             valid_out,
    output logic [WIDTH-1:0] data_out
);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            valid_out <= 1'b0;
            data_out <= '0;
        end else begin
            valid_out <= valid_in;
            data_out <= data_in;
        end
    end
endmodule
```

---

## 5. Top-Level Pipeline (`sobel_pipeline.sv`)

```systemverilog
module sobel_pipeline #(
    parameter int IMG_WIDTH = 640,
    parameter int IMG_HEIGHT = 480,
    parameter int DATA_WIDTH = 8
)(
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    valid_in,
    input  logic [DATA_WIDTH-1:0]   pixel_in,
    input  logic                    last_pixel_in,
    input  logic                    last_line_in,
    output logic                    valid_out,
    output logic [DATA_WIDTH-1:0]   pixel_out,
    output logic                    last_pixel_out,
    output logic                    last_line_out,
    output logic                    frame_done
);

    // Sinais entre estágios
    logic v_s0, v_s1, v_s2, v_s3, v_s4, v_s5, v_s6;
    logic lp_s0, lp_s1, lp_s2, lp_s3, lp_s4, lp_s5, lp_s6;
    logic ll_s0, ll_s1, ll_s2, ll_s3, ll_s4, ll_s5, ll_s6;
    
    logic [DATA_WIDTH-1:0] window_s0 [0:2][0:2];
    logic signed [15:0] gx_s1, gy_s2;
    logic [15:0] abs_gx_s3, abs_gy_s4;
    logic [16:0] mag_s5;
    logic [DATA_WIDTH-1:0] pixel_s6;

    // S0: Line Buffer + Window
    line_buffer_2line #(.WIDTH(IMG_WIDTH), .DATA_WIDTH(DATA_WIDTH)) lb_inst (
        .clk(clk), .rst_n(rst_n),
        .valid_in(valid_in), .pixel_in(pixel_in),
        .last_pixel_in(last_pixel_in), .last_line_in(last_line_in),
        .valid_out(v_s0),
        .line0_out(/*nc*/), .line1_out(/*nc*/), .curr_out(/*nc*/)  // internos
    );
    
    window_3x3 #(.DATA_WIDTH(DATA_WIDTH)) win_inst (
        .clk(clk), .rst_n(rst_n),
        .valid_in(v_s0),
        .line0(/* de lb */), .line1(/* de lb */), .curr(/* de lb */),
        .valid_out(v_s0),  // mesmo valid
        .window(window_s0)
    );

    // S1: Gx
    pipeline_stage_gx #(.DATA_WIDTH(DATA_WIDTH)) gx_inst (
        .clk(clk), .rst_n(rst_n),
        .valid_in(v_s0), .window(window_s0),
        .last_pixel_in(lp_s0), .last_line_in(ll_s0),
        .valid_out(v_s1), .gx_sum(gx_s1),
        .last_pixel_out(lp_s1), .last_line_out(ll_s1)
    );

    // S2: Gy
    pipeline_stage_gy #(.DATA_WIDTH(DATA_WIDTH)) gy_inst (
        .clk(clk), .rst_n(rst_n),
        .valid_in(v_s0), .window(window_s0),
        .last_pixel_in(lp_s0), .last_line_in(ll_s0),
        .valid_out(v_s2), .gy_sum(gy_s2),
        .last_pixel_out(lp_s2), .last_line_out(ll_s2)
    );

    // S3: |Gx|
    pipeline_stage_abs #(.IN_WIDTH(16), .OUT_WIDTH(16)) abs_gx_inst (
        .clk(clk), .rst_n(rst_n),
        .valid_in(v_s1), .in_val(gx_s1),
        .last_pixel_in(lp_s1), .last_line_in(ll_s1),
        .valid_out(v_s3), .abs_val(abs_gx_s3),
        .last_pixel_out(lp_s3), .last_line_out(ll_s3)
    );

    // S4: |Gy|
    pipeline_stage_abs #(.IN_WIDTH(16), .OUT_WIDTH(16)) abs_gy_inst (
        .clk(clk), .rst_n(rst_n),
        .valid_in(v_s2), .in_val(gy_s2),
        .last_pixel_in(lp_s2), .last_line_in(ll_s2),
        .valid_out(v_s4), .abs_val(abs_gy_s4),
        .last_pixel_out(lp_s4), .last_line_out(ll_s4)
    );

    // S5: |Gx| + |Gy|
    pipeline_stage_add #(.IN_WIDTH(16), .OUT_WIDTH(17)) add_inst (
        .clk(clk), .rst_n(rst_n),
        .valid_in(v_s3 & v_s4),  // ambos prontos no mesmo ciclo
        .abs_gx(abs_gx_s3), .abs_gy(abs_gy_s4),
        .last_pixel_in(lp_s3), .last_line_in(ll_s3),
        .valid_out(v_s5), .magnitude(mag_s5),
        .last_pixel_out(lp_s5), .last_line_out(ll_s5)
    );

    // S6: Saturação
    pipeline_stage_saturate #(.IN_WIDTH(17), .OUT_WIDTH(DATA_WIDTH)) sat_inst (
        .clk(clk), .rst_n(rst_n),
        .valid_in(v_s5), .magnitude_in(mag_s5),
        .last_pixel_in(lp_s5), .last_line_in(ll_s5),
        .valid_out(v_s6), .pixel_out(pixel_s6),
        .last_pixel_out(lp_s6), .last_line_out(ll_s6)
    );

    // Saídas
    assign valid_out = v_s6;
    assign pixel_out = pixel_s6;
    assign last_pixel_out = lp_s6;
    assign last_line_out = ll_s6;
    assign frame_done = v_s6 & lp_s6 & ll_s6;

endmodule
```

---

## 6. Timing e Latência

### 6.1 Pipeline de Entrada (Preenchimento)

```
Ciclo:    1    2    3    ...  2W    2W+1  2W+2  2W+3  2W+4  ...
          │    │    │         │     │     │     │     │
LB:       └────┴────┴─────────┴─────┘     │     │     │
Win:                    └─────────────────┘     │     │
S1:                                        └─────┘     │
S2:                                        └─────┘     │
S3:                                               └─────┘ │
S4:                                               └─────┘ │
S5:                                                   └─────┘
S6:                                                         └─────▶ prime pixel_out
```

**Primeiro pixel válido:** ciclo `2×IMG_WIDTH + 3 + 7 = 2×IMG_WIDTH + 10`

### 6.2 Estado Estacionário

Após preenchimento: **1 pixel/ciclo continuamente**

| Métrica | Valor (640×480) |
|---------|-----------------|
| Ciclos/frame | 640 × 480 = 307.200 |
| Tempo @ 100 MHz | 3,072 ms |
| **FPS** | **325 fps** |
| Tempo @ 200 MHz | 1,536 ms |
| **FPS @ 200 MHz** | **650 fps** |

---

## 7. Gerenciamento de Borda

### 7.1 Estratégia: Replicação de Borda (feita no Line Buffer + Window)

O `line_buffer_2line` e `window_3x3` (em `common/`) já implementam:

- **Primeira linha:** line0 = line1 = primeira linha real
- **Última linha:** replica última linha
- **Primeira coluna:** window[:,0] = window[:,1]  
- **Última coluna:** window[:,2] = window[:,1]
- **Cantos:** replicação 2D consistente

### 7.2 Sinais de Controle

- `last_pixel_in` / `last_pixel_out`: fim de linha
- `last_line_in` / `last_line_out`: fim de frame
- Propagam através de todos os 7 estágios via `pipeline_reg`

---

## 8. Verificação (Testbench cocotb)

### 8.1 Testes Obrigatórios

| Teste | Descrição |
|-------|-----------|
| `test_pipeline_reset` | Reset assíncrono, estado IDLE |
| `test_pipeline_latency` | Mede latência exata (7 ciclos + preenchimento) |
| `test_pipeline_throughput` | Verifica 1 pixel/ciclo sustentado |
| `test_pipeline_3x3_image` | Imagem 3×3, todos 9 pixels de saída |
| `test_pipeline_640x480` | Frame completo vs golden OpenCV |
| `test_pipeline_edge_cases` | 1×1, 2×2, linha única, coluna única |
| `test_pipeline_backpressure` | valid_in intermitente |
| `test_pipeline_frame_boundary` | Transição frame N → frame N+1 |

### 8.2 Modelo de Referência

```python
# models/sobel_reference.py
import cv2
import numpy as np

def sobel_l1_pipeline_reference(img):
    """Referência funcional para pipeline (1 pixel/ciclo)"""
    gx = cv2.Sobel(img, cv2.CV_16S, 1, 0, ksize=3, borderType=cv2.BORDER_REPLICATE)
    gy = cv2.Sobel(img, cv2.CV_16S, 0, 1, ksize=3, borderType=cv2.BORDER_REPLICATE)
    mag = np.abs(gx) + np.abs(gy)
    return np.clip(mag, 0, 255).astype(np.uint8)
```

### 8.3 Cobertura

- **Code coverage:** Line ≥ 95%, Toggle ≥ 90%
- **FSM coverage:** Não aplicável (pipeline sem FSM complexa)
- **Functional:** Bordas, cantos, valores 0/255, transições linha/frame

---

## 9. Síntese e Constraints

### 9.1 XDC (Xilinx Artix-7)

```tcl
# Clock 100 MHz (período 10ns) - target 200 MHz = 5ns
create_clock -period 5.00 -name clk [get_ports clk]

# Input delays (2ns)
set_input_delay -clock clk -max 2.0 [get_ports {pixel_in valid_in last_pixel_in last_line_in}]
set_input_delay -clock clk -min -0.5 [get_ports {pixel_in valid_in last_pixel_in last_line_in}]

# Output delays (2ns)
set_output_delay -clock clk -max 2.0 [get_ports {pixel_out valid_out last_pixel_out last_line_out frame_done}]
set_output_delay -clock clk -min -0.5 [get_ports {pixel_out valid_out last_pixel_out last_line_out frame_done}]

# Reset async
set_false_path -from [get_ports rst_n]

# Pipeline stages - opcional multicycle se timing apertado
# set_multicycle_path 2 -from [get_pins *pipeline_stage_gx*] -to [get_pins *pipeline_stage_gy*]
```

### 9.2 SDC (Intel Quartus)

```tcl
create_clock -name clk -period 5.00 [get_ports clk]
set_input_delay -clock clk -max 2.0 [get_ports {pixel_in valid_in last_pixel_in last_line_in}]
set_output_delay -clock clk -max 2.0 [get_ports {pixel_out valid_out last_pixel_out last_line_out frame_done}]
set_false_path -from [get_ports rst_n]
```

### 9.3 Atributos de Síntese

```systemverilog
// Forçar inferência de DSP
(* use_dsp = "yes" *) logic signed [11:0] products [0:8];

// Pipeline registers não otimizados
(* dont_touch = "true" *) logic valid_s1, valid_s2, ...;

// BRAM style para line buffers
(* ram_style = "block" *) logic [7:0] line_buffer [0:639];
```

---

## 10. Tabela Comparativa Final (Projeção)

| Métrica | Multiciclo | **Pipeline** | Paralela 2×2 | Paralela 3×3 |
|---------|------------|--------------|--------------|--------------|
| **Latência** | ~15 ciclos | **7 ciclos** | 6 ciclos | 5 ciclos |
| **Throughput** | 1/15 pix/clk | **1 pix/clk** | 4 pix/clk | 9 pix/clk |
| **LUTs** | ~200 | **~800** | ~2.500 | ~5.500 |
| **FFs** | ~150 | **~600** | ~2.000 | ~4.500 |
| **DSPs** | 1 | **18** | 72 | 162 |
| **BRAM** | 2 | **2** | 4 | 6 |
| **Fmax (Artix-7)** | ~250 MHz | **~200 MHz** | ~150 MHz | ~120 MHz |
| **Potência** | Muito Baixa | **Baixa** | Alta | Muito Alta |
| **FPS @ 100MHz (640×480)** | 6,8 | **325** | 1.300 | 2.930 |

---

## 11. Checklist de Implementação

### 11.1 RTL
- [ ] `pipeline_stage_gx.sv`
- [ ] `pipeline_stage_gy.sv`
- [ ] `pipeline_stage_abs.sv`
- [ ] `pipeline_stage_add.sv`
- [ ] `pipeline_stage_saturate.sv`
- [ ] `sobel_pipeline.sv` (integração)
- [ ] Verible lint **ZERO warnings**
- [ ] Verilator `--lint-only -Wall` **ZERO warnings**

### 11.2 Verificação
- [ ] `test_sobel_pipeline.py`
- [ ] Cobertura código ≥ 95%
- [ ] Golden reference match (erro = 0)
- [ ] Throughput 1 pixel/ciclo verificado

### 11.3 Síntese
- [ ] Vivado síntese sem warnings
- [ ] Timing met @ 200 MHz (Artix-7)
- [ ] Relatório recursos preenchido

---

## 12. Próximos Passos Imediatos

1. **Criar `pipeline_stage_gx.sv`** - Estágio S1 (9 MACs + adder tree)
2. **Criar `pipeline_stage_gy.sv`** - Estágio S2 (idêntico, kernel diferente)
3. **Criar `pipeline_stage_abs.sv`** - Estágios S3/S4
4. **Criar `pipeline_stage_add.sv`** - Estágio S5
5. **Criar `pipeline_stage_saturate.sv`** - Estágio S6
6. **Criar `sobel_pipeline.sv`** - Integração top-level
7. **Criar `test_sobel_pipeline.py`** - Testes cocotb
8. **Executar `make lint` e `make cocotb TEST=test_sobel_pipeline`**

---

## 13. Referências

- ESPECIFICACAO_SOBEL.md (Seção 3.3.2)
- Xilinx UG901 - Vivado Synthesis Guide (DSP inference, pipeline)
- "Digital Image Processing" - Gonzalez & Woods (Sobel operator)
- IEEE 1800-2017 - SystemVerilog LRM