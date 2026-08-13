# Arquitetura Multiciclo - Filtro Sobel

**Versão:** 1.0  
**Data:** 2025  
**Status:** Planejamento / Em desenvolvimento

---

## 1. Visão Geral

A arquitetura **multiciclo** reutiliza uma única unidade MAC (Multiply-Accumulate) para processar os 9 coeficientes do kernel Sobel sequencialmente, alternando entre Gx e Gy. É a arquitetura de **menor área**, ideal para FPGAs pequenas ou quando o throughput de 1 pixel a cada ~15 ciclos é aceitável.

### 1.1 Características Principais

| Métrica | Valor |
|---------|-------|
| **Latência** | 15 ciclos/pixel (após pipeline de line buffer + window) — valor validado por teste real, ver §5.2 e `test_mac_control_fsm.py::test_cycle_timing` |
| **Throughput** | 1 pixel / 15 ciclos |
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

## 4. Módulos Comuns (compartilhados pelas 3 arquiteturas)

> **Nota metodológica** (vale para todo o projeto, não só estes 2 módulos):
> durante a verificação destes módulos, encontramos uma pegadinha real de
> timing na combinação Icarus+cocotb 2.0.1 deste ambiente: ler um sinal do
> DUT *imediatamente* após `await RisingEdge(dut.clk)` pode retornar o
> valor de **antes** do assentamento completo daquele ciclo (confirmado
> comparando com dump de VCD, gerado pelo próprio simulador — a fonte de
> verdade). Isso não é bug do RTL; é uma característica da ferramenta.
> Correção: usar sempre `await RisingEdge(...)` → `await ReadOnly()` →
> (capturar valores) → `await NextTimeStep()` antes de escrever novos
> estímulos. Todos os testbenches cocotb deste projeto devem seguir esse
> padrão (já aplicado em `tb_python/test_line_buffer_2line.py` e
> `tb_python/test_window_3x3.py`) — sem ele, é fácil "corrigir" um bug de
> RTL que na verdade é um artefato de leitura do teste (isso literalmente
> aconteceu durante o desenvolvimento destes 2 módulos, documentado nas
> subseções abaixo).
>
> **Segunda pegadinha, relacionada** (relevante sempre que um teste
> precisar verificar se um `$error`/`$warning`/`$fatal` do RTL disparou
> de verdade — não só "existe no código", mas realmente aconteceu):
>
> Quando você chama `run(...)`, dois **processos** do sistema operacional
> entram em cena — dois programas rodando separadamente, cada um com sua
> própria memória, sem enxergar o que está dentro do outro:
>
> ```
> ┌────────────────────────────────────────────┐
> │ Processo Python (pytest)                    │
> │ onde voce digitou "python3 -m pytest"        │
> │                                              │
> │   run(...)              logger "cocotb"      │
> │   chama e aguarda   ┌──▶ (Handler de         │
> │        │            │    captura vai aqui)   │
> └────────┼────────────┼───────────────────────┘
>          │ inicia     │ stdout
>          │ processo   │ (pipe de
>          │ novo       │  texto)
>          ▼            │
> ┌────────────────────────────────────────────┐
> │ Processo do simulador (vvp)                  │
> │ criado pelo run(), roda o circuito            │
> │                                              │
> │   RTL + corrotina         $error              │
> │   (test_contract_...)  →  sai puro pelo stdout│
> └────────────────────────────────────────────┘
> ```
>
> 1. `run(...)` **cria um processo novo** (seta descendo) — é aqui que o
>    simulador (`vvp`) nasce, com um interpretador Python embutido via
>    VPI só pra rodar as corrotinas `@cocotb.test()`. A partir desse
>    ponto, `test_contract_violation_detected` roda **dentro** desse
>    processo novo, não no processo original.
> 2. Quando o `$error` do SystemVerilog dispara, ele **não** passa pelo
>    sistema de log do Python (o mesmo que `dut._log` usa) — ele
>    simplesmente imprime texto puro na saída padrão (stdout) do
>    processo do simulador, do mesmo jeito que um `print()` cru.
> 3. Como o processo do simulador foi criado *pelo* processo do pytest,
>    existe uma conexão automática entre os dois (um *pipe*) que carrega
>    esse texto de volta (seta subindo). É a biblioteca `cocotb-test`
>    quem lê esse pipe e grava o texto recebido num `logging.Logger`
>    chamado `"cocotb"` — só que esse logger existe **no processo do
>    pytest**, não dentro da simulação, mesmo tendo nome parecido com o
>    logger interno (`cocotb.<toplevel>`, usado por `dut._log`).
>
> **Consequência prática:** um `logging.Handler` para capturar e checar
> automaticamente se um `$error` disparou precisa ser registrado **em
> volta da chamada de `run(...)`**, num teste pytest comum (função sem
> `@cocotb.test()`) — nunca dentro de uma corrotina, porque o texto do
> `$error` nunca "visita" o processo onde a corrotina roda. Esse padrão
> está centralizado em `tb_python/_cocotb_helpers.py`
> (`ErrorLogCapture`/`capture_errors()`) — não reimplemente isso em cada
> arquivo de teste nem monte o `try`/`finally` na mão; use
> `with capture_errors() as capture: ...` (ver
> `test_window_3x3_contract_violation_runner` em
> `tb_python/test_window_3x3.py` para um exemplo de uso).
>
> **Terceira pegadinha** (relevante a partir de `mac_unit.sv`, seção
> 5.1 — primeiro módulo com portas `signed`): `int(dut.sinal.value)`
> devolve a interpretação **sem sinal** do valor, mesmo que a porta
> Verilog seja `signed` — para uma porta de 11 bits, `-5` apareceria
> como `2043`. A leitura correta de um valor com sinal é
> `dut.sinal.value.signed_integer`. Confirmado por teste dedicado antes
> de escrever `tb_python/test_mac_unit.py` (ver seção 5.1).
>
> **Quarta pegadinha, importante** (afeta qualquer teste que precise
> rodar só ALGUMAS corrotinas `@cocotb.test()` de um arquivo, não
> todas): o parâmetro `testcase=` de `cocotb_test.simulator.run()` **não
> funciona** com cocotb 2.0.1 — ele define a variável de ambiente antiga
> `TESTCASE`, mas o cocotb 2.0 passou a esperar `COCOTB_TESTCASE` (com
> prefixo) e ignora silenciosamente a variável antiga, rodando **todas**
> as corrotinas do módulo mesmo com `testcase=` definido. Confirmado com
> um teste mínimo isolado (3 corrotinas triviais, pedindo só 1 - as 3
> rodaram). A correção está centralizada em `tb_python/_cocotb_helpers.py`
> (`run_isolated(testcase, **kwargs)`) — use essa função em vez de
> `cocotb_test.simulator.run()` diretamente sempre que precisar isolar
> corrotinas específicas; ela já define `COCOTB_TESTCASE` corretamente
> por dentro, então o bug não pode voltar a acontecer por esquecimento
> em um teste futuro. (Existe também `COCOTB_TEST_FILTER`, baseado em
> regex e não depreciado, mas `COCOTB_TESTCASE` já resolve.)
>
> **Nota sobre `tb_python/_cocotb_helpers.py`:** este arquivo concentra
> as correções das pegadinhas 2 e 4 acima (`run_isolated`,
> `ErrorLogCapture`, `capture_errors`) — qualquer teste futuro que
> precise de qualquer uma delas deve importar daqui, não reimplementar.
> O nome começa com `_` de propósito: pytest só coleta arquivos
> `test_*.py`/`*_test.py` por padrão, então este módulo nunca é
> confundido com um testbench em si.
>
> **Quinta pegadinha / princípio geral** (surgiu ao investigar arquivos
> recuperados após perda parcial do repositório, sessão de
> `kernel_rom.sv`/`mac_control_fsm.sv`): existe uma diferença importante
> entre um **alarme passivo** (`$error`, só existe em simulação, só
> *avisa* que algo errado aconteceu, depois do fato) e uma **trava
> ativa** (garante, estruturalmente, que a saída de um módulo nunca
> pode causar dano em quem a consome, mesmo que o consumidor não
> verifique nada — sobrevive em hardware sintetizado, não só em
> simulação). Os dois são complementares, não substitutos um do outro:
> a trava ativa evita o problema; o alarme torna o problema visível
> rapidamente, sem depender de alguém lembrar de checar um sinal
> específico.
>
> O caso concreto que gerou este princípio: `kernel_rom.sv` recebe
> `i_tap_idx` (3 bits, valores 0..7) mas só 6 desses valores (0..5) têm
> significado real. A primeira versão da proteção só tinha o alarme
> (`$error` + saída sentinela fora do intervalo válido, `4'hF`) — o que
> já evita propagação de `X`, mas ainda deixava um valor "estranho"
> vazar pra fora do módulo, que um consumidor futuro descuidado
> poderia usar pra indexar um array sem checar limites. A trava ativa
> final usa 2 partes: (1) a saída "de dado" (`o_win_pos`) sempre fica
> dentro do intervalo seguro (0..8), então **nenhum uso possível dela
> pode causar um acesso fora dos limites de um array**, mesmo por um
> consumidor que não verifica nada; (2) uma saída nova e dedicada,
> **sintetizável** (`o_addr_valid`), separa "o dado é seguro de usar"
> de "o dado é *correto*" — sem essa segunda saída, voltar ao valor
> seguro (`0`) sozinho reintroduziria a ambiguidade original (`0` é
> tanto o valor de fallback quanto a posição real do tap 0 legítimo).
>
> **Princípio geral, pra reaplicar em módulos futuros deste projeto**
> (pipeline, paralela, MMIO): sempre que uma porta tiver mais
> combinações de bits do que valores com significado real (o mesmo
> "critério (a)" da seção 15.4 do `CLAUDE.md` — gap entre o que o sinal
> *consegue* representar e o que *deveria* representar), pergunte não
> só "isso precisa de um alarme de simulação?" mas também "a saída
> correspondente, sozinha, já é impossível de usar de forma perigosa,
> mesmo sem o alarme?". Nem todo contrato violável precisa das 2
> camadas (o custo de implementar as 2 só compensa quando o dano
> potencial do outro lado é real — ex: indexação de array, não um
> resultado aritmético que só fica "meio errado"), mas vale a pergunta
> explícita a cada novo módulo, não só confiar que ninguém vai violar o
> contrato.
>
> **Caso irmão, mesma sessão** (ilustra por que "ninguém espera que o
> contrato seja violado hoje, mas o alarme existe pra pegar quando
> alguém violar no futuro" não é só retórica): a Investigação 1 desta
> sessão provou, por construção, que `mac_control_fsm.sv` (único
> consumidor de `kernel_rom` hoje) nunca manda `i_tap_idx>5` — ou seja,
> o alarme de `kernel_rom` não está pegando nenhum bug que existe hoje.
> Mas essa prova depende inteiramente da faixa de estados usada em
> `is_gx_mac`/`is_gy_mac` continuar correta — um refactor futuro nos
> estados da FSM (ex: inserir um estado novo sem atualizar essa faixa)
> quebraria essa garantia silenciosamente, sem tocar em `kernel_rom.sv`
> nenhuma vez. A proteção não foi feita pro bug de hoje; foi feita pro
> bug que um refactor descuidado pode introduzir amanhã.

### 4.1 `line_buffer_2line.sv` (comum às 3 arquiteturas)

**Interface:**
```systemverilog
module line_buffer_2line #(
    parameter int DATA_WIDTH = 8,
    parameter int IMG_WIDTH  = 8
)(
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic                  i_valid,
    input  logic [DATA_WIDTH-1:0] i_pixel,
    output logic                  o_valid,
    output logic [DATA_WIDTH-1:0] o_curr,
    output logic [DATA_WIDTH-1:0] o_line1,
    output logic [DATA_WIDTH-1:0] o_line2
);
```

**O que faz:** a partir de um stream 1D de pixels (1 por ciclo, quando
`i_valid=1`), produz no mesmo ciclo 3 amostras alinhadas na mesma coluna
mas vindas de 3 linhas diferentes da imagem: a linha que está chegando
agora (`o_curr`), 1 linha atrás (`o_line1`) e 2 linhas atrás
(`o_line2`). Não tem noção de "fim de linha" ou "fim de frame" — apenas
atrasa o stream em `IMG_WIDTH` e `2×IMG_WIDTH` pulsos de `i_valid`,
respectivamente. Quem interpreta a geometria da imagem é o
`window_3x3` (seção 4.2) e, futuramente, um controlador de frame.

**Por que é implementado como FIFO circular (memória + ponteiro), e não
como shift-register puro de `IMG_WIDTH` flip-flops:** um shift-register
de profundidade `IMG_WIDTH` custa O(IMG_WIDTH) flip-flops. Para imagens
reais (`IMG_WIDTH` na casa de centenas/milhares), isso é caro e não é
como ferramentas de síntese inferem memória de fato — o padrão
"endereço + array indexado" (memória + ponteiro que dá a volta) é o que
sintetizadores reconhecem e mapeiam para BRAM, custando 1 bloco de
memória + poucos bits de ponteiro (`$clog2(IMG_WIDTH)`), independente de
`IMG_WIDTH` ser 8 ou 8192. Um shift-register só valeria a pena para
`IMG_WIDTH` muito pequeno, onde o overhead do ponteiro não compensa —
não é o caso de uso alvo aqui.

**Por que o zero-padding do topo da imagem NÃO depende de resetar a
memória:** a primeira versão do raciocínio (na conversa que gerou este
módulo) assumia que a memória "vem zerada" após reset — o que é verdade
em simulação de um shift-register de flip-flops, mas **falso para uma
BRAM real** (memórias de bloco em FPGA não têm reset instantâneo de
todo o conteúdo; ou não resetam, ou resetar custa 1 ciclo por posição).
Por isso, este módulo usa um **contador de aquecimento**
(`warmup1_cnt_r`/`warmup2_cnt_r`) independente do conteúdo da memória: a
saída só é considerada "dado real" depois que o contador confirma que
aquela posição já foi escrita pelo menos uma vez. Antes disso, a saída
é forçada a 0 (zero-padding), não importa o que esteja fisicamente
armazenado (mesmo que seja `X` em simulação ou lixo de power-up em
hardware real).

**O bug real que apareceu ao testar — leitura registrada vs.
combinacional, e por que os 2 estágios são assimétricos:**

O primeiro RTL escrito usava leitura **combinacional** de `mem1` (mesmo
endereço do próximo write, sem registrar o resultado), pensando em dar
exatamente `IMG_WIDTH` ciclos de atraso sem nenhuma latência extra.
Rodando o testbench corretamente (após corrigir a pegadinha de timing
do cocotb descrita na nota acima), ficou claro que essa versão dava
**`IMG_WIDTH − 1`** ciclos de atraso, não `IMG_WIDTH` — o dado real
"vazava" 1 ciclo cedo demais. Causa: no exato ciclo em que o ponteiro
dá a volta, a leitura combinacional usa o ponteiro **já atualizado**
(pós-write deste mesmo ciclo), efetivamente olhando para a posição que
será sobrescrita no **próximo** ciclo, não naquele.

A correção: usar leitura **registrada**, no padrão clássico
"lê-antes-de-escrever no mesmo endereço" (`rd_data1_r <= mem1[wr_ptr1_r]`
antes de `mem1[wr_ptr1_r] <= i_pixel`, mesmo `wr_ptr1_r`). Isso dá
exatamente `IMG_WIDTH` ciclos de atraso de **armazenamento** — mas o
resultado só fica visível 1 ciclo depois (o registro de leitura), então
o atraso *observável* é `IMG_WIDTH + 1`. Por isso o limiar de
"aquecido" é `IMG_WIDTH + 1` (não `IMG_WIDTH`) no estágio 1 — usar o
limiar sem o `+1` deixa a saída "confiar" na memória 1 ciclo antes dela
realmente conter dado válido, vazando `X` (posição nunca escrita) para
fora bem na transição.

Só que aplicar a MESMA correção (leitura registrada + limiar `+1`) nos
**dois** estágios em cascata acumula os 2 ciclos de latência de leitura,
dando `2×IMG_WIDTH + 1` ciclos totais em vez de `2×IMG_WIDTH` — também
confirmado testando (`o_line2` chegava consistentemente 1 ciclo
atrasado). A causa é sutil: o dado que o estágio 2 escreve
(`line1_val`) já é ele mesmo derivado de um registro do estágio 1;
registrar a leitura do estágio 2 empilha um segundo ciclo de latência
sobre um sinal que já "pagou" essa latência uma vez. A solução final,
validada pelos testes: **estágio 1 usa leitura registrada (limiar
`IMG_WIDTH+1`)**, **estágio 2 usa leitura combinacional (limiar
simples, `IMG_WIDTH`)** — essa assimetria não é inconsistência, é a
compensação exata do ciclo extra introduzido pelo encadeamento.

| Alternativa considerada | Por que foi descartada |
|---|---|
| Shift-register de `IMG_WIDTH` flip-flops | O(IMG_WIDTH) FFs; não escala para imagens reais; só compensa para `IMG_WIDTH` muito pequeno |
| Leitura combinacional nos 2 estágios | Dá `2×IMG_WIDTH − 2` ciclos de atraso total (cada estágio "adianta" 1 ciclo) — testado e rejeitado |
| Leitura registrada nos 2 estágios | Dá `2×IMG_WIDTH + 1` ciclos (cada estágio "atrasa" 1 ciclo extra) — testado e rejeitado |
| Resetar a memória inteira no reset (`mem <= '{default:0}`) | Simula bem, mas não é como BRAM real se comporta; teria que ser descartado ao mudar de FF-array para BRAM inferida |
| **Estágio 1 registrado + estágio 2 combinacional (escolhida)** | Único arranjo que fecha em exatamente `2×IMG_WIDTH` ciclos, validado por teste |

### 4.2 `window_3x3.sv` (comum às 3 arquiteturas)

**Interface:**
```systemverilog
module window_3x3 #(
    parameter int DATA_WIDTH = 8,
    parameter int IMG_WIDTH  = 8
)(
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    i_valid,
    input  logic [DATA_WIDTH-1:0]   i_curr,
    input  logic [DATA_WIDTH-1:0]   i_line1,
    input  logic [DATA_WIDTH-1:0]   i_line2,
    output logic                    o_valid,
    output logic [9*DATA_WIDTH-1:0] o_window  // vetor achatado, ver abaixo
);
```

**O que faz:** recebe, a cada ciclo válido, as 3 amostras alinhadas em
coluna que o `line_buffer_2line` fornece (`i_curr`, `i_line1`,
`i_line2`) e monta a janela deslizante 3×3 completa, com zero-padding
nas bordas esquerda/direita de cada linha. A janela emitida está
**centrada na linha de `i_line1`**, não na de `i_curr` — `i_curr`
funciona como o "olhar 1 linha à frente" necessário para completar a
vizinhança abaixo do centro (é o motivo do `line_buffer_2line` bufferizar
"2 linhas atrás" em vez de "1 linha pra cada lado").

**Por que `o_window` é um vetor packed achatado, e não um array 2D
(`logic [DATA_WIDTH-1:0] o_window[3][3]`)**: a primeira versão usava um
array 2D de verdade na porta, que é sintaticamente válido em SystemVerilog
(IEEE1800-2017) e mais legível. Só que a combinação Icarus + cocotb 2.0.1
deste ambiente não consegue indexar portas de array 2D *unpacked* via
VPI (`NotImplementedError` ao tentar `dut.o_window[0][0].value`) — uma
limitação de ferramenta, não da linguagem. Solução robusta: achatar em
1 vetor de `9×DATA_WIDTH` bits, com layout MSB→LSB documentado no
cabeçalho do módulo (ordem linha-major, `k = 3×linha + coluna`), indexável
por fatiamento de bits em qualquer ferramenta.

**Como a borda esquerda "sai de graça" — e por que isso precisa ser
refeito a CADA linha, não só uma vez no reset:** cada uma das 3 linhas
da janela tem seu próprio shift-register horizontal de 3 posições
(`sr_row0_r`, `sr_row1_r`, `sr_row2_r`). No reset, todas as posições
começam em 0 — então a primeira coluna de uma linha naturalmente tem
"vizinho esquerdo" = 0. Só que isso só é verdade *uma vez*, no
power-up: nas linhas seguintes, se o shift-register simplesmente
continuasse deslizando normalmente, o último pixel da linha anterior
vazaria como "vizinho esquerdo" da primeira coluna da linha nova —
comportamento de wrap-around, não de zero-padding. Por isso, o módulo
detecta explicitamente `col_cnt_r == 0` (início de uma nova linha) e
**força** as 2 posições mais antigas do shift-register a 0 nesse ciclo,
em vez de deixá-las deslizar — descartando de propósito o contexto da
linha anterior.

**Como a borda direita é tratada — o "ciclo fantasma" e o contrato de
interface:** a última coluna de cada linha precisa de um "vizinho
direito" que não existe (seria a coluna `IMG_WIDTH`). Para resolver
isso sem inventar um pixel falso vindo de fora, o módulo detecta
`col_cnt_r == IMG_WIDTH-1` (última coluna real) e, **no ciclo seguinte**,
desliza um zero para dentro dos 3 shift-registers — mesmo sem receber
pixel novo nenhum (`i_valid` pode estar em 0 nesse ciclo). Isso só
funciona se o ciclo seguinte realmente estiver livre para esse
"deslizamento fantasma" — por isso este módulo define um **contrato de
interface obrigatório**: a fonte que dirige `i_valid`/`i_curr`/`i_line1`/
`i_line2` deve inserir pelo menos 1 ciclo de gap (`i_valid=0`) entre o
último pixel de uma linha e o primeiro pixel da linha seguinte
(análogo ao intervalo de *blanking* horizontal em vídeo). Sem esse gap,
o ciclo fantasma "rouba" um ciclo que deveria ser um pixel real, que
seria descartado silenciosamente — por isso o módulo inclui uma
asserção de simulação (`// synthesis translate_off/on`, fora do RTL
sintetizável) que dispara `$error` se essa violação acontecer.
Confirmado por teste dedicado (`test_contract_violation_detected` /
`test_window_3x3_contract_violation_runner`, seção 8.1) que esse alarme
realmente dispara quando o contrato é violado de propósito — ver nota
metodológica no início desta seção 4 para o porquê de precisar de um
executor separado para checar isso automaticamente. Um segundo teste
(`test_sustained_contract_violation_detected`) confirma que o alarme
dispara repetidamente numa violação sustentada (não só na primeira
vez), com contagem exata previsível — o módulo perde 1 pixel a cada
fronteira de linha violada e se re-sincroniza sozinho, em vez de ficar
permanentemente desalinhado.

**O que este módulo explicitamente NÃO faz (fora de escopo):** não
trata a borda inferior do frame (última linha da imagem). Isso
exigiria uma "linha fantasma" inteira de zeros ao final do frame,
análoga ao ciclo fantasma horizontal — mas isso requer saber a altura
da imagem (`IMG_HEIGHT`), que nenhum destes 2 módulos conhece por
projeto (mantê-los agnósticos a `IMG_HEIGHT` é o que permite reutilizá-los
sem mudança nas 3 arquiteturas, que podem ter formas bem diferentes de
orquestrar o fim de frame). Essa responsabilidade fica para um futuro
controlador de nível superior (ver seção 10).

| Alternativa considerada | Por que foi descartada |
|---|---|
| Array 2D na porta `o_window[3][3]` | Não indexável via VPI nesta combinação de ferramentas (Icarus+cocotb) |
| Resetar os shift-registers só uma vez, no power-up | Funciona só para a 1ª linha; linhas seguintes vazam o último pixel da linha anterior como vizinho esquerdo (bug encontrado por derivação manual, corrigido antes de escrever o RTL) |
| Fonte de pixels sem gap entre linhas + módulo com backpressure (`o_ready`) próprio | Resolveria o contrato de interface de forma mais robusta, mas adiciona handshake real; adiado — over-engineering para o estado atual do projeto (reavaliar se lidar com bottom-border no controlador de frame precisar disso mesmo) |
| Tratar a borda inferior do frame aqui mesmo | Exigiria conhecer `IMG_HEIGHT`, acoplando o módulo à geometria do frame — quebra a reutilização entre as 3 arquiteturas |

### 4.3 `abs_saturate.sv` (comum às 3 arquiteturas)

**Interface:**
```systemverilog
module abs_saturate #(
    parameter int IN_WIDTH  = 11,
    parameter int OUT_WIDTH = 8
)(
    input  logic signed [IN_WIDTH-1:0]  i_value,
    output logic        [OUT_WIDTH-1:0] o_value
);
```

**O que faz:** calcula `|i_value|` e satura o resultado para caber em
`OUT_WIDTH` bits sem sinal — se a magnitude passar do máximo
representável (`2^OUT_WIDTH-1`), a saída trava nesse máximo em vez de
estourar. Puramente combinacional (sem `clk`/`rst_n`) — uma função
pura, pensada para ser instanciada 2× (uma para Gx, outra para Gy).

**Aritmética saturante, rapidamente:** em vez de deixar um valor
"vazar" pra fora da faixa representável (o que daria um número
*errado* por *overflow* — ex: 260 virando 4 num campo de 8 bits), a
saída trava no teto. É assim que sensores de imagem e pipelines de
vídeo tratam estouro de brilho/contraste na prática — perder precisão
no extremo é aceitável, dar um valor absurdo não é.

**Por que a entrada é "esticada" em 1 bit antes de negar (e um bug
real que isso evitou, encontrado testando):** o valor mais negativo
representável num campo de N bits com sinal (ex: −8 em 4 bits) não tem
um positivo correspondente na *mesma* largura (o máximo positivo em 4
bits é só +7) — negar esse valor sem folga extra "dá a volta" e
continua negativo, um bug clássico de complemento de 2. A correção é
fazer a negação com 1 bit a mais de largura antes de calcular o valor
absoluto. No uso real deste projeto (saída do `mac_unit`, ±1020) esse
caso extremo nunca acontece — mas como o módulo é pensado para reuso
genérico, ele trata o caso certo mesmo assim, e isso é testado
explicitamente (`test_two_complement_extreme_edge_case`, com
`IN_WIDTH=4` para realmente alcançar o valor extremo).

**Um segundo bug real, esse sim pego durante os testes:** os sinais
internos (`abs_val`, o limite de saturação) foram inicialmente
dimensionados só com `IN_WIDTH+1` bits — o suficiente para o primeiro
teste (`IN_WIDTH=11, OUT_WIDTH=8`, onde `IN_WIDTH+1=12 > OUT_WIDTH=8`),
mas **não genericamente correto**: com `IN_WIDTH=4, OUT_WIDTH=8`
(exatamente o teste do caso extremo acima), `IN_WIDTH+1=5 < OUT_WIDTH=8`,
e o valor 255 (que precisa de 8 bits) ficava truncado ao ser guardado
num sinal de só 5 bits — gerando bits `X` (indefinido) na saída. A
correção: dimensionar os sinais internos pelo **maior** entre
`IN_WIDTH+1` e `OUT_WIDTH`, não só `IN_WIDTH+1`. Vale a lição geral:
parâmetros que "funcionam" para uma combinação específica não provam
que a lógica está genericamente correta — só testar com combinações
diferentes revela isso (mesma lição da investigação de bugs da seção
sobre `line_buffer_2line`/`window_3x3`).

| Alternativa considerada | Por que foi descartada |
|---|---|
| Não tratar o caso extremo de complemento de 2 (assumir que nunca acontece) | Funcionaria para o uso atual (±1020), mas quebraria silenciosamente se o módulo for reaproveitado com uma faixa de entrada diferente — módulo comum deveria ser genericamente correto |
| Saturar `|Gx|`+`|Gy|` só no final (não em cada um separadamente) | Matematicamente equivalente para esta soma de 2 valores não-negativos (ver seção 4.4), mas exigiria carregar a largura completa (11 bits) até o somador final, em vez de 8 bits |

### 4.4 `magnitude_l1.sv` (comum às 3 arquiteturas)

**Interface:**
```systemverilog
module magnitude_l1 #(
    parameter int DATA_WIDTH = 8
)(
    input  logic [DATA_WIDTH-1:0] i_abs_gx,
    input  logic [DATA_WIDTH-1:0] i_abs_gy,
    output logic [DATA_WIDTH-1:0] o_magnitude
);
```

**O que faz:** soma `|Gx|` e `|Gy|` (já calculados e saturados por 2
instâncias de `abs_saturate`) e satura o resultado da soma para
`DATA_WIDTH` bits de novo — a soma de dois valores de 8 bits pode
chegar a 510, que não cabe em 8 bits. Puramente combinacional.

**Por que saturar 2 vezes (uma vez em cada `abs_saturate`, outra aqui)
não é redundante nem gera erro:** poderia parecer estranho saturar
duas vezes — mas para uma soma de valores **não-negativos**, saturar
cedo (em cada parcela) e saturar tarde (na soma) dão exatamente o
mesmo resultado final. Intuição: se `|Gx|` sozinho já passa de 255, a
soma final vai saturar de qualquer jeito, não importa o valor de
`|Gy|` — então saturar `|Gx|` antes de somar não muda a resposta,
só evita carregar bits desnecessários adiante. Essa é a mesma
aritmética saturante da seção 4.3, aplicada em cascata.

| Alternativa considerada | Por que foi descartada |
|---|---|
| Somar `Gx`/`Gy` com sinal (11 bits cada) e só então tirar valor absoluto + saturar | Funcionaria, mas exigiria carregar 11 bits até o somador final em vez de 8 — mais fiação sem ganho de precisão (ver prova de equivalência acima) |

---

## 5. Módulos Específicos da Arquitetura Multiciclo

### 5.1 `mac_unit.sv`

**Interface:**
```systemverilog
module mac_unit #(
    parameter int DATA_WIDTH  = 8,
    parameter int COEFF_WIDTH = 3,
    parameter int ACC_WIDTH   = 11
)(
    input  logic                          clk,
    input  logic                          rst_n,
    input  logic                          i_clear,
    input  logic                          i_mac_en,
    input  logic [DATA_WIDTH-1:0]         i_pixel,
    input  logic signed [COEFF_WIDTH-1:0] i_coeff,
    output logic signed [ACC_WIDTH-1:0]   o_acc
);
```

**O que faz:** unidade de multiplicação-acumulação (`acc ← acc +
pixel×coeficiente`), pensada para ser instanciada **uma única vez** e
reaproveitada pela `mac_control_fsm` ao longo dos 12 ciclos úteis de
MAC por pixel (6 para Gx, 6 para Gy — ver seção 6.2). `i_clear` zera o
acumulador (usado no estado `S_LOAD_WIN`, antes de começar os passos de
MAC); `i_mac_en` realiza 1 passo de acumulação naquele ciclo.

**Por que não existe multiplicador de hardware:** como os coeficientes
do Sobel, depois de pular os zeros (seção 6.2), só valem
`{+1,-1,+2,-2}`, a multiplicação vira deslocamento + negação — sem
custar nenhum multiplicador/DSP:

| Coeficiente | Operação | Custo em hardware |
|---|---|---|
| +1 | `produto = pixel` | fio direto |
| −1 | `produto = −pixel` | inversor + somador (complemento de 2) |
| +2 | `produto = pixel <<< 1` | fio deslocado (sem custo de portas) |
| −2 | `produto = −(pixel <<< 1)` | fio deslocado + inversor + somador |

Essa tabela é implementada com um `case` explícito no RTL, não com o
operador `*` — a diferença importa porque `i_coeff` é uma **entrada de
runtime** (muda a cada ciclo, vindo da FSM), não uma constante fixa em
tempo de compilação. Ferramentas de síntese normalmente só conseguem
simplificar `pixel * coeficiente` para deslocamento quando o
coeficiente é uma constante conhecida em tempo de compilação — com um
coeficiente variável, `pixel * i_coeff` provavelmente instancia um
multiplicador de verdade (1 DSP), mesmo que só 4 valores sejam
possíveis. O `case` manual garante 0 DSPs por construção, não por
otimização "torcida" da ferramenta.

**Teste de caminho errado:** o `case` tem um ramo `default` cobrindo
qualquer `i_coeff` fora de `{-2,-1,1,2}` (inclusive 0, que a FSM nunca
deveria enviar de qualquer forma — ver seção 6.2). Confirmado por
teste dedicado (`test_unexpected_coefficient_handled_safely`, seção
8.1) que esse `default` realmente produz `produto=0` sem propagar bits
`X`, em vez de só confiar no comentário do RTL.

**Largura do acumulador — 11 bits, o mínimo exato:** o pior caso (todos
os pixels de coeficiente positivo em 255, todos os de coeficiente
negativo em 0, ou vice-versa) soma `±1020` — ver seção 6.2 para a
derivação completa dos coeficientes não-nulos. `2^10 = 1024 > 1020`,
logo 11 bits (`−1024` a `1023`) já cobre o intervalo com folga mínima,
sem desperdiçar nenhum bit. Confirmado por teste dedicado
(`test_boundary_max_min`) que os valores `+1020`/`−1020` realmente
cabem sem estourar.

**Por que o acumulador mora dentro do `mac_unit`, e não na FSM:** o
nome "MAC" (*multiply-accumulate*) já implica um estado interno — é
isso que diferencia um MAC de um multiplicador simples. Mantendo o
acumulador aqui, a `mac_control_fsm` só precisa sequenciar
`i_clear`/`i_mac_en`/`i_coeff`, sem duplicar a lógica de soma. A
consequência prática (relevante para o item 5.2, ainda não
implementado): como o *mesmo* acumulador é reaproveitado tanto para Gx
quanto para Gy, o resultado de Gx precisa ser **salvo em outro
registrador** (na FSM ou no top-level) antes de dar `i_clear` e
reaproveitar o `mac_unit` para Gy — senão o valor de Gx se perde.

| Alternativa considerada | Por que foi descartada |
|---|---|
| Operador `*` genérico, confiando na síntese | Coeficiente é entrada de runtime — a maioria das ferramentas não otimiza para deslocamento nesse caso, provavelmente instancia 1 DSP real |
| Acumulador de 12 bits (margem de segurança) | Funcionaria também, mas desperdiça 1 flip-flop sem necessidade — decisão consciente de usar o mínimo exato |
| 2 instâncias de `mac_unit` (1 para Gx, 1 para Gy, em paralelo) | Melhor throughput, mas contraria o objetivo da arquitetura multiciclo (área mínima); essa ideia é, na verdade, o que a arquitetura **pipeline** faz |
| Acumulador vivendo na FSM em vez do `mac_unit` | Duplicaria a lógica de soma caso o `mac_unit` precise ser reaproveitado em outro contexto; menos coeso com o nome/propósito "MAC" |

### 5.2 `mac_control_fsm.sv`

**Status:** implementado e testado (16 estados, 15 ciclos úteis/pixel —
ver seção 3 para o diagrama de estados). Recuperado após perda parcial
do repositório e corrigido em sessão de investigação com 3 bugs reais
encontrados por execução de verdade (nenhum hipotético).

**Interface:**
```systemverilog
module mac_control_fsm #(
    parameter int DATA_WIDTH  = 8,
    parameter int COEFF_WIDTH = 3,
    parameter int ACC_WIDTH   = 11
)(
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    i_valid,
    input  logic [9*DATA_WIDTH-1:0] i_window,   // vetor achatado, layout de window_3x3
    output logic                    o_ready,    // 1 so durante S_IDLE
    output logic                    o_valid,    // 1 so durante S_OUTPUT
    output logic [DATA_WIDTH-1:0]   o_pixel
);
```

Instancia internamente `mac_unit` + `kernel_rom` + 2×`abs_saturate` +
`magnitude_l1` (não é FSM pura de propósito, ver `RESUMO_ESTADO_PROJETO.md`).

#### Bug #1 (real, encontrado ao rodar de verdade): `win_reg` capturando 1 ciclo atrasado

**Sintoma:** `magnitude` sempre saía `0`, para qualquer janela de
entrada — confirmado com `test_cycle_timing` esperando `255` e obtendo
`0`.

**Causa raiz** (confirmada por trace ciclo-a-ciclo, não só leitura de
código): `win_reg` capturava `i_window` na condição
`state_r == S_LOAD_WIN` — ou seja, **1 ciclo inteiro depois** de
`i_valid` ter sido aceito em `S_IDLE`. O contrato de interface já
documentado no cabeçalho do módulo garante `i_window` válido só
**enquanto `o_ready=1`** (durante `S_IDLE`), não no ciclo seguinte.
Como `window_3x3` não tem backpressure (continua deslizando
independente da FSM), por essa altura `i_window` já teria avançado
pra janela seguinte no uso real — no teste, já tinha sido zerado. O
acumulador do `mac_unit` sempre multiplicava por pixel=0.

**Correção:** capturar `win_reg` na própria transição de saída de
`S_IDLE` (`state_r == S_IDLE && i_valid`), não na entrada em
`S_LOAD_WIN`:
```diff
- end else if (state_r == S_LOAD_WIN) begin
+ end else if (state_r == S_IDLE && i_valid) begin
```
`S_LOAD_WIN` continua existindo como estado — passa a servir só pra
dar 1 ciclo de folga pro `i_clear` do `mac_unit` assentar antes do
primeiro MAC, não mais literalmente "o estado onde a janela é
carregada" (que passa a acontecer 1 ciclo antes).

**Alternativas descartadas** (discutidas antes de decidir):

| Alternativa | Por que foi descartada |
|---|---|
| Exigir que quem chama segure `i_window` por 2 ciclos (o atual + `S_LOAD_WIN`) | Contradiz o próprio contrato já documentado; empurraria um buffer extra pro futuro `sobel_multicycle.sv` sem necessidade |
| Eliminar `S_LOAD_WIN`, capturando direto na saída de `S_IDLE` e indo pro 1º MAC no mesmo estado | Reabriria a contagem de 16 estados/15 ciclos já fechada e testada (`test_o_ready_low_while_busy`); risco de `i_clear` e o 1º `i_mac_en` caírem no mesmo ciclo (prioridade de `clear` no `mac_unit` descartaria o 1º MAC) |

#### Bug #3 (real, exposto só depois de corrigir o Bug #1 e o `NameError` do teste): violação de contrato entre janelas consecutivas

**Sintoma:** ao corrigir `test_various_windows` pra reusar
`_feed_and_wait` num laço (ver Bug #2, seção do testbench), o `$error`
de contrato do próprio `mac_control_fsm.sv` disparava
(`i_valid ativo com o_ready=0`), e `o_valid` nunca chegava a disparar
pra 2ª janela em diante.

**Causa raiz:** `_feed_and_wait` retornava assim que detectava
`o_valid=1` — exatamente no ciclo em que `state_r == S_OUTPUT`. Mas
`state_r` só volta pra `S_IDLE` (`o_ready` só volta a `1`) na borda
**seguinte** (transição incondicional `S_OUTPUT -> S_IDLE`). Chamar
`_feed_and_wait` de novo, em sequência, ligava `i_valid=1` ainda com
`o_ready=0`.

**Correção (Opção B, escolhida por afetar a raiz do padrão em vez de
cada chamador individualmente):** `_feed_and_wait` agora espera
`o_ready` voltar a `1` antes de retornar, depois de já ter capturado
`pixel`/`cycles` (a contagem de ciclos retornada não muda — ver
`tb_python/test_mac_control_fsm.py`).

Ver também a nota metodológica da seção 4 ("Quinta pegadinha") sobre a
distinção entre alarme passivo e trava ativa, e por que a Investigação
1 (prova de que `tap_idx` gerado aqui nunca ultrapassa 5) é uma
garantia condicionada à estrutura atual dos estados, não permanente.

### 5.3 `kernel_rom.sv`

**Status:** implementado e testado. Recuperado após perda parcial do
repositório (interface real, diferente da reconstrução de uma sessão
anterior — ver histórico de decisões abaixo) e reforçado com trava
ativa nesta sessão.

**Interface (final, com a trava ativa):**
```systemverilog
module kernel_rom #(
    parameter int COEFF_WIDTH = 3
)(
    input  logic                          i_gy,         // 0=tabela de Gx, 1=tabela de Gy
    input  logic        [            2:0] i_tap_idx,    // 0..5
    output logic        [            3:0] o_win_pos,    // posicao 0..8 na janela - SEMPRE valida
    output logic signed [COEFF_WIDTH-1:0] o_coeff,
    output logic                          o_addr_valid  // 1=tap real, 0=i_tap_idx fora de 0..5
);
```

**O que faz:** lookup puramente combinacional (sem `clk`/`rst_n`) dos 6
taps não-nulos de cada kernel Sobel (Gx ou Gy, escolhido por `i_gy`),
retornando `(posição na janela 3×3, coeficiente)` de cada tap,
endereçado por `i_tap_idx` (0..5).

**Histórico da interface:** uma sessão anterior (antes da perda dos
arquivos) havia reconstruído este módulo do zero com uma interface
diferente (`i_select_gy`/`i_addr`/`o_pos`, parâmetros `ADDR_WIDTH`/
`POS_WIDTH` explícitos). Ao recuperar os arquivos reais do projeto,
ficou claro que a interface verdadeira (já integrada a
`mac_control_fsm.sv`) usa `i_gy`/`i_tap_idx`/`o_win_pos`, com larguras
fixas (não parametrizadas) — mesma convenção de literais fixos já usada
em `mac_unit.sv`. A reconstrução anterior foi descartada em favor dos
arquivos recuperados, que são consistentes entre si.

**Trava ativa (não só alarme passivo) — evolução em 2 etapas nesta sessão:**

1. **Primeira correção:** `i_tap_idx` tem 3 bits (permite 0..7), mas só
   0..5 têm significado (6 taps por kernel) — gap entre o que o sinal
   representa e o que deveria representar. Adicionado `$error` de
   simulação + `default` seguro no `case` (sem propagar `X`).
2. **Reforço (trava ativa de verdade):** o `default` inicial usava um
   sentinela fora do intervalo válido (`o_win_pos=4'hF`) — tornava o
   erro visível, mas deixava um valor perigoso vazar pra fora do
   módulo (se um consumidor futuro indexasse um array de 9 posições
   com esse valor, sem checar nada antes, estouraria os limites).
   Corrigido para: `o_win_pos` **sempre** dentro de 0..8 (nunca causa
   um acesso fora dos limites em nenhum consumidor, mesmo sem
   verificação nenhuma do lado de quem chama) + saída nova
   `o_addr_valid` (**sintetizável**, ao contrário do `$error` — separa
   "seguro de usar" de "correto", já que `o_win_pos=0` sozinho é
   ambíguo entre "endereço inválido" e "tap 0 legítimo").

```diff
  default: begin
-   o_win_pos = 4'hF;  // sentinela fora de 0..8
-   o_coeff   = '0;
+   o_win_pos    = 4'd0;  // valor seguro, sempre dentro de 0..8
+   o_coeff      = '0;
+   o_addr_valid = 1'b0;
  end
```

**Não foi necessário alterar `mac_control_fsm.sv`:** a porta nova
(`o_addr_valid`) simplesmente fica sem conexão na instanciação
existente — legal em SystemVerilog (saída não conectada não é erro de
compilação). `mac_control_fsm.sv` continua confiando na prova de que
nunca envia `i_tap_idx>5` (ver "Investigação 1" na nota metodológica da
seção 4); qualquer consumidor futuro mais cauteloso pode conectar
`o_addr_valid` sem precisar de nenhuma mudança aqui.

Ver a nota metodológica completa (5ª pegadinha) na seção 4 sobre a
distinção entre alarme passivo e trava ativa, e o princípio geral pra
reaplicar em módulos futuros.

| Alternativa considerada | Por que foi descartada |
|---|---|
| Só o `$error` (sem trava ativa) | Deixa a decisão de proteção inteiramente do lado do consumidor — contraria o objetivo de "quem instancia `kernel_rom` não precisa reimplementar essa checagem" |
| Sentinela fora de range sem `o_addr_valid` (estado da 1ª correção) | Torna o erro visível, mas não impede um consumidor descuidado de causar dano real (acesso fora dos limites de array) |
| Proteção redundante também em `mac_control_fsm.sv` (checar `kr_win_pos` antes de indexar `win_reg`) | Redundante hoje, dado que `kernel_rom` já é instanciado *dentro* de `mac_control_fsm` (qualquer simulação que exercitasse o bug já dispararia o `$error` na mesma rodada); reconsiderar só se outro consumidor futuro não reusar a mesma lógica de geração de endereço já provada segura |

---

## 6. Timing e Latência

### 6.1 Pipeline de Entrada (Line Buffer + Window)

| Estágio | Ciclos | Descrição |
|---------|--------|-----------|
| Line Buffer | 2×IMG_WIDTH + 1 | Ver seção 4.1 (atraso exato validado por teste) |
| Window 3×3 | +1 | 1 ciclo adicional até a primeira janela válida |
| **Total entrada** | **~2×IMG_WIDTH + 2** | Apenas no primeiro frame |

### 6.2 Processamento por Pixel (Estado Estacionário)

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

> **Atenção ao usar estes números:** a contagem de "coeficientes úteis"
> acima (5 para Gx) e a tabela de ciclos otimizados na seção 6.3 têm uma
> inconsistência conhecida, ainda não corrigida neste documento — Gx
> tem 6 taps não-nulos, não 5 (índices 0,2,3,5,6,8 do kernel
> `[-1,0,1;-2,0,2;-1,0,1]`, não 0,3,5,6,8). Isso foi identificado e
> corrigido durante o projeto conceitual da FSM (ainda não implementada
> em RTL) — ver seção 11 para o estado atualizado dessa discussão antes
> de implementar `mac_control_fsm.sv`.

### 6.3 Otimização: Pular Coeficientes Zero

Como Gx tem zeros nas posições [1, 4, 7] e Gy nas posições [3, 4, 5]:

```
Ciclo:  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14
Gx:    -1  0 -2  0 +2  0 -1  0 +1  -  -  -  -  -  -
Gy:    -1 -2 -1  0  0  0 +1 +2 +1  -  -  -  -  -  -
ABS:                        |Gx| |Gy| ADD SAT OUT
```

**Total otimizado: ~15 ciclos/pixel** (ver ressalva acima — este número
precisa ser recalculado quando a FSM for implementada).

---

## 7. Gerenciamento de Borda (Edge Handling)

### 7.1 Estratégia Implementada: Zero-Padding (provisório)

> Esta seção substitui a descrição anterior ("replicação de borda"),
> que refletia um plano inicial nunca chegou a ser implementado. A
> implementação real (seção 4, `line_buffer_2line` + `window_3x3`) usa
> **zero-padding**, decisão marcada como provisória — pode ser
> revisada para replicação de borda no futuro, mudança que ficaria
> isolada nesses 2 módulos comuns, sem impacto nas 3 arquiteturas.

Bordas tratadas automaticamente pelos módulos comuns, sem sinais
externos dedicados:
- **Borda superior** (primeiras 2 linhas da imagem): `line_buffer_2line`
  força saída 0 enquanto o contador de aquecimento não confirma que a
  memória correspondente já foi escrita (seção 4.1).
- **Bordas esquerda/direita** (dentro de cada linha): `window_3x3`
  força 0 na primeira coluna (reset explícito do contexto horizontal a
  cada início de linha) e usa 1 "ciclo fantasma" para a última coluna
  (seção 4.2).
- **Borda inferior** (última linha da imagem): **ainda não tratada** -
  nenhum dos 2 módulos comuns conhece `IMG_HEIGHT`; fica para um
  controlador de frame de nível superior (seção 11).

### 7.2 Contrato de Interface (substitui os sinais `first_pixel`/`last_pixel`/`first_line`/`last_line`)

A versão anterior deste documento previa que `line_buffer_2line`
forneceria sinais `first_pixel`/`last_pixel`/`first_line`/`last_line`
para o `window_3x3` "replicar automaticamente via shift register
behavior". Isso não reflete a implementação real: **nenhum desses
sinais existe** - `window_3x3` resolve bordas esquerda/direita sozinho,
usando apenas um contador de coluna interno (`col_cnt_r`, dimensionado
por `IMG_WIDTH`, parâmetro do próprio módulo). O único requisito
externo é um **contrato de timing**, não um sinal: a fonte que dirige
`window_3x3` deve inserir ≥1 ciclo de gap (`i_valid=0`) entre linhas
(ver seção 4.2 para o porquê).

---

## 8. Verificação (Testbench cocotb)

### 8.1 Testes Já Existentes

Os módulos comuns (seção 4) e o `mac_unit` (seção 5.1) já têm
testbenches cocotb autocontidos, seguindo o padrão de metodologia
descrito no início da seção 4:

| Arquivo | Testes (`@cocotb.test`) | Cobre |
|---|---|---|
| `tb_python/test_line_buffer_2line.py` | `test_reset_state`, `test_delay_and_zero_padding`, `test_ignores_invalid_cycles`, `test_midstream_reset` | Reset (inicial e no meio da operação); atraso W/2W ciclos + zero-padding com stream contínuo; imunidade a ciclos com `i_valid=0`; ausência de resíduo após reset com dado "em trânsito" |
| `tb_python/test_window_3x3.py` | `test_reset_state`, `test_geometry_with_zero_padding`, `test_multiple_gap_cycles`, `test_contract_violation_detected`, `test_sustained_contract_violation_detected` | Reset; geometria completa da janela 3×3 com zero-padding (bordas superior/esquerda/direita), comparado contra referência numpy; tolerância a mais de 1 ciclo de gap entre linhas; disparo automático do `$error` ao violar o contrato de interface de propósito (via executor dedicado, ver nota metodológica da seção 4); violação **sustentada** (5 linhas contínuas, sem gap algum) dispara exatamente `N_ROWS-1` vezes, confirmando que o alarme não "trava" após a 1ª violação e que o módulo se re-sincroniza sozinho |
| `tb_python/test_abs_saturate.py` | `test_positive_no_saturation`, `test_negative_no_saturation`, `test_positive_saturation`, `test_negative_saturation`, `test_boundary_exact_255_256`, `test_project_actual_range`, `test_two_complement_extreme_edge_case` | Cada caso de saturação/não-saturação; varredura completa do intervalo real (±1020); caso extremo de complemento de 2 (via executor dedicado com `IN_WIDTH=4`) |
| `tb_python/test_magnitude_l1.py` | `test_no_saturation`, `test_saturation`, `test_boundary_exact_255_256`, `test_exhaustive_small_range` | Soma sem/com saturação; limite exato 255/256; varredura exaustiva de 4096 combinações (gx,gy de 0 a 63) |
| `tb_python/test_mac_unit.py` | `test_reset_state`, `test_each_coefficient`, `test_accumulation_sequence`, `test_full_gx_sequence`, `test_full_gy_sequence`, `test_boundary_max_min`, `test_mac_en_gating`, `test_clear_priority_over_mac_en`, `test_unexpected_coefficient_handled_safely` | Reset; cada um dos 4 coeficientes isolado; soma correta ao longo de vários passos; sequência completa de Gx e Gy (com os coeficientes reais); valores de fronteira ±1020 cabendo em 11 bits; `i_mac_en=0` mantém o acumulador parado; prioridade de `i_clear` sobre `i_mac_en`; **caminho errado** — coeficiente fora de `{-2,-1,1,2}` não propaga `X` (confirma o `default` do `case`) |

`tb_python/_cocotb_helpers.py` **não é um arquivo de teste** (nome
começa com `_` de propósito, pytest não o coleta) — é infraestrutura
compartilhada (`run_isolated`, `ErrorLogCapture`, `capture_errors`)
usada por `test_window_3x3.py` e `test_abs_saturate.py`, centralizando
as correções das pegadinhas 2 e 4 da seção 4. Qualquer teste futuro que
precise isolar corrotinas específicas ou capturar `$error` deve
importar daqui.

Rodar com `make cocotb` (a partir da raiz do projeto).

### 8.2 Testes Obrigatórios (Arquitetura Multiciclo Completa - Pendente)

| Teste | Descrição |
|-------|-----------|
| `test_reset` | Reset assíncrono, estado IDLE |
| `test_single_pixel` | 1 pixel, verifica latência |
| `test_3x3_image` | Imagem 3×3, todos os 9 pixels de saída |
| `test_640x480` | Frame completo, comparação golden |
| `test_edge_cases` | Imagens 1×1, 2×2, linha única, coluna única |
| `test_fsm_states` | Cobertura 100% dos estados FSM |
| `test_backpressure` | valid_in intermitente |

### 8.3 Modelo de Referência (Python)

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

### 8.4 Métricas de Cobertura

- **Code coverage:** Line ≥ 95%, Toggle ≥ 90%
- **FSM coverage:** 100% states, 100% transitions
- **Functional:** Bordas, cantos, valores 0/255, transições linha/frame

---

## 9. Síntese e Constraints

### 9.1 XDC (Xilinx Artix-7)

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

### 9.2 SDC (Intel Quartus)

```tcl
create_clock -name clk -period 10.00 [get_ports clk]
set_input_delay -clock clk -max 2.0 [get_ports {pixel_in valid_in last_pixel_in last_line_in}]
set_output_delay -clock clk -max 2.0 [get_ports {pixel_out valid_out last_pixel_out last_line_out}]
set_false_path -from [get_ports rst_n]
```

---

## 10. Checklist de Implementação

### 10.1 RTL
- [x] `line_buffer_2line.sv` - módulo comum, testado
- [x] `window_3x3.sv` - módulo comum, testado
- [x] `mac_unit.sv` - testado, 0 DSPs por construção
- [x] `abs_saturate.sv` - módulo comum, testado
- [x] `magnitude_l1.sv` - módulo comum, testado
- [x] `mac_control_fsm.sv` - FSM completa, testada (16 estados, 15 ciclos úteis/pixel) - 2 bugs reais corrigidos nesta sessão (seção 5.2)
- [x] `kernel_rom.sv` - lookup combinacional com trava ativa, testado (seção 5.3)
- [ ] `sobel_multicycle.sv` - Integração top-level
- [x] Verible lint **ZERO warnings** (todos os módulos criados até agora)
- [ ] Verilator `--lint-only -Wall` **ZERO warnings**

### 10.2 Verificação
- [x] `test_line_buffer_2line.py` - Todos os testes passando
- [x] `test_window_3x3.py` - Todos os testes passando
- [x] `test_mac_unit.py` - Todos os testes passando
- [x] `test_abs_saturate.py` - Todos os testes passando
- [x] `test_magnitude_l1.py` - Todos os testes passando
- [x] `test_kernel_rom.py` - Todos os testes passando (4 corrotinas, 2 executores: normal + violação isolada)
- [x] `test_mac_control_fsm.py` - Todos os testes passando (5 corrotinas, 2 executores: normal + violação isolada)
- [ ] `test_sobel_multicycle.py` - Todos os testes passando
- [ ] Cobertura código ≥ 95%
- [ ] Cobertura FSM 100%
- [ ] Comparação golden (erro = 0) para L1

### 10.3 Síntese
- [ ] Vivado síntese sem warnings (latches, timing)
- [ ] Quartus síntese sem warnings
- [ ] Timing met @ 100 MHz (Artix-7)
- [ ] Relatório recursos preenchido

---

## 11. Próximos Passos Imediatos

1. ~~Criar `line_buffer_2line.sv` e `window_3x3.sv`~~ - **feito**, testado (seção 4)
2. ~~Criar `mac_unit.sv`~~ - **feito**, testado, 0 DSPs por construção (seção 5.1)
3. ~~Criar `abs_saturate.sv` e `magnitude_l1.sv`~~ - **feito**, testados (seções 4.3, 4.4)
4. **Confirmar decisões da FSM** antes de codar `mac_control_fsm.sv`:
   contagem correta de taps não-nulos (Gx tem 6, não 5 - ver ressalva na
   seção 6.2), largura do enum (`$clog2` do nº real de estados, não 4
   bits fixos), e se os estágios de finalização (ABS/ADD/SAT) ficam
   separados ou fundidos (afeta o total de ciclos/pixel)
5. **Criar `kernel_rom.sv`** (ou lookup combinacional) - decisão de
   design em aberto, ver seção 5.3
6. ~~Criar `mac_control_fsm.sv`~~ - **feito**, testado, 2 bugs reais corrigidos em sessão de recuperação (seção 5.2)
7. **Criar `sobel_multicycle.sv`** - Integração dos módulos, incluindo
   o handshake necessário entre o stream de entrada contínuo e a FSM
   (que leva múltiplos ciclos por janela - ver discussão sobre
   `S_LOAD_WIN`)
8. **Criar `tb_python/test_sobel_multicycle.py`** - Testes cocotb de
   integração, seguindo o mesmo padrão de metodologia da seção 4
9. **Executar `make cocotb`** e `make format` antes de considerar pronto

---

## 12. Referências

- ESPECIFICACAO_SOBEL.md (Seção 3.3.1)
- Gonzalez & Woods - Digital Image Processing (Sobel operator)
- Xilinx UG901 - Vivado Synthesis Guide
- IEEE 1800-2017 - SystemVerilog LRM