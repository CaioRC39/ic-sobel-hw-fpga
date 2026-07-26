# Arquitetura Multiciclo - Filtro Sobel

**Versão:** 1.0  
**Data:** 2025  
**Status:** Planejamento / Em desenvolvimento

---

## 1. Visão Geral

A arquitetura **multiciclo** reutiliza uma única unidade MAC (Multiply-Accumulate) para processar os 9 coeficientes do kernel Sobel sequencialmente, alternando entre Gx e Gy. É a arquitetura de **menor área**, ideal para FPGAs pequenas ou quando o throughput de 1 pixel a cada ~11 ciclos é aceitável.

### 1.1 Características Principais

| Métrica | Valor |
|---------|-------|
| **Latência** | ~11 ciclos/pixel (após pipeline de line buffer + window) |
| **Throughput** | 1 pixel / 11 ciclos |
| **Área (LUTs)** | ~200 |
| **FFs** | ~150 |
| **DSPs** | 1 |
| **BRAM (18Kb)** | 2 (line buffers) |
| **Fmax (Artix-7)** | ~250 MHz |

---

## 2. Diagrama de Blocos

```
┌─────────────────────────────────────────────────────────────────┐
│                      SOBEL_MULTICYCLE                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌──────────────┐    ┌──────────────┐    ┌────────────────┐   │
│   │ line_buffer_ │    │  window_3x3  │    │  mac_control_  │   │
│   │   2line      │───▶│              │───▶│      fsm       │   │
│   └──────────────┘    └──────────────┘    └───────┬────────┘   │
│                                                  │              │
│                              ┌───────────────────┼───────────┐  │
│                              ▼                   ▼           ▼  │
│                       ┌─────────────┐    ┌─────────────┐  ┌─────┐
│                       │  kernel_rom │    │  mac_unit   │  │ ROM │
│                       │    (Gx/Gy)  │    │  (1x DSP)   │  │addr │
│                       └──────┬──────┘    └──────┬──────┘  └─────┘
│                              │                  │
│                              ▼                  ▼
│                       ┌─────────────────────────────────┐
│                       │     magnitude_l1 (|Gx|+|Gy|)    │
│                       └──────────────┬──────────────────┘
│                                      ▼
│                              ┌──────────────┐
│                              │ abs_saturate │
│                              └──────┬───────┘
│                                     ▼
│                              ┌──────────────┐
│                              │   pixel_out  │
│                              └──────────────┘
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. FSM de Controle (mac_control_fsm)

### 3.1 Estados da FSM (11 estados)

```systemverilog
typedef enum logic [3:0] {
    S_IDLE        = 4'd0,   // Aguarda valid_in
    S_LOAD_WIN    = 4'd1,   // Carrega janela 3x3 (1 ciclo)
    S_MAC_GX_0    = 4'd2,   // MAC Gx coef [0]
    S_MAC_GX_1    = 4'd3,   // MAC Gx coef [1]
    S_MAC_GX_2    = 4'd4,   // MAC Gx coef [2]
    S_MAC_GX_3    = 4'd5,   // MAC Gx coef [3]
    S_MAC_GX_4    = 4'd6,   // MAC Gx coef [4]
    S_MAC_GX_5    = 4'd7,   // MAC Gx coef [5]
    S_MAC_GX_6    = 4'd8,   // MAC Gx coef [6]
    S_MAC_GX_7    = 4'd9,   // MAC Gx coef [7]
    S_MAC_GX_8    = 4'd10,  // MAC Gx coef [8]
    S_MAC_GY_0    = 4'd11,  // MAC Gy coef [0]
    S_MAC_GY_1    = 4'd12,  // MAC Gy coef [1]
    S_MAC_GY_2    = 4'd13,  // MAC Gy coef [2]
    S_MAC_GY_3    = 4'd14,  // MAC Gy coef [3]
    S_MAC_GY_4    = 4'd15,  // MAC Gy coef [4]
    S_MAC_GY_5    = 4'd16,  // MAC Gy coef [5]
    S_MAC_GY_6    = 4'd17,  // MAC Gy coef [6]
    S_MAC_GY_7    = 4'd18,  // MAC Gy coef [7]
    S_MAC_GY_8    = 4'd19,  // MAC Gy coef [8]
    S_ABS_GX      = 4'd20,  // |Gx|
    S_ABS_GY      = 4'd21,  // |Gy|
    S_ADD_MAG     = 4'd22,  // |Gx| + |Gy|
    S_SATURATE    = 4'd23,  // Saturação 8-bit
    S_OUTPUT      = 4'd24   // Saída + valid_out
} fsm_multicycle_e;
```

**Total: 25 estados** (pode ser otimizado combinando ABS/ADD/SAT em menos ciclos)

### 3.2 Otimização de Estados

Como muitos coeficientes Sobel são **zero**, podemos pular ciclos MAC desnecessários:

| Kernel | Valores não-zero | Índices |
|--------|------------------|---------|
| **Gx** | -1, -2, +2, +1   | 0, 3, 5, 6, 8 (5 MACs úteis) |
| **Gy** | -1, -2, +2, +1   | 0, 1, 2, 6, 7, 8 (6 MACs úteis) |

**Otimização:** FSM com **11 ciclos úteis** + 4 ciclos overhead = **~15 ciclos totais**

### 3.3 Transições de Estado

```
S_IDLE 
    │ (valid_in)
    ▼
S_LOAD_WIN ──▶ S_MAC_GX_0 ──▶ S_MAC_GX_1 ──▶ ... ──▶ S_MAC_GX_8
                                                              │
                                                              ▼
S_OUTPUT ◀── S_SATURATE ◀── S_ADD_MAG ◀── S_ABS_GY ◀── S_ABS_GX ◀── S_MAC_GY_8 ◀── ... ◀── S_MAC_GY_0
    │
    │ (próximo valid_in)
    ▼
S_LOAD_WIN (novo pixel) OU S_IDLE (se !valid_in)
```

---

## 4. Módulos Específicos

### 4.1 `mac_control_fsm.sv`

**Interface:**
```systemverilog
module mac_control_fsm #(
    parameter int KERNEL_DEPTH = 9
)(
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    valid_in,       // Nova janela disponível
    input  logic                    last_pixel,     // Último pixel da linha
    input  logic                    last_line,      // Última linha do frame
    output logic                    mac_enable,     // Enable para MAC unit
    output logic [$clog2(KERNEL_DEPTH):0] kernel_addr, // Endereço kernel ROM
    output logic                    select_gy,      // 0=Gx, 1=Gy
    output logic                    acc_clear,      // Limpa acumulador
    output logic                    acc_store_gx,   // Armazena resultado Gx
    output logic                    acc_store_gy,   // Armazena resultado Gy
    output logic                    output_valid,   // Pixel de saída válido
    output logic                    busy            // Core ocupado
);
```

**Funcionamento:**
- Gera endereços sequenciais para kernel ROM (0 a 8)
- Alterna `select_gy` após 9 ciclos (Gx → Gy)
- Controla `acc_clear` no início de cada convolução
- Pulsa `acc_store_gx`/`acc_store_gy` no final de cada convolução
- Asserta `output_valid` por 1 ciclo no estado S_OUTPUT

### 4.2 `kernel_rom.sv` (já existe em common/)

Já implementado - suporta leitura síncrona de ambos kernels Gx/Gy simultaneamente.

### 4.3 `sobel_multicycle.sv` (Top-level da arquitetura)

**Interface:**
```systemverilog
module sobel_multicycle #(
    parameter int IMG_WIDTH  = 640,
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
    output logic                    busy,
    output logic                    frame_done
);
```

**Conexões internas:**
1. `line_buffer_2line` → `window_3x3` → janela 3×3
2. `mac_control_fsm` → controla `mac_unit` + `kernel_rom`
3. Acumuladores Gx/Gy registrados
4. `magnitude_l1` → `abs_saturate` → saída

---

## 5. Timing e Latência

### 5.1 Pipeline de Entrada (Line Buffer + Window)

| Estágio | Ciclos | Descrição |
|---------|--------|-----------|
| Line Buffer | 2 linhas × IMG_WIDTH | Preenchimento inicial |
| Window 3×3 | 3 ciclos | Shift registers para formar janela |
| **Total entrada** | **~2×IMG_WIDTH + 3** | Apenas no primeiro frame |

### 5.2 Processamento por Pixel (Estado Estacionário)

| Fase | Ciclos | Descrição |
|------|--------|-----------|
| Load Window | 1 | Window_3x3 valid_out |
| MAC Gx | 9 | 9 coeficientes (5 úteis + 4 zeros) |
| MAC Gy | 9 | 9 coeficientes (6 úteis + 3 zeros) |
| |Gx| (ABS) | 1 | Combinacional + reg |
| |Gy| (ABS) | 1 | Combinacional + reg |
| |Gx|+|Gy| | 1 | Soma + reg |
| Saturação | 1 | Combinacional + reg |
| Output | 1 | Registra saída + valid_out |
| **Total/pixel** | **~24** | **Otimizável para ~15** |

### 5.3 Otimização: Pular Coeficientes Zero

Como Gx tem zeros nas posições [1, 4, 7] e Gy nas posições [3, 4, 5]:

```
Ciclo:  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14
Gx:    -1  0 -2  0 +2  0 -1  0 +1  -  -  -  -  -  -
Gy:    -1 -2 -1  0  0  0 +1 +2 +1  -  -  -  -  -  -
ABS:                        |Gx| |Gy| ADD SAT OUT
```

**Total otimizado: ~15 ciclos/pixel**

---

## 6. Gerenciamento de Borda (Edge Handling)

### 6.1 Estratégia: Replicação de Borda

Para pixels nas bordas da imagem, replicamos o pixel mais próximo:

```systemverilog
// No line_buffer_2line e window_3x3
// Primeira linha: line0 = line1 = primeira linha
// Primeira coluna: window[:,0] = window[:,1]
// Última coluna: window[:,2] = window[:,1]
```

### 6.2 Sinais de Controle de Borda

O `line_buffer_2line` deve fornecer:
- `first_pixel` - primeira coluna
- `last_pixel` - última coluna  
- `first_line` - primeira linha
- `last_line` - última linha

O `window_3x3` replica automaticamente via shift register behavior.

---

## 7. Verificação (Testbench cocotb)

### 7.1 Testes Obrigatórios

| Teste | Descrição |
|-------|-----------|
| `test_reset` | Reset assíncrono, estado IDLE |
| `test_single_pixel` | 1 pixel, verifica latência |
| `test_3x3_image` | Imagem 3×3, todos os 9 pixels de saída |
| `test_640x480` | Frame completo, comparação golden |
| `test_edge_cases` | Imagens 1×1, 2×2, linha única, coluna única |
| `test_fsm_states` | Cobertura 100% dos estados FSM |
| `test_backpressure` | valid_in intermitente |

### 7.2 Modelo de Referência (Python)

```python
# models/sobel_reference.py
import cv2
import numpy as np

def sobel_l1_reference(img):
    """Referência OpenCV + magnitude L1"""
    gx = cv2.Sobel(img, cv2.CV_16S, 1, 0, ksize=3)
    gy = cv2.Sobel(img, cv2.CV_16S, 0, 1, ksize=3)
    mag = np.abs(gx) + np.abs(gy)
    return np.clip(mag, 0, 255).astype(np.uint8)
```

### 7.3 Métricas de Cobertura

- **Code coverage:** Line ≥ 95%, Toggle ≥ 90%
- **FSM coverage:** 100% states, 100% transitions
- **Functional:** Bordas, cantos, valores 0/255, transições linha/frame

---

## 8. Síntese e Constraints

### 8.1 XDC (Xilinx Artix-7)

```tcl
# Clock 100 MHz
create_clock -period 10.00 -name clk [get_ports clk]

# Input delays (2ns)
set_input_delay -clock clk -max 2.0 [get_ports pixel_in]
set_input_delay -clock clk -max 2.0 [get_ports valid_in]
set_input_delay -clock clk -max 2.0 [get_ports last_pixel_in]
set_input_delay -clock clk -max 2.0 [get_ports last_line_in]

# Output delays (2ns)
set_output_delay -clock clk -max 2.0 [get_ports pixel_out]
set_output_delay -clock clk -max 2.0 [get_ports valid_out]
set_output_delay -clock clk -max 2.0 [get_ports last_pixel_out]
set_output_delay -clock clk -max 2.0 [get_ports last_line_out]

# Reset async
set_false_path -from [get_ports rst_n]

# Multicycle paths para MAC (se necessário)
set_multicycle_path 2 -from [get_pins mac_control_fsm/*] -to [get_pins mac_unit/*]
```

### 8.2 SDC (Intel Quartus)

```tcl
create_clock -name clk -period 10.00 [get_ports clk]
set_input_delay -clock clk -max 2.0 [get_ports {pixel_in valid_in last_pixel_in last_line_in}]
set_output_delay -clock clk -max 2.0 [get_ports {pixel_out valid_out last_pixel_out last_line_out}]
set_false_path -from [get_ports rst_n]
```

---

## 9. Checklist de Implementação

### 9.1 RTL
- [ ] `mac_control_fsm.sv` - FSM completa com otimização zeros
- [ ] `sobel_multicycle.sv` - Integração top-level
- [ ] Verible lint **ZERO warnings**
- [ ] Verilator `--lint-only -Wall` **ZERO warnings**

### 9.2 Verificação
- [ ] `test_sobel_multicycle.py` - Todos os testes passando
- [ ] Cobertura código ≥ 95%
- [ ] Cobertura FSM 100%
- [ ] Comparação golden (erro = 0) para L1

### 9.3 Síntese
- [ ] Vivado síntese sem warnings (latches, timing)
- [ ] Quartus síntese sem warnings
- [ ] Timing met @ 100 MHz (Artix-7)
- [ ] Relatório recursos preenchido

---

## 10. Próximos Passos Imediatos

1. **Criar `mac_control_fsm.sv`** - FSM otimizada pulando zeros
2. **Criar `sobel_multicycle.sv`** - Integração dos módulos
3. **Criar `tb_python/test_sobel_multicycle.py`** - Testes cocotb
4. **Executar `make lint`** - Verificar lint
5. **Executar `make cocotb TEST=test_sobel_multicycle`** - Rodar testes
5. **Gerar relatório de cobertura** - Verificar métricas

---

## 11. Referências

- ESPECIFICACAO_SOBEL.md (Seção 3.3.1)
- Gonzalez & Woods - Digital Image Processing (Sobel operator)
- Xilinx UG901 - Vivado Synthesis Guide
- IEEE 1800-2017 - SystemVerilog LRM