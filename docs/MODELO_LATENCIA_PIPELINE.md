# Modelo de Latência/Identidade — Pipeline `sobel_multicycle.sv`

**Status:** Camada 1 (ordem/identidade) implementada e validada por construção. Hipótese central (janela espúria por fronteira de frame) **corroborada por evidência já coletada, não confirmada por execução direcionada**. Nenhuma mudança de RTL foi feita a partir deste documento.

---

## 1. Objetivo

Determinar, para cada janela 3×3 que `window_3x3.sv` emite (ordem contínua, sem noção de frame — decisão de projeto já documentada em `ARQUITETURA_MULTICICLO.md` §4.2), **qual posição lógica de saída `(frame, linha, coluna)` ela representa**, ou se é uma janela espúria que não deveria contar como saída real — **sem depender do mecanismo de tag de 1 bit (`frame_tag_r`)**, que a investigação desta sessão provou não ser um indicador confiável de conteúdo (Teste D, pós-Alternativa-A: janelas com `win_tag != frame_tag_r` produziram pixel **correto**; a causa real do defeito está em outro lugar).

### 1.1 Por que este modelo existe agora

As últimas 5 correções em `sobel_multicycle.sv` (F-16 Metade 1, F-16 Metade 2, Alternativa A3, Alternativa A) seguiram o mesmo padrão: uma hipótese local, testada num cenário estreito, "parece resolver", e um sintoma reaparece em outro lugar. A causa raiz de fundo (ver conversa desta sessão) é a ausência de um modelo único que amarre a relação entre os 5 estágios do pipeline (`line_buffer_2line` → `line_window_skid` → `window_3x3` → `skid_fifo2` → `mac_control_fsm`). Este documento é o primeiro passo para fechar essa lacuna.

## 2. Escopo e estrutura do modelo

### 2.1 Camada 1 — Ordem/Identidade (implementada)

Puramente combinatória: não modela ciclos de relógio, backpressure ou stall — modela apenas **qual amostra de entrada corresponde a qual janela de saída**, na ordem em que ambas ocorrem. Isso é suficiente para diagnosticar bugs de **conteúdo** (o problema atual), porque `line_window_skid` e `skid_fifo2` são FIFOs que preservam ordem — não reordenam nem duplicam (Teste A já confirmou isso por execução: "nenhuma duplicata de conteúdo").

### 2.2 Camada 2 — Tempo/Ciclos (fora de escopo desta entrega)

Prediria o ciclo exato de cada evento, incorporando os padrões de stall observados (`deltas` `[15,16,1,32]` repetindo, já visíveis nos logs desta sessão). Não implementada aqui — recomendada como próxima extensão (seção 7).

### 2.3 Premissas adotadas

| Premissa | Justificativa |
|---|---|
| Sem stall externo (`stall_prob=0.0`) | Todos os dados reais disponíveis (Testes A-D) foram coletados nesse regime; modelar stall externo exigiria uma camada de tempo que não temos evidência suficiente para validar ainda |
| `line_window_skid`/`skid_fifo2` preservam ordem, sem duplicação/perda | Confirmado por execução (Teste A, "verificação de conteúdo duplicado": nenhuma duplicata) |
| `window_3x3` não tem noção de frame | Decisão de projeto já documentada (`ARQUITETURA_MULTICICLO.md` §4.2), não é premissa nova |

## 3. Derivação — 2 fatos estruturais (lidos do RTL, não hipótese)

**Fato (a):** a janela emitida enquanto se alimenta a linha de entrada `r` está centrada em `i_line1`, que `line_buffer_2line.sv` entrega com **1 linha de atraso** (mesma coluna). Logo: alimentar a linha de entrada `r` produz janelas de saída para a linha `r-1`.

**Fato (b):** `window_3x3.sv` nunca emite janela na 1ª coluna de uma linha (precisa do vizinho esquerdo). As colunas `1..W-1` da linha de entrada produzem `W-1` janelas (colunas de saída `0..W-2`); o "ciclo fantasma" da borda direita produz a `W`-ésima janela (coluna de saída `W-1`). Total: `W` janelas de saída por linha de entrada.

## 4. A hipótese central — janela espúria por fronteira

`i_rearm` (Alternativa 3-C, já testada e funcionando corretamente) força `warm1`/`warm2` de volta a zero **no primeiro ciclo de CADA frame**, não só no power-up — necessário para a borda superior de cada frame. Consequência colateral: **alimentar a linha 0 de qualquer frame produz uma "linha de saída -1" virtual**, exatamente como no frame 0.

**Hipótese:** `discard_cnt_r`/`warmup_done_r` (o mecanismo que descarta essa linha virtual) só dispara **uma vez na vida do módulo** — a partir do frame 2, essas `IMG_WIDTH` janelas espúrias por frame não são mais descartadas.

## 5. Validação

### 5.1 Camada 1, caso 1 frame — CONFIRMADO por construção

Testado contra `_build_reference_windows_with_bottom_padding` (referência já validada e em uso em `test_win_reg_direct.py`), para `(W,H) ∈ {(4,3), (6,3), (8,3), (5,4)}`: geometria das janelas reais bate 100%; contagem de espúrias = `W` em todos os casos (script `models/validate_model.py`, rodado nesta sessão).

### 5.2 Hipótese multi-frame — corroborada por dados já coletados, não confirmada por execução direcionada

Aplicando a hipótese aos números reais do Teste C (pós-Alternativa-A, `W=4, H=3`, 4 frames):

| Frame | Filtrado de fato (medido) | Previsto pela hipótese (`=W`) | Diagnóstico |
|---|---|---|---|
| 1 | 4 | 4 | Consistente — mecanismo original (`discard_cnt_r`) funcionando |
| 2 | 3 | 4 | **Déficit de exatamente 1** — Alternativa A filtrou 1 a menos que o necessário |
| 3 | 3 | 4 | **Déficit de exatamente 1** — idem |
| 4 | 3 | 4 | **Déficit de exatamente 1** — idem |

Esse padrão (déficit constante de exatamente 1, em todo frame após o primeiro) é altamente específico — improvável de ser coincidência, mas **não é prova por execução direcionada**.

### 5.3 O que falta para virar fato

`tb_python/test_pipeline_identity_model.py` — compara, por **conteúdo real** (não tag), cada janela `win_valid` bruta contra a predição do modelo: se a hipótese estiver certa, toda janela prevista como espúria deve ter `line1`/`line2` genuinamente zero. Não executado nesta sessão (ambiente sem o repositório real).

## 6. Recomendação — antes de qualquer novo diff

1. **Reverter a Alternativa A** — ela não ataca a causa provável e usa a magnitude errada (3 em vez de `IMG_WIDTH`).
2. **Rodar `test_pipeline_identity_model.py`** contra o RTL revertido — se confirmado, a correção correta é re-armar `discard_cnt_r`/`warmup_done_r` (mesmo padrão do `i_rearm` já usado em `line_buffer_2line.sv`) com limiar `IMG_WIDTH`, **não** um número medido empiricamente por um proxy (tag) já demonstrado não confiável.
3. Só então propor o diff, com o mesmo gate de aceitação já estabelecido (Teste A/C recontados, `test_four_consecutive_frames` sem mismatch).

## 7. Limitações e trabalho futuro

- Camada 2 (tempo/ciclos) não implementada — necessária para prever exatamente em que ciclo cada evento ocorre sob stall externo arbitrário.
- Modelo assume `stall_prob=0.0`; comportamento sob stall externo real não coberto.
- A hipótese da seção 4 é a explicação mais provável encontrada até agora, mas convive com a possibilidade (não descartada) de um segundo efeito menor sobreposto — só a execução direcionada (seção 5.3) fecha isso com certeza.

## 8. Arquivos deste modelo

| Arquivo | Papel |
|---|---|
| `tb_python/models/pipeline_identity_model.py` | Camada 1 — implementação |
| `tb_python/models/validate_model.py` | Validação self-contida (roda sem RTL) |
| `tb_python/test_pipeline_identity_model.py` | Validação contra RTL real (pendente de execução) |
