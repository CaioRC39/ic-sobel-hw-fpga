# Especificação Técnica: Filtro Sobel em FPGA (SystemVerilog)

**Versão:** 1.0  
**Data:** 2025  
**Autor:** Iniciação Científica - FPGA Sobel Filter  
**Objetivo:** Implementação, verificação e comparação de 3 arquiteturas de filtro Sobel em FPGA

---

## 1. Visão Geral do Projeto

### 1.1 Objetivo
Implementar, verificar e comparar três arquiteturas de filtro Sobel em FPGA utilizando SystemVerilog, com verificação via cocotb/Verilator e linting com Verible.

### 1.2 Arquiteturas a Implementar

| Arquitetura | Descrição | Latência | Throughput | Área |
|-------------|-----------|----------|------------|------|
| **Multiciclo** | Reutiliza unidades aritméticas (MAC) em múltiplos ciclos | ~9-12 ciclos/pixel | 1 pixel/9-12 ciclos | Menor área |
| **Pipeline** | Pipeline de N estágios, 1 pixel por ciclo após latency | ~N ciclos (latency) | 1 pixel/ciclo | Média |
| **Paralela** | Processa múltiplos pixels por ciclo (ex: 2×2 ou 3×3) | ~1-2 ciclos | 4-9 pixels/ciclo | Maior área |

---

## 2. Especificação do Algoritmo Sobel

### 2.1 Kernels de Convolução 3×3

```
Gx = | -1  0  +1 |     Gy = | -1 -2 -1 |
     | -2  0  +2 |          |  0  0  0 |
     | -1  0  +1 |          | +1 +2 +1 |
```

### 2.2 Cálculo do Gradiente

```
Gx = Σ(kernel_x[i][j] × pixel[i][j])
Gy = Σ(kernel_y[i][j] × pixel[i][j])

Magnitude = |Gx| + |Gy|  (aproximação L1 - mais eficiente em HW)
           ou
Magnitude = sqrt(Gx² + Gy²)  (L2 - mais preciso, mais caro em HW)
```

**Decisão de projeto:** Usar aproximação L1 (`|Gx| + |Gy|`) para eficiência de hardware.

### 2.3 Entrada/Saída

| Sinal | Largura | Descrição |
|-------|---------|-----------|
| `pixel_in` | 8 bits | Pixel de entrada (grayscale 0-255) |
| `pixel_out` | 8 bits | Magnitude do gradiente (0-255, saturado) |
| `valid_in` | 1 bit | Valida pixel de entrada |
| `valid_out` | 1 bit | Valida pixel de saída |
| `clk` | 1 bit | Clock |
| `rst_n` | 1 bit | Reset assíncrono ativo baixo |

### 2.4 Janela 3×3 (Line Buffer)

Necessário armazenar 2 linhas completas + 3 pixels da linha atual para formar janela 3×3.

```
Line Buffer 0 (linha y-2):  [p00 p01 p02 ... p0(W-1)]
Line Buffer 1 (linha y-1):  [p10 p11 p12 ... p1(W-1)]
Linha atual (linha y):      [p20 p21 p22 ...]  (streaming)
                            ↓
Janela 3×3 deslizando:
[p00 p01 p02]
[p10 p11 p12]
[p20 p21 p22]
```

---

## 3. Especificação dos Módulos (Modularidade Obrigatória)

### 3.1 Hierarquia de Módulos

```
sobel_top (top-level)
├── sobel_multicycle
│   ├── line_buffer_2line
│   ├── window_3x3
│   ├── sobel_mac_multicycle (MAC reutilizado)
│   │   ├── mac_unit
│   │   ├── mac_control_fsm
│   │   └── abs_saturate
│   └── magnitude_l1
├── sobel_pipeline
│   ├── line_buffer_2line
│   ├── window_3x3
│   ├── pipeline_stage_gx (estágio 1: convolução Gx)
│   ├── pipeline_stage_gy (estágio 2: convolução Gy)
│   ├── pipeline_stage_abs_gx
│   ├── pipeline_stage_abs_gy
│   ├── pipeline_stage_add (|Gx| + |Gy|)
│   └── pipeline_stage_saturate
└── sobel_parallel
    ├── line_buffer_2line (ou line_buffer_3line para 3 linhas)
    ├── window_3x3_parallel (janelas 2×2 ou 3×3 paralelas)
    ├── sobel_kernel_parallel (9 MACs paralelos para Gx)
    ├── sobel_kernel_parallel (9 MACs paralelos para Gy)
    ├── abs_array_gx (9 ABS paralelos)
    ├── abs_array_gy (9 ABS paralelos)
    ├── adder_tree_gx (árvore de soma Gx)
    ├── adder_tree_gy (árvore de soma Gy)
    └── magnitude_l1_parallel
```

### 3.2 Módulos Comuns (Compartilhados)

#### 3.2.1 `line_buffer_2line`
```systemverilog
module line_buffer_2line #(
    parameter int WIDTH = 640,
    parameter int DATA_WIDTH = 8
)(
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    valid_in,
    input  logic [DATA_WIDTH-1:0]   pixel_in,
    output logic                    valid_out,
    output logic [DATA_WIDTH-1:0]   line0_out,  // linha y-2
    output logic [DATA_WIDTH-1:0]   line1_out,  // linha y-1
    output logic [DATA_WIDTH-1:0]   curr_out    // pixel atual (y)
);
```

#### 3.2.2 `window_3x3`
```systemverilog
module window_3x3 #(
    parameter int DATA_WIDTH = 8
)(
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    valid_in,
    input  logic [DATA_WIDTH-1:0]   line0,
    input  logic [DATA_WIDTH-1:0]   line1,
    input  logic [DATA_WIDTH-1:0]   curr,
    output logic                    valid_out,
    output logic [DATA_WIDTH-1:0]   window [0:2][0:2]  // janela 3x3
);
```

#### 3.2.3 `mac_unit` (MAC Unit - Multiply-Accumulate)
```systemverilog
module mac_unit #(
    parameter int DATA_WIDTH = 8,
    parameter int KERNEL_WIDTH = 4,  // -2 a +2 precisa de 4 bits signed
    parameter int ACC_WIDTH = 16
)(
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    enable,
    input  logic signed [DATA_WIDTH-1:0]    pixel,
    input  logic signed [KERNEL_WIDTH-1:0]  kernel,
    output logic signed [ACC_WIDTH-1:0]     acc_out
);
```

#### 3.2.4 `abs_saturate`
```systemverilog
module abs_saturate #(
    parameter int IN_WIDTH = 16,
    parameter int OUT_WIDTH = 8
)(
    input  logic signed [IN_WIDTH-1:0]  in_val,
    output logic [OUT_WIDTH-1:0]        out_val
);
```

#### 3.2.5 `magnitude_l1`
```systemverilog
module magnitude_l1 #(
    parameter int GX_WIDTH = 16,
    parameter int GY_WIDTH = 16,
    parameter int OUT_WIDTH = 8
)(
    input  logic signed [GX_WIDTH-1:0]  gx,
    input  logic signed [GY_WIDTH-1:0]  gy,
    output logic [OUT_WIDTH-1:0]        magnitude
);
```

---

### 3.3 Módulos Específicos por Arquitetura

#### 3.3.1 Multiciclo (`sobel_multicycle`)

**FSM de Controle (9 ciclos para convolução 3×3):**
```
IDLE → LOAD_WIN → MAC_GX_0 → MAC_GX_1 → ... → MAC_GX_8 
     → MAC_GY_0 → MAC_GY_1 → ... → MAC_GY_8 
     → ABS_GX → ABS_GY → ADD_MAG → SATURATE → OUTPUT → IDLE
```

**Módulos específicos:**
- `mac_control_fsm` - FSM de 11 estados
- `mac_unit` - 1 instância reutilizada (time-multiplexed)
- `kernel_rom_gx` / `kernel_rom_gy` - ROMs com kernels

#### 3.3.2 Pipeline (`sobel_pipeline`)

**Estágios do Pipeline (7 estágios sugeridos):**
```
S0: Line Buffer + Window Formation      (valid_in)
S1: Convolução Gx (9 MACs paralelos)    → gx_sum
S2: Convolução Gy (9 MACs paralelos)    → gy_sum
S3: |Gx| (ABS)                          → abs_gx
S4: |Gy| (ABS)                          → abs_gy
S5: |Gx| + |Gy| (Adder)                 → magnitude
S6: Saturação 8-bit + Output Register   → pixel_out, valid_out
```

**Módulos específicos:**
- `pipeline_stage_gx` - 9 MACs paralelos + adder tree
- `pipeline_stage_gy` - 9 MACs paralelos + adder tree
- `pipeline_stage_abs` - ABS saturating
- `pipeline_stage_add` - Soma + saturação
- `pipeline_reg` - Registradores de pipeline genéricos

#### 3.3.3 Paralela (`sobel_parallel`)

**Configuração:** Processa janela 3×3 completa por ciclo (9 MACs Gx + 9 MACs Gy paralelos)

**Módulos específicos:**
- `sobel_kernel_parallel_gx` - 9 MACs + adder tree para Gx
- `sobel_kernel_parallel_gy` - 9 MACs + adder tree para Gy
- `magnitude_l1_parallel` - ABS + soma + saturação paralelos
- `line_buffer_3line` - 3 line buffers para janela 3×3 completa
- `window_3x3_parallel` - Janela completa 3×3 disponível por ciclo

---

## 4. Interface Comum (Top-Level)

### 4.1 `sobel_top`
```systemverilog
module sobel_top #(
    parameter int IMG_WIDTH  = 640,
    parameter int IMG_HEIGHT = 480,
    parameter int DATA_WIDTH = 8,
    parameter enum logic [1:0] {MULTICYCLE=2'b00, PIPELINE=2'b01, PARALLEL=2'b10} ARCH = PIPELINE
)(
    input  logic                    clk,
    input  logic                    rst_n,
    // Interface de streaming
    input  logic                    valid_in,
    input  logic [DATA_WIDTH-1:0]   pixel_in,
    input  logic                    last_pixel_in,  // fim de linha/frame
    output logic                    valid_out,
    output logic [DATA_WIDTH-1:0]   pixel_out,
    output logic                    last_pixel_out,
    // Configuração
    input  logic [1:0]              arch_sel,       // seleciona arquitetura em runtime
    output logic                    busy,           // core ocupado (multiciclo)
    output logic                    frame_done      // frame processado
);
```

---

## 5. Verificação (cocotb + Verilator)

### 5.1 Testbench Estrutura
```
tb/
├── tb_sobel_top.sv              # TB SystemVerilog (Verilator)
├── test_sobel_multicycle.py     # cocotb test multicycle
├── test_sobel_pipeline.py       # cocotb test pipeline
├── test_sobel_parallel.py       # cocotb test parallel
├── test_sobel_common.py         # Testes comuns (line buffer, window, MAC)
├── models/
│   └── sobel_reference.py       # Modelo de referência Python (OpenCV/NumPy)
├── test_images/
│   ├── test_640x480.png
│   ├── test_320x240.png
│   └── edge_cases.png
└── Makefile
```

### 5.2 Testes Obrigatórios por Módulo

| Módulo | Testes |
|--------|--------|
| `line_buffer_2line` | Preenchimento inicial, transição linha, fim de frame |
| `window_3x3` | Janela correta em bordas, cantos, centro |
| `mac_unit` | Acúmulo correto, overflow, signed/unsigned |
| `abs_saturate` | Valores negativos, positivos, saturação 255 |
| `magnitude_l1` | Combinações Gx/Gy, saturação 255 |
| `sobel_multicycle` | FSM states, latência correta, pixels de borda |
| `sobel_pipeline` | Throughput 1 pixel/ciclo, latência correta, stall |
| `sobel_parallel` | Throughput N pixels/ciclo, bordas, throughput sustentado |
| `sobel_top` | Seleção de arquitetura runtime, frame completo, comparação golden |

### 5.3 Testes de Imagem (Golden Reference)
- Imagem de referência: OpenCV `cv2.Sobel()` + magnitude L1
- Comparação pixel-a-pixel (erro = 0 tolerado para L1)
- Métricas: PSNR, SSIM, taxa de erro de pixel
- Testes de borda: imagem 1×1, 2×2, 3×3, linha única, coluna única

### 5.4 Métricas de Cobertura (Verilator + cocotb)
- **Code coverage:** Line, toggle, FSM state, branch
- **Functional coverage:** Todos os estados FSM, bordas de imagem, valores extremos (0, 255)
- **Performance:** Latência, throughput, frequência máxima (timing analysis)

---

## 6. Linting e Formatação (Verible)

### 6.1 Regras Verible Obrigatórias
```bash
verible-verilog-format --indentation_spaces=4 --indentation_size=4
verible-verilog-lint --rules=+line-length=120,+parameter-name-style=UPPER_SNAKE_CASE
```

### 6.2 Regras de Estilo Obrigatórias
- `parameter` em `UPPER_SNAKE_CASE`
- `signal` e `variable` em `lower_snake_case`
- `module`/`class`/`typedef` em `PascalCase`
- `enum` em `PascalCase`, valores em `UPPER_SNAKE_CASE`
- Indentação 4 espaços, sem tabs
- Linhas ≤ 120 colunas
- `begin`/`end` em linhas separadas para blocos > 1 linha
- `always_comb`/`always_ff`/`always_latch` explícitos
- `logic` ao invés de `reg`/`wire`

---

## 7. Síntese e Implementação (FPGA)

### 7.1 Targets Suportados
- **Xilinx:** Artix-7, Kintex-7, UltraScale+
- **Intel/Altera:** Cyclone V, Cyclone 10, Stratix 10, Agilex
- **Lattice:** ECP5, Nexus
- **Genérico:** ASIC (via synthesis constraints)

### 7.2 Constraints (XDC/SDC)
```tcl
# Clock constraint (ex: 100 MHz)
create_clock -period 10.00 -name clk [get_ports clk]

# Input/output delays
set_input_delay -clock clk -max 2.0 [get_ports pixel_in]
set_input_delay -clock clk -max 2.0 [get_ports valid_in]
set_output_delay -clock clk -max 2.0 [get_ports pixel_out]
set_output_delay -clock clk -max 2.0 [get_ports valid_out]

# False paths (reset assíncrono)
set_false_path -from [get_ports rst_n]
```

### 7.3 Métricas de Comparação (Tabela Final do Artigo)

| Métrica | Multiciclo | Pipeline | Paralela (2×2) | Paralela (3×3) |
|---------|------------|----------|----------------|----------------|
| **Latência (ciclos)** | ~11 | 7 | 2 | 1 |
| **Throughput (pix/clk)** | 1/11 | 1 | 4 | 9 |
| **LUTs** | ~200 | ~800 | ~2500 | ~5500 |
| **FFs** | ~150 | ~600 | ~2000 | ~4500 |
| **DSPs** | 1 | 18 | 72 | 162 |
| **BRAM (18Kb)** | 2 | 2 | 4 | 6 |
| **Fmax (Artix-7)** | ~250 MHz | ~200 MHz | ~150 MHz | ~120 MHz |
| **Potência (est.)** | Baixa | Média | Alta | Muito Alta |

---

## 8. Estrutura de Diretórios do Projeto

```
ic-sobel-hw-fpga/
├── CLAUDE.md                     # Este arquivo
├── docs/
│   ├── ESPECIFICACAO_SOBEL.md    # Este arquivo
│   ├── ARQUITETURA_MULTICICLO.md
│   ├── ARQUITETURA_PIPELINE.md
│   └── ARQUITETURA_PARALELA.md
├── rtl/
│   ├── common/
│   │   ├── line_buffer_2line.sv
│   │   ├── window_3x3.sv
│   │   ├── mac_unit.sv
│   │   ├── abs_saturate.sv
│   │   ├── magnitude_l1.sv
│   │   └── kernel_rom.sv
│   ├── multicycle/
│   │   ├── sobel_multicycle.sv
│   │   ├── mac_control_fsm.sv
│   │   └── mac_multicycle.sv
│   ├── pipeline/
│   │   ├── sobel_pipeline.sv
│   │   ├── pipeline_stage_gx.sv
│   │   ├── pipeline_stage_gy.sv
│   │   ├── pipeline_stage_abs.sv
│   │   ├── pipeline_stage_add.sv
│   │   └── pipeline_reg.sv
│   ├── parallel/
│   │   ├── sobel_parallel.sv
│   │   ├── sobel_kernel_parallel.sv
│   │   ├── line_buffer_3line.sv
│   │   ├── window_3x3_parallel.sv
│   │   └── magnitude_l1_parallel.sv
│   └── sobel_top.sv
├── tb/
│   ├── tb_sobel_top.sv
│   ├── Makefile
│   ├── test_sobel_multicycle.py
│   ├── test_sobel_pipeline.py
│   ├── test_sobel_parallel.py
│   ├── test_sobel_common.py
│   ├── models/sobel_reference.py
│   └── test_images/
├── sim/
│   └── Makefile.verilator
├── lint/
│   └── verible.rules
├── syn/
│   ├── xilinx/
│   ├── intel/
│   └── constraints/
├── scripts/
│   ├── run_sim.py
│   ├── run_lint.py
│   └── run_synth.py
└── Makefile
```

---

## 9. Cronograma Sugerido (Iniciação Científica)

| Semana | Atividade | Entregável |
|--------|-----------|------------|
| 1-2 | Estudo SystemVerilog, Verilator, cocotb, Verible | Relatório de estudo |
| 3-4 | Módulos comuns (line_buffer, window, MAC, ABS, mag) + TB | RTL + TB comum |
| 5-6 | Arquitetura Multiciclo + FSM + TB | RTL + TB Multiciclo |
| 7-8 | Arquitetura Pipeline + TB | RTL + TB Pipeline |
| 9-10 | Arquitetura Paralela (2×2 e 3×3) + TB | RTL + TB Paralela |
| 11 | Top-level + seleção runtime + TB integrado | RTL Top + TB Top |
| 12 | Verificação completa (cobertura 100%) | Relatório cobertura |
| 13 | Síntese FPGA (Xilinx/Intel) + timing analysis | Relatório síntese |
| 14 | Coleta métricas (área, freq, potência) | Tabela comparativa |
| 15-16 | Redação artigo + preparação apresentação | Artigo + Slides |

---

## 10. Critérios de Aceitação (Definition of Done)

### 10.1 Por Módulo
- [ ] SystemVerilog sintetizável (sem `initial`, sem `fork/join`, sem `delay`)
- [ ] Verible lint **ZERO warnings/errors**
- [ ] Cobertura de código ≥ 95% (line/toggle/FSM)
- [ ] Cobertura funcional 100% (estados FSM, bordas, valores extremos)
- [ ] Testbench cocotb passa com modelo de referência (erro = 0)
- [ ] Documentação do módulo (header com parâmetros, portas, função)

### 10.2 Por Arquitetura
- [ ] Todos os módulos verificados individualmente
- [ ] Integração top-level verificada
- [ ] Throughput/latência medidos e conferidos
- [ ] Síntese bem-sucedida (sem latches, timing met)
- [ ] Tabela de recursos preenchida

### 10.3 Projeto Completo
- [ ] 3 arquiteturas funcionais e verificadas
- [ ] Top-level com seleção runtime
- [ ] Artigo/report com tabela comparativa completa
- [ ] Apresentação técnica preparada
- [ ] Código no GitHub com CI (Verilator + cocotb + Verible)

---

## 11. Referências Técnicas

1. **IEEE 1800-2017/2023** - SystemVerilog LRM
2. **Gonzalez & Woods** - Digital Image Processing (Sobel operator)
3. **Xilinx UG901** - Vivado Synthesis Guide
4. **Intel FPGA SDK** - Best Practices for Pipeline/Parallel
5. **Verilator Manual** - Linting e coverage
6. **cocotb Documentation** - Testbench patterns
7. **Verible Style Guide** - Google Hardware Style

---

## 12. Decisões de Projeto (Registro para Defesa)

| Decisão | Justificativa | Trade-off |
|---------|---------------|-----------|
| L1 magnitude (`|Gx|+|Gy|`) | Sem multiplicador/raiz, 1 adder apenas | Menor precisão vs L2 |
| Kernel ROM (não hardcoded) | Flexibilidade, reuso, síntese otimizada | 1 ciclo extra leitura ROM |
| Line buffer 2 linhas (não 3) | Economia BRAM, streaming natural | Requer window_3x3 extra |
| Pipeline 7 estágios | Balanceamento latência/throughput | Mais registradores que 5 estágios |
| Paralela 3×3 = 9 MACs | Máximo throughput teórico | Alto uso DSP/BRAM |
| Reset assíncrono ativo baixo | Padrão FPGA/ASIC, evita metastabilidade | Requer sincronização interna |

---

*Documento vivo - Atualizar conforme decisões de projeto*