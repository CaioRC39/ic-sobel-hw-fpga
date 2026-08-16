# Auditoria Arquitetural 01 — Pré-Multiciclo

> **Relação com o restante do projeto:** este documento NÃO substitui nem duplica `CLAUDE.md` ou `RESUMO_ESTADO_PROJETO.md`. Regras permanentes, convenções e decisões arquiteturais já consolidadas continuam vivendo exclusivamente lá — aqui só entram referências a elas. Este documento registra o processo, as evidências e as conclusões *desta* auditoria específica, de forma rastreável e atualizável.
>
> **Legenda do checklist:** `[ ]` não analisado · `[x]` analisado/concluído · `[~]` parcialmente concluído · `[!]` problema identificado · `[?]` depende de informação adicional.
>
> **Nota de continuidade desta revisão (2026-08-11):** esta versão retoma o documento a partir do estado "EM ANDAMENTO" deixado na criação (2026-08-10) e o leva até uma conclusão formal (§16–17). Todo achado novo introduzido nesta revisão está identificado como tal (data e origem da evidência); nada do conteúdo original com evidência válida foi apagado — apenas complementado ou, em 1 caso (§5), corrigido com correção explícita registrada.

---

## 1. Identificação da auditoria

| Campo | Valor |
|---|---|
| Nome | Auditoria Arquitetural 01 — Pré-Multiciclo |
| Código | AUDITORIA-01 |
| Marco | Antes de declarar a arquitetura Multiciclo concluída e iniciar a arquitetura Pipeline |
| Objetivo | Determinar se a base construída até aqui (módulos `common/` + `multicycle/`) é suficientemente sólida, coerente e reutilizável para sustentar o avanço até a finalização da Arquitetura 1, e prospectivamente Pipeline, Paralela, FPGA e o fluxo ASIC opcional |
| Data de início | 2026-08-10 |
| Data desta revisão | 2026-08-11 |
| Status | **CONCLUÍDA** (ver §16–17 para o gate formal) |
| Versão/estado relevante do projeto | Módulos comuns e multiciclo-específicos (exceto `sobel_multicycle.sv`) implementados, testados e **reexecutados de verdade nesta sessão** (§4, §6–8). `sobel_multicycle.sv` **não está presente no material auditável desta sessão** — ver Achado F-06 para uma discrepância importante sobre seu status real. |

## 2. Contexto

Esta auditoria surge no ponto em que `sobel_multicycle.sv` — o último módulo pendente da arquitetura multiciclo (`RESUMO_ESTADO_PROJETO.md`, seção "Pendente / em andamento agora") — está referenciado como estando em processo ativo de depuração em uma sessão anterior. Ao longo dessa depuração (registrada na criação deste documento em 2026-08-10), apareceram sinais concretos de que decisões locais podem ter consequências além do módulo onde foram tomadas — o que motivou diretamente `CLAUDE.md`, seção 15.10 (visão de longo prazo obrigatória). Esta revisão (2026-08-11) formaliza esse exercício até uma conclusão auditável, com evidência coletada por execução real das ferramentas do projeto (não apenas leitura de código), conforme exigido pelas regras de processo desta auditoria.

## 3. Escopo

**Dentro:**
- Todos os módulos de `rtl/common/`: `line_buffer_2line.sv`, `window_3x3.sv`, `abs_saturate.sv`, `magnitude_l1.sv`.
- Todos os módulos de `rtl/multicycle/`: `mac_unit.sv`, `kernel_rom.sv`, `mac_control_fsm.sv`, `sobel_multicycle.sv` (este último **auditado quanto à sua ausência/status**, não quanto a um RTL que não foi disponibilizado — ver Achado F-06).
- Os testbenches cocotb correspondentes em `tb_python/`.
- Coerência entre `docs/ESPECIFICACAO_SOBEL.md`, `docs/ARQUITETURA_MULTICICLO.md` e o RTL/testes realmente existentes.
- Consequências previsíveis da divisão `common/` vs. `multicycle/` sobre Pipeline, Paralela, FPGA e ASIC (visão prospectiva).

**Fora:**
- `docs/ARQUITETURA_PIPELINE.md` e `docs/ARQUITETURA_PARALELA.md` como planejamento (referência prospectiva apenas).
- Síntese real em FPGA/ASIC.
- Integração MMIO com o núcleo cv32e40p.

## 4. Critérios e fontes de evidência

Fontes usadas nesta revisão, por tipo:

| Tipo | Fonte | Como foi obtida |
|---|---|---|
| Código-fonte RTL | `rtl/common/*.sv`, `rtl/multicycle/*.sv` (7 arquivos) | Reconstruídos nesta sessão a partir do conteúdo íntegro fornecido no Project Knowledge, byte-a-byte, e comparados de volta contra a fonte para conferência |
| Testbenches | `tb_python/test_*.py` + `_cocotb_helpers.py` (8 arquivos) | Idem — reconstruídos e executados de verdade, não apenas lidos |
| **Execução real de `make cocotb`** | Ambiente Ubuntu 24 desta sessão, Icarus Verilog 12.0 + cocotb 2.0.1 + cocotb-test 0.2.6 + pytest 9.1.1 (mesmas versões de ferramenta citadas nas notas metodológicas do projeto) | `make cocotb` e `pytest -v` executados diretamente nesta sessão (§6.2) |
| **Execução real de `verible-verilog-lint`** | Verible `v0.0-4084-gf3e4d98b` (mesma versão fixa documentada em `COMO_VALIDAR.md`) | Baixado e executado nesta sessão contra os 7 arquivos RTL em escopo (§7.4) |
| **Execução real de `verilator --lint-only -Wall`** | Verilator 5.020 (via apt) | Executado nesta sessão, arquivo a arquivo e depois em conjunto para `mac_control_fsm.sv` com suas dependências (§7.5) — item que os próprios documentos do projeto (`ARQUITETURA_MULTICICLO.md`, §10.1) marcam como `[ ]` não verificado |
| Documentação | `CLAUDE.md`, `RESUMO_ESTADO_PROJETO.md`, `docs/ESPECIFICACAO_SOBEL.md`, `docs/ARQUITETURA_MULTICICLO.md`, `docs/ARQUITETURA_PIPELINE.md`, `docs/ARQUITETURA_PARALELA.md`, `Projeto_IC_Caio_ESEG.md`, `COMO_VALIDAR.md` | Leitura direta e comparação cruzada textual |
| Logs de sessão anterior (F-01 a F-05, D-01 a D-03) | Histórico já registrado na criação deste documento (2026-08-10) | **Não** re-obtidos nesta sessão — preservados como estavam, sem reabertura (Regra de Processo 3), exceto onde uma nova evidência concreta os contradiz (ver F-06) |

Nenhuma métrica de síntese (LUTs, FFs, DSPs, Fmax, potência) e nenhuma medição de cobertura de código (Verilator coverage) são fontes de evidência disponíveis nesta revisão — permanecem como lacunas conhecidas (F-04, inalterado).

## 5. Estado do projeto no início desta revisão

Tabela **corrigida** nesta revisão — a versão original (2026-08-10) continha 1 erro de contagem, encontrado por recontagem direta (`grep -c "^@cocotb.test()"`) nos arquivos reconstruídos nesta sessão:

| Módulo | Implementado | Testado unitariamente (nesta sessão, real) | Corrotinas `@cocotb.test()` | Observação |
|---|---|---|---|---|
| `line_buffer_2line.sv` | ✅ | ✅ PASS | 4 | comum |
| `window_3x3.sv` | ✅ | ✅ PASS | **6** (não 5 — ver nota abaixo) | comum; retrofit de `o_ready` (F-01) |
| `abs_saturate.sv` | ✅ | ✅ PASS | 7 | comum |
| `magnitude_l1.sv` | ✅ | ✅ PASS | 4 | comum |
| `mac_unit.sv` | ✅ | ✅ PASS | 9 | multiciclo |
| `kernel_rom.sv` | ✅ | ✅ PASS | 4 | multiciclo |
| `mac_control_fsm.sv` | ✅ | ✅ PASS | 5 | multiciclo |
| `sobel_multicycle.sv` | **⚠️ status em conflito entre documentos** | não aplicável | não aplicável | **ver Achado F-06 — bloqueador de processo, não de código** |

> **Nota sobre a correção:** a versão de 2026-08-10 deste documento (§5) registrava "5 corrotinas" para `window_3x3.sv`. A recontagem direta no arquivo real (`tb_python/test_window_3x3.py`) mostra 6: `test_reset_state`, `test_geometry_with_zero_padding`, `test_multiple_gap_cycles`, `test_contract_violation_detected`, `test_sustained_contract_violation_detected`, `test_ready_gating_prevents_manual_gap_calculation`. Registrado como Achado F-13 (§11) por ser, em si, uma instância do tipo de erro que esta auditoria existe para pegar — inclusive dentro do próprio processo de auditoria.

"Testado unitariamente (nesta sessão, real)" = passou em execução real de `make cocotb`/`pytest`, nesta sessão, a partir de um ambiente do zero (Icarus + cocotb reinstalados) — não apenas inferido da leitura do código do teste. Ver §6.2 para o log completo.

## 6. Checklist de auditoria

### 6.1 Módulos

- [x] `line_buffer_2line.sv` — ver §7.1
- [x] `window_3x3.sv` — ver §7.1
- [x] `abs_saturate.sv` — ver §7.1
- [x] `magnitude_l1.sv` — ver §7.1
- [x] `mac_unit.sv` — ver §7.2
- [x] `kernel_rom.sv` — ver §7.2
- [x] `mac_control_fsm.sv` — ver §7.2
- [!] `sobel_multicycle.sv` — **não auditável como código nesta sessão** (arquivo não existe no material disponibilizado); auditado quanto ao seu *status declarado*, que está em conflito entre documentos — ver F-06

### 6.2 Testes

- [x] `test_line_buffer_2line.py` — reexecutado, 100% PASS
- [x] `test_window_3x3.py` — reexecutado (3 executores: normal, violação única, violação sustentada), 100% PASS
- [x] `test_abs_saturate.py` — reexecutado (2 executores: normal, caso extremo), 100% PASS
- [x] `test_magnitude_l1.py` — reexecutado, 100% PASS
- [x] `test_mac_unit.py` — reexecutado, 100% PASS
- [x] `test_kernel_rom.py` — reexecutado (2 executores: normal, tap inválido), 100% PASS
- [x] `test_mac_control_fsm.py` — reexecutado (2 executores: normal, violação de contrato), 100% PASS
- [!] `test_sobel_multicycle.py` — não existe no material desta sessão (consistente com `sobel_multicycle.sv` também não existir — ver F-06)

### 6.3 Transversais

- [x] Convenções de nomenclatura e reset (`i_*`/`o_*`, `_r`, `rst_n` assíncrono ativo-baixo) — reverificadas por leitura direta dos 7 módulos reconstruídos nesta sessão; 100% conformes com `CLAUDE.md` §2–3. (Já havia sido concluído em 2026-08-10; recheck nesta revisão não encontrou divergência.)
- [x] Padrão de handshake ready/valid entre módulos — **concluído nesta revisão**: `window_3x3.o_ready = !phantom_pending_r` e `mac_control_fsm.o_ready = (state_r == S_IDLE)` seguem a **mesma convenção semântica** ("posso aceitar `i_valid=1` neste mesmo ciclo"), confirmado por leitura direta das 2 definições. Isso é uma condição necessária (não suficiente) para a fórmula de handshake externo já fechada em `RESUMO_ESTADO_PROJETO.md` ("Design fechado para `sobel_multicycle.sv`", item 3) funcionar como descrito — ver F-07 para o que ainda falta verificar (só é possível com o RTL do integrador, que não existe).
- [!] Estratégia de zero-padding de borda e sua composabilidade entre frames consecutivos — inalterado nesta revisão (nenhuma evidência nova disponível, já que `sobel_multicycle.sv` não está presente); ver F-06.
- [x] Reuso de `common/` sob a ótica de Pipeline/Paralela — concluído nesta revisão como análise prospectiva (não há RTL de Pipeline/Paralela para auditar). Achado direto: `docs/ARQUITETURA_PIPELINE.md` (§3.1, S0) planeja reusar `line_buffer_2line`/`window_3x3` tal como estão; `docs/ARQUITETURA_PARALELA.md` planeja uma variante nova (`line_buffer_3line`) inspirada neles, mas não reutilizando o código diretamente. Consequência: qualquer defeito ou warning de lint em `rtl/common/` (ver F-09) se propaga automaticamente para o reuso planejado em Pipeline e, por design, não para Paralela (que usa um módulo próprio). Isso eleva a prioridade relativa de F-09 especificamente nos 2 arquivos de `common/` que ele afeta.
- [x] Cobertura de código (Verilator coverage) — confirmado, por ausência, que continua não medida (nenhuma instrumentação de cobertura existe no `Makefile` ou nos testbenches atuais). Mantido como lacuna conhecida (F-04, inalterado); medir isso exigiria alterar a infraestrutura de build/teste, o que é uma ação de implementação fora do escopo desta auditoria (Regra de Processo 6).

## 7. Auditoria dos módulos

### 7.1 `rtl/common/` — geral

Os 4 módulos comuns foram relidos integralmente nesta sessão e comparados linha a linha com suas contrapartes em `docs/ARQUITETURA_MULTICICLO.md` (que os documenta em detalhe, incluindo alternativas descartadas). Nenhuma divergência entre RTL e o texto de `ARQUITETURA_MULTICICLO.md` foi encontrada — a documentação de engenharia deste arquivo está factualmente correta e atualizada.

Divergência real encontrada, porém, entre o RTL e `docs/ESPECIFICACAO_SOBEL.md` (o documento de especificação de mais alto nível, não o de arquitetura detalhada) — ver Achado F-12: as assinaturas de porta descritas em `ESPECIFICACAO_SOBEL.md` §3.2 (`valid_in`/`pixel_in`/`line0_out`/… sem prefixo `i_*`/`o_*`, `magnitude_l1` recebendo `gx`/`gy` com sinal em vez de `i_abs_gx`/`i_abs_gy`) não correspondem ao RTL real, que segue corretamente a convenção `i_*`/`o_*` de `CLAUDE.md` §3 e a decomposição real (`abs_saturate` × 2 + `magnitude_l1`, documentada e justificada em `ARQUITETURA_MULTICICLO.md` §4.3–4.4).

### 7.2 `rtl/multicycle/` — geral

Os 3 módulos (`mac_unit.sv`, `kernel_rom.sv`, `mac_control_fsm.sv`) foram relidos e cross-validados nesta sessão:

- Os coeficientes de `kernel_rom.sv` (Gx: posições `[0,2,3,5,6,8]` → `[-1,+1,-2,+2,-1,+1]`; Gy: posições `[0,1,2,6,7,8]` → `[-1,-2,-1,+1,+2,+1]`) foram recalculados manualmente a partir dos kernels-padrão de Sobel (`docs/ESPECIFICACAO_SOBEL.md` §2.1) e conferem exatamente.
- O layout do vetor achatado `i_window`/`o_window` (MSB→LSB, ordem linha-major `k=3·linha+coluna`) é usado de forma **consistente** em 3 lugares independentes — `window_3x3.sv` (produtor), `mac_control_fsm.sv` (consumidor, `win_reg[i] <= i_window[(9-i)*DATA_WIDTH-1-:DATA_WIDTH]`) e o testbench (`_pack_window`/`_unpack_window`) — checado por leitura direta das 3 implementações.
- A contagem de estados/ciclos de `mac_control_fsm.sv` (16 estados enum, `S_IDLE=5'd0` .. `S_OUTPUT=5'd15`) confere com a constante `EXPECTED_CYCLES_TO_VALID = 15` do testbench, e essa asserção **passou em execução real** (`test_cycle_timing`, §6.2).

Nenhum defeito funcional novo foi encontrado nestes 3 módulos nesta revisão.

### 7.3 `sobel_multicycle.sv` — não auditável como código

Este módulo não está presente em nenhuma fonte disponibilizada para esta sessão (nem nos documentos do Project Knowledge, nem em upload). Isso por si só **não é uma reprovação**: `RESUMO_ESTADO_PROJETO.md` já declara esse módulo como "em andamento" e explicitamente "design fechado... ainda não implementado". O que a auditoria encontrou de fato relevante é uma **discrepância entre documentos** sobre esse mesmo status — ver Achado F-06, que é o achado mais importante desta revisão.

### 7.4 Lint de estilo — Verible (execução real, nesta sessão)

```
$ verible-verilog-lint rtl/common/*.sv rtl/multicycle/*.sv
(sem saída, exit code 0)
```

Rodado com a versão fixa `v0.0-4084-gf3e4d98b` (a mesma pinada em `COMO_VALIDAR.md`, evitando o problema de rate-limit da API do GitHub documentado ali). **Resultado: zero warnings nos 7 arquivos**, confirmando por execução real a alegação já registrada em `docs/ARQUITETURA_MULTICICLO.md` §10.1 ("Verible lint ZERO warnings (todos os módulos criados até agora)" — `[x]`).

### 7.5 Lint estrutural — Verilator `--lint-only -Wall` (execução real, nesta sessão — item que os documentos do projeto marcam como pendente)

Este item está marcado `[ ]` (não verificado) em `docs/ARQUITETURA_MULTICICLO.md` §10.1. Esta auditoria o executou de verdade, usando Verilator 5.020:

| Arquivo | Resultado (`--lint-only -Wall`) |
|---|---|
| `rtl/common/abs_saturate.sv` | 1 warning: `WIDTHEXPAND` em `assign value_ext = i_value;` (linha 12) |
| `rtl/common/line_buffer_2line.sv` | 2 warnings: `WIDTHTRUNC` em `LastPtr` e em `WarmThresh` (localparams derivados de `IMG_WIDTH`) |
| `rtl/common/magnitude_l1.sv` | **0 warnings** |
| `rtl/common/window_3x3.sv` | 2 warnings: `WIDTHTRUNC` em `LastCol`; `SYNCASYNCNET` em `rst_n` |
| `rtl/multicycle/kernel_rom.sv` | **0 warnings** |
| `rtl/multicycle/mac_unit.sv` | **0 warnings** |
| `rtl/multicycle/mac_control_fsm.sv` (com dependências: `abs_saturate`, `magnitude_l1`, `mac_unit`, `kernel_rom`) | 3 warnings: `PINMISSING` (`o_addr_valid` de `kernel_rom` não conectado), `WIDTHEXPAND` (propagado de `abs_saturate` via `u_abs_gy`), `SYNCASYNCNET` em `rst_n` |

**Conclusão factual:** o item "Verilator `--lint-only -Wall` ZERO warnings" **não está fechado** — ao contrário do que se poderia supor por analogia com o Verible (que está limpo). São 3 categorias distintas de warning, cada uma com severidade e causa diferentes — ver Achado F-09 (§11) para a análise completa, incluindo qual delas é apenas estilo e qual merece investigação técnica mais séria (`SYNCASYNCNET`).

## 8. Auditoria dos testes

**Execução real, do zero, nesta sessão** (ambiente reconstruído: Icarus 12.0 + cocotb 2.0.1 + cocotb-test 0.2.6 + pytest 9.1.1 + numpy 2.4.4, instalados nesta sessão via apt/pip, não reaproveitados de nenhum estado anterior):

```
$ make cocotb
mkdir -p sim
Rodando testes cocotb (SIM=icarus) ...
cd tb_python && SIM=icarus python3 -m pytest -q
............                                                             [100%]
12 passed in 7.18s
```

```
$ pytest -v (mesmo diretório)
test_abs_saturate.py::test_abs_saturate_runner PASSED
test_abs_saturate.py::test_abs_saturate_two_complement_edge_runner PASSED
test_kernel_rom.py::test_kernel_rom_runner PASSED
test_kernel_rom.py::test_kernel_rom_invalid_tap_idx_runner PASSED
test_line_buffer_2line.py::test_line_buffer_2line_runner PASSED
test_mac_control_fsm.py::test_mac_control_fsm_runner PASSED
test_mac_control_fsm.py::test_mac_control_fsm_contract_violation_runner PASSED
test_mac_unit.py::test_mac_unit_runner PASSED
test_magnitude_l1.py::test_magnitude_l1_runner PASSED
test_window_3x3.py::test_window_3x3_runner PASSED
test_window_3x3.py::test_window_3x3_contract_violation_runner PASSED
test_window_3x3.py::test_window_3x3_sustained_violation_runner PASSED
============================== 12 passed in 5.38s ==============================
```

**12 de 12 executores passaram**, incluindo os 5 executores dedicados de "caminho errado" (contrato violado / valor inválido / caso extremo de complemento de 2) que dependem de `capture_errors()` confirmar contagens **exatas** de `$error` — não apenas "não travou". Esta é a evidência mais forte a favor de um GO desta auditoria: a suíte de testes não é apenas extensa, ela **de fato roda e passa**, reproduzida de forma independente, em um ambiente construído do zero nesta sessão.

**Pergunta orientadora da auditoria original (§8, versão 2026-08-10):** "os testes existentes sustentam a confiança que estamos depositando nesta implementação, ou só confirmam que o caminho feliz funciona?" — **Resposta, com evidência:** não é só caminho feliz. Todos os módulos com contrato violável (`window_3x3`, `kernel_rom`, `mac_control_fsm`, mais o caso de borda de `abs_saturate`) têm teste negativo dedicado, isolado via `run_isolated`/`capture_errors`, com contagem exata de disparos verificada — e todos passaram nesta reexecução. Isso confirma, com evidência de execução real (não de leitura), que a disciplina da seção 15.4 de `CLAUDE.md` está sendo seguida de forma consistente nos 7 módulos existentes.

## 9. Auditoria arquitetural

**Conclusão desta seção (antes pendente, concluída nesta revisão):**

A observação preliminar da versão 2026-08-10 — de que `line_buffer_2line`/`window_3x3` carregam estado interno sem noção de "frame", empurrando toda a responsabilidade de coerência entre frames para quem os integra — **continua válida e não foi contestada por nenhuma evidência nova** (Regra de Processo 3: preservada). O que esta revisão pôde concluir de fato novo, com evidência real:

1. **A base de 7 módulos que hoje tem RTL real é internamente coerente e passa 100% dos seus próprios testes**, incluindo os de contrato violável. Isso é evidência direta a favor de a "base" (no sentido estrito da pergunta desta auditoria) estar pronta.
2. **A superfície de risco identificada em 2026-08-10 (integração de frame) permanece inteiramente dentro de `sobel_multicycle.sv`** — nenhum dos 7 módulos auditados nesta revisão tem qualquer lógica de fronteira de frame, então nenhuma correção dentro deles poderia ter "vazado" esse risco para os módulos já fechados. Isso é uma boa notícia estrutural: o raio de impacto do problema mais sério já identificado no projeto (F-02) está contido, por design, a um único módulo ainda não escrito.
3. **A pergunta arquitetural em aberto não é mais "os módulos comuns são bons o suficiente?"** (resposta: sim, com evidência) **mas sim "o registro do que já foi decidido/tentado para `sobel_multicycle.sv` é confiável?"** — e aqui a resposta desta revisão é **não, sem reconciliação** (F-06). Isso desloca o gate desta auditoria de uma questão técnica para uma questão de processo/registro.

## 10. Impactos futuros

| Etapa futura | Impacto identificado | Natureza | Atualizado nesta revisão? |
|---|---|---|---|
| Pipeline | Reuso planejado e direto de `line_buffer_2line`/`window_3x3` (`docs/ARQUITETURA_PIPELINE.md` §3.1/S0) — herda automaticamente qualquer warning real desses 2 arquivos (F-09: 2+2 warnings Verilator) e qualquer decisão futura sobre F-02/F-06 | **Confirmado** (não mais hipótese) — texto do próprio doc de Pipeline lista os módulos comuns nominalmente | Sim — nesta revisão |
| Paralela | Não reusa o RTL comum diretamente (planeja `line_buffer_3line` novo); herda apenas o *padrão* de projeto, não os warnings específicos | **Confirmado**, por leitura direta de `docs/ARQUITETURA_PARALELA.md` §3.1 | Sim — nesta revisão |
| FPGA (síntese) | Nenhuma métrica real de área/Fmax coletada ainda | Inalterado | Não |
| ASIC | Idem FPGA | Inalterado | Não |
| Timing | Nenhuma análise de caminho crítico real | Inalterado | Não |
| Potência | Nenhuma medição | Inalterado | Não |
| **Verificação (Verilator)** | O item "Verilator -Wall zero warnings" do checklist de `ARQUITETURA_MULTICICLO.md` §10.1, antes apenas `[ ]` (não tentado), agora tem um resultado real e não-trivial (F-09) que **precisa ser decidido** antes de ser marcado `[x]` de boa-fé | **Novo, confirmado nesta revisão** | Sim |

## 11. Problemas, riscos e dívida técnica

Tabela original (F-01 a F-05) preservada sem reabertura, exceto notas de status onde relevante. Achados novos desta revisão: **F-06 a F-13**.

| ID | Descrição | Severidade | Evidência | Status |
|---|---|---|---|---|
| F-01 | `window_3x3.sv` precisou de retrofit (`o_ready`) depois de já fechado/testado | Média | `ARQUITETURA_MULTICICLO.md` §4.2 | Preservado — lição arquitetural, não pendência |
| F-02 | Contaminação de fronteira de frame em `sobel_multicycle.sv` (relatada na sessão de 2026-08-10) | Alta (*se* o código ao qual se refere realmente existir — ver F-06) | Log de simulação da sessão de 2026-08-10, **não re-obtido nesta revisão** | **Status incerto nesta revisão** — ver F-06, que qualifica diretamente este item |
| F-03 | Nenhuma métrica de síntese real coletada | Média | Ausência confirmada | Aberto, sem ação (dependente de etapa futura) |
| F-04 | Cobertura de código (Verilator) nunca medida | Média | Checklist `ARQUITETURA_MULTICICLO.md` §10.2, confirmado ainda `[ ]` nesta revisão (§6.3) | Aberto |
| F-05 | Padrão de bug repetido em `line_buffer_2line`/`window_3x3` mal-interpretados por integradores (sessão 2026-08-10) | Média | Histórico da sessão de 2026-08-10 | Motivou `CLAUDE.md` 15.9/15.10; sem ação adicional |
| **F-06** | **Conflito de status sobre `sobel_multicycle.sv` entre `RESUMO_ESTADO_PROJETO.md` (diz "ainda não implementado", design apenas fechado em discussão) e este próprio documento de auditoria em sua versão de 2026-08-10 (descreve o módulo como "em implementação ativa", com F-02 e as Decisões D-01–D-03 e Ações A-01–A-04 registradas como já *aplicadas e testadas*, "3 dos 4 testes de `sobel_multicycle` passam"). Nenhum RTL nem testbench de `sobel_multicycle.sv` está presente no material desta sessão para arbitrar qual relato é factual agora.** | **Alta — é o principal item que qualquer decisão de avançar precisa resolver antes** | Comparação textual direta entre `RESUMO_ESTADO_PROJETO.md` (seção "Pendente / em andamento agora") e `AUDITORIA_01_PRE_MULTICICLO.md` §1/§5/§11/§12/§13 (versão 2026-08-10) — ambos fornecidos no mesmo Project Knowledge, mesma sessão | **Resolvido** — `RESUMO_ESTADO_PROJETO.md` (seção "Design fechado para `sobel_multicycle.sv`") foi atualizado com evidência de execução real obtida em conversa dedicada: A-01–A-04 confirmados aplicados e validados (`make cocotb`, 3/4 testes); F-02 confirmado ainda aberto no código real. Ver §12 D-04 para o raciocínio da reconciliação e §18 para o registro histórico desta atualização. |
| **F-07** | Suíte de testes dos 7 módulos existentes (`common/` + `multicycle/` exceto o integrador) **reexecutada do zero nesta sessão** — ambiente novo (Icarus 12.0, cocotb 2.0.1, cocotb-test 0.2.6, pytest 9.1.1, numpy 2.4.4), 12/12 executores passaram, incluindo os 5 dedicados a caminho errado | **Positivo** (não é um risco — registrado aqui por ser evidência central do gate) | Log de execução real desta sessão, §6.2/§8 | Confirmado |
| **F-08** | Verible lint (`v0.0-4084-gf3e4d98b`, mesma versão pinada em `COMO_VALIDAR.md`) reexecutado nesta sessão contra os 7 arquivos RTL em escopo: **zero warnings** | **Positivo** | Log de execução real desta sessão, §7.4 | Confirmado |
| **F-09** | Verilator `--lint-only -Wall` (5.020), executado pela primeira vez com evidência real nesta sessão (item antes só `[ ]` no checklist do projeto): **não é zero warnings**. 5 ocorrências distintas: `WIDTHEXPAND`×1 (`abs_saturate.sv`, sign-extension intencional de 1 bit já documentada em `ARQUITETURA_MULTICICLO.md` §4.3 — provável falso-positivo de estilo), `WIDTHTRUNC`×3 (`line_buffer_2line.sv`×2, `window_3x3.sv`×1 — truncamento de `localparam` calculado a partir de parâmetro de largura, padrão comum e provavelmente aceito silenciosamente por Vivado/Quartus, mas não por lint estrito), `SYNCASYNCNET`×2 (`window_3x3.sv` e, por propagação, `mac_control_fsm.sv` — `rst_n` sendo lido de forma síncrona dentro dos blocos de asserção `// synthesis translate_off/on`, o que sugere que o Verilator, nesta invocação, **não está removendo** esses blocos antes de lintar, ao contrário do que ferramentas de síntese como Vivado/Quartus tipicamente fazem para esse pragma), `PINMISSING`×1 (`o_addr_valid` de `kernel_rom` não conectado em `mac_control_fsm` — **decisão já documentada e intencional**, `ARQUITETURA_MULTICICLO.md` §5.3) | **Baixa a Média** — nenhum aponta para um defeito funcional; `SYNCASYNCNET` é o único que merece investigação técnica (ver §13, Ação A-09) porque questiona se o padrão `// synthesis translate_off` do projeto está sendo tratado como o time espera pela ferramenta de lint escolhida | Log de execução real desta sessão, §7.5 | **Decidido nesta sessão (2026-08-13): alternativa (i) `lint_off`/`lint_on` pontual, por não alterar nenhum comportamento sintetizado e não reabrir lógica funcional de módulos já testados. Diffs preparados para `window_3x3.sv`, `mac_control_fsm.sv`, `sobel_multicycle.sv` — pendente de aplicação no repositório real do usuário.** |
| **F-10** | `docs/ARQUITETURA_MULTICICLO.md` §1.1 (resumo no topo do documento) declara "~11 ciclos/pixel" para a arquitetura multiciclo; o valor real, medido pelo teste `test_cycle_timing` (que passou nesta sessão, §6.2/§8), é **15 ciclos** só para `mac_control_fsm` isolado (sem contar a latência de `line_buffer_2line`+`window_3x3` a montante). O próprio documento já registra uma ressalva sobre inconsistência de contagem em §6.2 ("Gx tem 6 taps não-nulos, não 5"), mas essa ressalva **não cobre** o número desatualizado em §1.1, que continua a citar "~11" | Baixa (não afeta RTL/testes, afeta apenas a tabela-resumo de um documento) | Comparação textual direta entre `ARQUITETURA_MULTICICLO.md` §1.1, §6.2, §6.3, e a constante `EXPECTED_CYCLES_TO_VALID = 15` do testbench (confirmada por execução real) | **Fechado (2026-08-13) — verificado que `ARQUITETURA_MULTICICLO.md` §1.1 já contém "15 ciclos/pixel... valor validado por teste real", corrigido em sessão não registrada anteriormente neste documento.** |
| **F-11** | `CLAUDE.md` §1 instrui basear respostas do projeto "especialmente [em] `plano_ic_submissao.md`, `ARQUITETURA_*.md`, `RESUMO_ESTADO_PROJETO.md`" — nenhum arquivo chamado `plano_ic_submissao.md` existe no projeto atual (o documento equivalente presente é `Projeto_IC_Caio_ESEG.md`) | Baixa | Comparação direta entre o texto de `CLAUDE.md` §1 e a lista de arquivos do projeto disponibilizada nesta sessão | **Fechado (2026-08-13) — verificado que `CLAUDE.md` §1 já cita `Projeto IC Caio ESEG.md`, corrigido em sessão não registrada anteriormente.** |
| **F-12** | `docs/ESPECIFICACAO_SOBEL.md` §3.2 (especificação de mais alto nível) descreve interfaces de módulo (`line_buffer_2line`, `window_3x3`, `magnitude_l1`, e uma dupla `kernel_rom_gx`/`kernel_rom_gy`) que **não correspondem** ao RTL real: nomes de porta sem prefixo `i_*`/`o_*` (`valid_in`, `pixel_in`, `line0_out`...), `magnitude_l1` recebendo `gx`/`gy` com sinal em vez da decomposição real via `abs_saturate`×2, e um único `kernel_rom` parametrizado por `i_gy` em vez de 2 ROMs separadas. `docs/ARQUITETURA_MULTICICLO.md` (o documento de detalhamento por arquitetura) **está** atualizado e correto | Média — não bloqueia engenharia (quem trabalha no projeto usa `ARQUITETURA_MULTICICLO.md`, corretamente atualizado, per `CLAUDE.md` §1), mas é uma fonte de confusão para qualquer leitura direta da "especificação oficial" (ex.: orientador, revisor externo) | Comparação linha a linha entre `ESPECIFICACAO_SOBEL.md` §3.2.1/3.2.5/3.3.1 e o RTL real reconstruído nesta sessão | **Diff aplicado nesta sessão (2026-08-13), escopo ampliado para incluir `window_3x3` |
| **F-13** | A versão de 2026-08-10 deste próprio documento de auditoria (§5) contava "5 corrotinas" para `test_window_3x3.py`; a contagem real (`grep -c`, nesta sessão) é 6 | Baixa | §5 desta revisão, com o comando e a lista de nomes | **Corrigido nesta revisão** (ver §5) |
| **F-14** *(nova - 2026-08-13)* | `verible-verilog-lint` (sem `--rules=+line-length=120` explícito) aponta 1 violação de line-length (limite default 100) em `sobel_multicycle.sv:272` — arquivo ausente do escopo de F-08 (2026-08-11) por não existir então | Baixa (possível falso-positivo de invocação) | Log de execução real desta sessão, 2026-08-13 | **Investigação pendente — aguardando resultado de `verible-verilog-lint --rules=+line-length=120` no ambiente do usuário** |

## 12. Decisões

Decisões D-01 a D-03 (versão 2026-08-10) preservadas sem reabertura — nenhuma evidência nova desta sessão as contradiz tecnicamente (elas dizem respeito a um código que esta sessão não pôde re-observar; ver F-06 para o porquê disso ser tratado separadamente, como uma questão de registro, não de mérito técnico da decisão em si).

**Decisão D-04 (nova, revisão 2026-08-11) — Tratar `RESUMO_ESTADO_PROJETO.md` como a fonte de estado corrente, e o conteúdo de F-02/D-01–D-03/A-01–A-04 (versão 2026-08-10 deste documento) como *histórico de raciocínio preservado, mas não confirmado como aplicado ao código atual*.**
- Alternativas consideradas: (A) assumir que a versão 2026-08-10 está correta e que `sobel_multicycle.sv` já existe com 3/4 testes passando, apenas não compartilhado nesta sessão; (B) assumir que `RESUMO_ESTADO_PROJETO.md` está correto e que o trabalho descrito em F-02/D-01–D-03 nunca foi persistido no repositório real (haja vista que o próprio projeto já documentou, em outro contexto, perdas parciais de repositório — `ARQUITETURA_MULTICICLO.md` §5.2/5.3 menciona explicitamente "recuperado após perda parcial do repositório" para `mac_control_fsm.sv`/`kernel_rom.sv`); (C) não assumir nenhuma das duas, registrar o conflito explicitamente e pedir reconciliação ao usuário antes de qualquer gate que dependa da resposta.
- Vantagem de A: aproveita o raciocínio já feito, evita retrabalho.
- Desvantagem de A: viola a Regra de Processo 1 desta auditoria ("nunca dedução isolada") — não há como confirmar que A é verdade sem ver o arquivo.
- Vantagem de B: é a leitura literal e mais conservadora do documento que este projeto define como "o estado atual" (instrução no início desta conversa: "RESUMO_ESTADO_PROJETO.md é o estado atual do projeto").
- Desvantagem de B: descartaria trabalho de depuração real (bugs reais encontrados por execução, não hipotéticos) só por não estar visível nesta sessão — pode ser precipitado.
- Decisão: **C**. Justificativa: é a única opção que não exige apostar em uma suposição não verificável nesta sessão, e é consistente com a Regra de Processo 2 ("não anuncie GO/NO-GO antes de esgotar o checklist... falta de evidência é uma lacuna a registrar, não um vácuo a preencher com suposição").
- Consequência prática: o gate desta auditoria (§17) é condicionado à reconciliação deste ponto — não ao mérito técnico de D-01–D-03, que continuam parecendo decisões sólidas *enquanto hipótese de design* (skid buffer local, `warmup_done_r`, Alternativa B de re-armamento por fronteira de frame), independentemente de já estarem ou não implementadas de fato.

**Decisão D-05 (nova revisão 2026-08-12) — Prevenção estrutural (Alternativa 3-B + Alternativa 6).**
[mesmo conteúdo que eu te enviei antes, só troque "D-04" por "D-05" no título]

| A-14 | Adicionar `i_tag`/`o_tag` (passthrough) em `line_buffer_2line.sv` | Alta | A-05 | Pendente | — |
| A-15 | Adicionar `i_tag`/`o_tag` + comparação + `o_window_valid_geom` em `window_3x3.sv` | Alta | A-14 | Pendente | — |
| A-16 | Reformular A-06 (teste multi-frame) como requisito permanente de "definition of done" por arquitetura | Média | — | Pendente | — |

## 13. Correções e ações

Ações A-01 a A-04 (versão 2026-08-10, marcadas "✅ Concluída") preservadas com a mesma ressalva da Decisão D-04: seu status "concluída" descreve o que a sessão de 2026-08-10 registrou ter acontecido, não o que esta sessão pôde confirmar de forma independente.

| ID | Ação | Prioridade | Dependências | Status | Resultado |
|---|---|---|---|---|---|
| A-01 | Skid buffer profundidade 1 em `sobel_multicycle.sv` | Alta | — | Registrado como "✅ Concluída" em 2026-08-10; **não confirmável nesta sessão** | — |
| A-02 | Corrigir `fsm_i_valid` para depender de `fsm_ready` | Alta | A-01 | Idem A-01 | — |
| A-03 | Latch `warmup_done_r` para suprimir janelas de "linha -1" | Alta | — | Idem A-01 | — |
| A-04 | Corrigir condição do laço `while` em `_feed_image_and_collect` | Média | — | Idem A-01 | — |
| A-05 | Aplicar Alternativa B (re-armar descarte a cada fronteira de frame) | Alta — bloqueadora | A-03 | **Resolvido** — mesma evidência de F-06. Ambos os documentos agora concordam: A-01–A-04 aplicados/validados, F-02 aberto | — |
| A-06 | Teste dedicado de 3+ frames consecutivos | Média | A-05 | Pendente | — |
| A-07 | Teste do caso degenerado `IMG_HEIGHT=1` | Baixa | A-05 | Pendente | — |
| A-08 | Medir cobertura de código real (Verilator) para os 7 módulos já fechados | Média | — | Pendente (F-04) | — |
| **A-09** *(nova)* | Investigar por que `// synthesis translate_off`/`translate_on` não impede o `SYNCASYNCNET` do Verilator nos blocos de asserção de `window_3x3.sv`/`mac_control_fsm.sv` (F-09) — decidir entre: (i) usar `/* verilator lint_off SYNCASYNCNET */`/`lint_on` ao redor do bloco de asserção; (ii) reestruturar a asserção para não reler `rst_n` como dado; (iii) aceitar o warning como esperado e documentar por quê | Baixa–Média | — | Pendente (planejada nesta auditoria, não implementada — Regra de Processo 6) | — |
| **A-10** *(nova)* | Silenciar/corrigir os warnings `WIDTHEXPAND`/`WIDTHTRUNC` do Verilator (F-09) com casts explícitos, ou documentar por que são aceitáveis, para fechar de fato o item `[ ]` de `ARQUITETURA_MULTICICLO.md` §10.1 | Baixa | — | **Decidido nesta sessão (2026-08-13): alternativa (i) cast explícito de largura — `(IN_WIDTH+1)'(i_value)` em `abs_saturate.sv`; `PtrWidth'(...)`/`WarmupWidth'(...)` em `line_buffer_2line.sv`; `ColWidth'(...)` em `window_3x3.sv`. Diffs entregues ao usuário, pendentes de aplicação no repositório real.** | — |
| **A-11** *(nova)* | Atualizar `docs/ESPECIFICACAO_SOBEL.md` §3.2 para refletir as interfaces reais (`i_*`/`o_*`, decomposição `abs_saturate`+`magnitude_l1`, `kernel_rom` único parametrizado) — o próprio arquivo já se declara "documento vivo" (F-12) | Baixa | — | Pendente | — |
| **A-12** *(nova)* | Corrigir a referência a `plano_ic_submissao.md` em `CLAUDE.md` §1 para o nome de arquivo real do projeto (F-11) | Baixa | — | Pendente | — |
| **A-13** *(nova)* | Corrigir "~11 ciclos/pixel" em `ARQUITETURA_MULTICICLO.md` §1.1 para refletir os 15 ciclos medidos por teste real (F-10), e recalcular a latência total considerando `line_buffer_2line`+`window_3x3` a montante | Baixa | — | Pendente | — |

## 14. Questões em aberto

- **Q-01, Q-02, Q-03, Q-04** (versão 2026-08-10): preservadas sem alteração — nenhuma evidência nova desta sessão as resolve, já que todas dependem de `sobel_multicycle.sv` existir e ser testável, o que não foi possível nesta revisão.
- **Q-05** *(nova)*: qual dos dois relatos sobre `sobel_multicycle.sv` é factual agora — o de `RESUMO_ESTADO_PROJETO.md` ("ainda não implementado") ou o desta própria auditoria em sua versão de 2026-08-10 ("em implementação ativa, 3/4 testes passando")? Esta pergunta só pode ser respondida pelo usuário (ex.: confirmando se o arquivo existe no repositório real e, se sim, compartilhando-o) — nenhuma quantidade adicional de leitura ou execução nesta sessão consegue arbitrar isso, porque a resposta depende de um estado externo a este chat (o repositório real do usuário) que não foi disponibilizado aqui.

## 15. Decisões preservadas

Todas as decisões preservadas na versão 2026-08-10 continuam válidas e **confirmadas com evidência adicional real nesta revisão** onde indicado:

- Reset assíncrono ativo-baixo (`rst_n`) — `CLAUDE.md` §15.1. **Reconfirmado** nesta revisão por releitura dos 7 módulos reconstruídos.
- Convenções de nomenclatura (`i_*`/`o_*`, `_r`, `UPPER_SNAKE_CASE`) — **reconfirmado**, mesma base.
- Magnitude L1 (`|Gx|+|Gy|`) em vez de L2 — sem evidência nova que a questione.
- `line_buffer_2line` com 2 estágios em cascata — **reconfirmado por execução real** (`test_delay_and_zero_padding`, `test_ignores_invalid_cycles`, `test_midstream_reset`, todos PASS nesta sessão).
- `kernel_rom.sv` com trava ativa (`o_addr_valid`) — **reconfirmado por execução real** (`test_invalid_tap_idx_safe_and_error`, contagem exata de 4 disparos de `$error`, PASS nesta sessão).
- Retrofit do `o_ready` em `window_3x3.sv` (F-01) — **reconfirmado por execução real** (`test_ready_gating_prevents_manual_gap_calculation`, PASS nesta sessão), reforçando que a lição de 2026-08-10 (retrofit foi decisão correta) continua sustentada por evidência, não só por registro.
- **Novo nesta revisão:** a decomposição `abs_saturate` (função pura, reusável) + `magnitude_l1` (soma+saturação) em vez de um `magnitude_l1` monolítico com valor absoluto embutido (como o esboço original em `ESPECIFICACAO_SOBEL.md` sugeria) — confirmada como correta e deliberada por `ARQUITETURA_MULTICICLO.md` §4.3–4.4, e reconfirmada por execução real dos 2 módulos separadamente (`test_abs_saturate.py`, `test_magnitude_l1.py`, ambos PASS). Preservada; a divergência com `ESPECIFICACAO_SOBEL.md` é tratada como pendência de documentação (F-12/A-11), não como erro de arquitetura.

## 16. Conclusão

**Determinável nesta versão**, ao contrário da versão de 2026-08-10 (que declarou explicitamente "não determinável").

A base técnica — os 7 módulos que hoje têm RTL real, mais seus testbenches — está **sólida por evidência real, obtida nesta sessão de forma independente**: reconstrução do zero, reexecução completa da suíte de testes (12/12, incluindo os 5 executores de caminho errado com contagem exata de `$error`), lint de estilo limpo (Verible, versão pinada do projeto), e uma primeira execução real do lint estrutural (Verilator `-Wall`) que revela apenas problemas de baixa a média severidade, nenhum deles um defeito funcional (F-09).

O que impede um GO simples e incondicional não é nada encontrado nos 7 módulos auditados — é a **incerteza sobre o que já existe ou não** para `sobel_multicycle.sv` (F-06), que esta sessão não pode resolver sozinha porque depende de um estado (o repositório real do usuário) que não foi compartilhado aqui. Isso é qualitativamente diferente do NO-GO tendencial que a versão anterior deste documento cogitou (baseado em F-02 estar "aberto e bloqueador") — aqui o bloqueio não é "há um bug conhecido não corrigido", é "não sabemos com confiança qual é o estado real, e por isso não deveríamos assumir nenhum dos dois relatos como base para o próximo passo".

## 17. Gate de avanço

**Status: GO WITH CONDITIONS.**

**Para a base já existente (`rtl/common/` + `rtl/multicycle/` exceto o integrador, e seus testbenches):** GO. Sustentada por evidência de execução real desta sessão (não dedução), nas 3 frentes verificadas — corretude funcional (testes), estilo (Verible), e portabilidade/estrutura (Verilator, item antes nunca verificado). Nenhum achado de severidade Alta nestes 7 módulos.

**Para o avanço imediato sobre `sobel_multicycle.sv`:** condicionado a **resolver Q-05/F-06 antes de escrever ou continuar qualquer código novo desse módulo** — ou seja, confirmar com o usuário se o trabalho descrito na versão 2026-08-10 deste documento (skid buffer, `warmup_done_r`, 3/4 testes passando) já existe no repositório real, e se sim, trazê-lo para uma próxima sessão para que possa ser verificado com o mesmo rigor aplicado aqui aos outros 7 módulos. As decisões de design já fechadas (D-01 a D-03, e os itens 1–5 de "Design fechado para `sobel_multicycle.sv`" em `RESUMO_ESTADO_PROJETO.md`) continuam válidas como **plano**, independentemente da resposta a Q-05 — o que muda com a resposta é só o ponto de partida (implementar do zero vs. retomar de onde a sessão de 2026-08-10 parou).

**Condições secundárias:** F-09 e A-10 fechados/decididos (2026-08-13); resta apenas F-15 (possível sintaxe incorreta do comando de lint em `ESPECIFICACAO_SOBEL.md` §6.1, não confirmada, baixa prioridade) — nenhum dos dois bloqueia o avanço para a Alternativa 3-B. **Único bloqueador técnico real do projeto, em qualquer frente, é F-02/A-05.**

**Critério de reavaliação:** esta seção deve ser revisitada assim que (a) Q-05 for respondida e, se aplicável, o RTL real de `sobel_multicycle.sv` puder ser auditado com o mesmo rigor de execução real usado aqui; ou (b) uma nova versão de `sobel_multicycle.sv` for escrita do zero e testada, o que quer que Q-05 revele.

## 18. Histórico

| Data | Alteração | Motivo |
|---|---|---|
| 2026-08-10 | Criação do documento; estrutura preenchida com estado factual conhecido até o momento; F-01 a F-05 e D-01 a D-03 registrados a partir do histórico da sessão de depuração de `sobel_multicycle.sv` | Auditoria formal pré-marco Multiciclo, solicitada explicitamente antes de avançar para Pipeline |
| 2026-08-11 | Revisão completa: reconstrução independente do repositório (7 módulos RTL + 8 arquivos de teste) nesta sessão; execução real de `make cocotb` (12/12 PASS), `verible-verilog-lint` (0 warnings) e `verilator --lint-only -Wall` (5 warnings reais, item antes nunca verificado); correção de 1 erro de contagem no próprio documento (F-13); descoberta de um conflito de status sobre `sobel_multicycle.sv` entre este documento e `RESUMO_ESTADO_PROJETO.md` (F-06); checklists de §6 fechados; §7–9 preenchidas; gate formal emitido em §17 (GO WITH CONDITIONS) | Conclusão da Auditoria Arquitetural 01, conforme solicitado |
| 2026-08-12 | F-06/Q-05 atualizados de "Aberto" para "Resolvido", com evidência de execução real obtida em conversa dedicada sobre `sobel_multicycle.sv` (não nesta sessão de revisão). Corrigida confusão de numeração entre 2 linhagens divergentes deste documento que circularam brevemente entre sessões. | Fechar a reconciliação de estado antes de decidir o gate final |
| 2026-08-13 (continuação 2) | A-10 decidido (alternativa i, cast explícito de largura) — diffs entregues, pendentes de aplicação. Com isso, todos os achados de menor severidade da Auditoria 01 estão fechados ou decididos; resta apenas F-02/A-05 (Alternativa 3-B) como pendência real do projeto. | Esgotamento do escopo de menor severidade solicitado nesta sessão |

---

## Apêndice — Estrutura reaproveitável para futuras auditorias (AUDITORIA_02 em diante)

Como esta é a primeira auditoria da série, o padrão de seções abaixo deve ser reaproveitado integralmente nas próximas (numeração sequencial: `AUDITORIA_02_...md`, `AUDITORIA_03_...md`, UPPER_SNAKE_CASE, zero-padded):

1. Identificação — sempre com "Data de início" e, se houver revisão, "Data desta revisão" separadas.
2. Contexto — 1 parágrafo, referenciando o marco anterior.
3. Escopo — dentro/fora, explícito.
4. Critérios e fontes de evidência — **manter a distinção entre evidência obtida por execução real nesta sessão vs. evidência herdada de sessões anteriores** (esta distinção foi o que permitiu identificar F-06 nesta auditoria).
5. Estado do projeto no início — tabela factual, recontada por comando real sempre que possível (não por leitura visual do código de teste).
6. Checklist (módulos / testes / transversais).
7–9. Auditoria dos módulos / dos testes / arquitetural — texto corrido, sempre citando arquivo+seção como evidência.
10. Impactos futuros — tabela.
11. Problemas/riscos/dívida técnica — tabela com ID sequencial global (não reiniciar a numeração F-xx a cada auditoria).
12. Decisões — formato "alternativas consideradas → vantagem/desvantagem → decisão → justificativa".
13. Correções e ações — tabela com ID sequencial global (A-xx).
14. Questões em aberto — ID sequencial global (Q-xx).
15. Decisões preservadas.
16. Conclusão.
17. Gate de avanço — só GO/GO WITH CONDITIONS/NO-GO depois do checklist esgotado (Regra de Processo 2).
18. Histórico — 1 linha por revisão, nunca reescrever linhas antigas.

**Recomendação para a próxima auditoria (quando `sobel_multicycle.sv` estiver de fato disponível para revisão):** abrir como `AUDITORIA_02_PRE_PIPELINE.md` (ou nome equivalente) somente depois que Q-05 desta auditoria estiver resolvida, reiniciando o "Estado do projeto no início" a partir do resultado real dessa reconciliação — não a partir do texto de F-02/D-01–D-03 preservado aqui, que deve ser tratado, na próxima auditoria, como confirmado ou descartado, não mais como "em aberto".
