# Registro técnico do fluxo Quartus — Projeto ic-sobel-hw-fpga

> **Propósito.** Registrar formalmente o estado da caracterização da arquitetura Multiciclo do filtro de Sobel no Quartus Prime Lite 25.1std, dentro do container Docker do projeto `ic-sobel-hw-fpga`. Documento destinado ao repositório Git, com foco em rastreabilidade, reprodutibilidade e continuidade.

---

## 1. Identificação e contexto

- **Projeto:** `ic-sobel-hw-fpga` — implementação do filtro de Sobel em FPGA, com foco em caracterização arquitetural de três variantes (Multiciclo, Pipeline, Paralela).
- **Arquitetura caracterizada nesta etapa:** Multiciclo (única com RTL implementado).
- **Objetivo desta etapa:** obter números de síntese e timing da arquitetura Multiciclo no dispositivo Cyclone V, sem placa física disponível.
- **Escopo:** criação e configuração do projeto Quartus; compilação completa (map, fit, asm, sta); extração de recursos, timing e caminho crítico; registro dos achados.
- **Fora do escopo:** refatoração de RTL; caracterização das arquiteturas Pipeline e Paralela; estimativa de potência; segundo vendor (Vivado); caracterização ASIC.
- **Ambiente:** Ubuntu 24.04 em container Docker, acessado via VS Code Dev Containers, sobre WSL no host Windows.

---

## 2. Preparação do ambiente e instalação do Quartus

### 2.1 Sistema e container

- **SO base:** `ubuntu:24.04` (imagem oficial).
- **Ferramenta de container:** Docker.
- **Interface:** VS Code Dev Containers.
- **Usuário do container:** `vscode`, UID/GID 1000.
- **Contexto do build:** pasta pai do `.devcontainer/`.
- **Mount do projeto:** `/workspaces/ic-sobel-hw-fpga`.

### 2.2 Volume persistente para o Quartus

- **Tipo:** volume Docker nomeado `quartus-install`.
- **Ponto de montagem:** `/opt/intelFPGA_lite`.
- **Declaração em `.devcontainer/devcontainer.json`:**

  ```json
  "mounts": [
      "source=quartus-install,target=/opt/intelFPGA_lite,type=volume"
  ]
  ```

- **Justificativa:** o Quartus ocupa vários GB. Sem volume persistente, a instalação é apagada a cada rebuild do container.

### 2.3 Dependências do sistema

Além dos pacotes já presentes no `Dockerfile` (Icarus, Verilator, Verible, LaTeX, Python), foram instaladas bibliotecas de 32 bits exigidas pelo Quartus:

- `g++-multilib`
- Bibliotecas i386: `libxft2`, `libncurses6`, `libxext6`, `libx11-6`, `libxau6`, `libxdmcp6`, `libbsd0`, `libmd0`, `libtinfo6`, `zlib1g`, `libpng16-16`, `libfreetype6`, `libfontconfig1`, `libexpat1`, `libglib2.0-0`, `libglx0`, `libgl1`, `libice6`, `libsm6`, `libuuid1`, `libselinux1`, `libpcre2-8-0`, `libattr1`, `libacl1`, `libgcc-s1`, `libstdc++6`.

### 2.4 Variável `PATH`

Adicionada no `Dockerfile`:

```dockerfile
ENV PATH=$PATH:/opt/intelFPGA_lite/25.1std/quartus/bin
```

Isso garante que `quartus_sh`, `quartus_map`, `quartus_fit`, `quartus_sta` estejam no `PATH` em qualquer shell iniciado dentro do container.

### 2.5 Versão e edição do Quartus

- **Edição:** Quartus Prime Lite.
- **Versão:** 25.1std.
- **Componentes instalados:** `quartus`, `cyclonev`.
- **Método:** instalador SFX (`qinst-lite-linux-25.1std-1129.run`), extraído com `--noexec` e instalado com `./qinst.sh --cli --components ...`.

### 2.6 Comandos de instalação

Executados **dentro do container**, a partir de `/tmp`:

```bash
# Obtenção do instalador (via download no navegador do host, depois movido para o container)
# Motivo: o wget direto do CDN da Altera retorna 403 Forbidden.

./qinst-lite-linux-25.1std-1129.run --target /tmp/qinst --noexec
cd /tmp/qinst
./qinst.sh --cli --help   # verificar nomes de componentes
./qinst.sh --cli \
  --components quartus,cyclonev \
  --download-dir /tmp/quartus-download \
  --install-dir /opt/intelFPGA_lite/25.1std \
  --delete-downloads \
  --accept-eula
```

### 2.7 Verificação da instalação

```bash
which quartus_sh quartus_map quartus_fit quartus_sta
quartus_sh --version
```

Saída esperada: caminhos em `/opt/intelFPGA_lite/25.1std/quartus/bin/` e versão 25.1.0.

**Lacuna identificada:** o build exato reportado por `quartus_sh --version` não foi colado no histórico. Verificar com o comando acima antes de qualquer publicação.

---

## 3. Fluxo de trabalho executado

### Etapa 3.1 — Smoke test

**Objetivo:** validar o fluxo completo (`quartus_sh` → `quartus_map` → `quartus_fit` → `quartus_asm` → `quartus_sta`) com um design trivial antes de tentar o RTL real.

**Procedimento:** criado um `counter.sv` (contador de 8 bits), um `counter.sdc`, um `setup_smoke.tcl`; rodado `quartus_sh --flow compile counter`.

**Resultado observado:** fluxo completo sem erros; relatórios gerados.

**Evidência:** confirmado no histórico ("Smoke validado e concluído com sucesso").

### Etapa 3.2 — Criação do projeto real

**Objetivo:** criar o projeto Quartus para o `sobel_multicycle`.

**Arquivo usado:** `constraints/setup_proj.tcl`.

**Comando:**

```bash
quartus_sh -t constraints/setup_proj.tcl
```

**Problema encontrado #1:** atribuição `SYSTEMVERILOG_INCLUDE` rejeitada com `ERROR: Illegal assignment`. **Solução:** substituída por `SEARCH_PATH "include"`.

**Problema encontrado #2:** erro `can't open Verilog Design File "timescale.svh"` ao analisar arquivos individualmente. **Causa:** `SEARCH_PATH` ainda não tinha sido propagado ao `.qsf` (projeto não tinha sido recriado após edição do `.tcl`). **Solução:** `rm -rf db/ incremental_db/ output_files/ *.qpf *.qsf` e reexecução do `setup_proj.tcl`.

**Problema encontrado #3:** `quartus_map --analyze_file=<arquivo>` não lê o `.qsf`, portanto **não** respeita `SEARCH_PATH`. **Solução:** abandonar o `--analyze_file` e ir direto para `quartus_sh --flow compile`, que tem contexto completo do projeto.

### Etapa 3.3 — Compilação completa

**Comando:**

```bash
quartus_sh --flow compile sobel_multicycle
```

**Resultado:** compilação bem-sucedida. Sem erros. Warnings e infos documentados abaixo.

### Etapa 3.4 — Extração do caminho crítico

**Comando:**

```bash
quartus_sta sobel_multicycle --do_report_timing
```

**Saída:** `.sta.rpt` atualizado com Fmax e slack. Caminho crítico extraído separadamente (`critical_path_summary.rpt`) — conteúdo exato do script Tcl **[não verificado]**.

---

## 4. Inventário dos arquivos e artefatos

### 4.1 Arquivos-fonte do projeto (versionar)

| Caminho | Descrição |
|---|---|
| `rtl/common/line_buffer_2line.sv` | Atraso de 2 linhas |
| `rtl/common/window_3x3.sv` | Janela 3×3 deslizante |
| `rtl/common/abs_saturate.sv` | Valor absoluto + saturação |
| `rtl/common/magnitude_l1.sv` | Soma L1 com saturação |
| `rtl/common/line_window_skid.sv` | FIFO síncrona de profundidade 2 |
| `rtl/multicycle/mac_unit.sv` | MAC sem multiplicador |
| `rtl/multicycle/kernel_rom.sv` | LUT combinacional dos coeficientes |
| `rtl/multicycle/mac_control_fsm.sv` | FSM de 16 estados |
| `rtl/multicycle/skid_fifo2.sv` | FIFO de profundidade 2 entre window_3x3 e FSM |
| `rtl/multicycle/sobel_multicycle.sv` | Top-level |
| `include/timescale.svh` | Diretivas `` `timescale `` compartilhadas |

### 4.2 Arquivos de configuração do Quartus (versionar)

| Caminho | Descrição |
|---|---|
| `constraints/multicycle.sdc` | Restrição de clock |
| `constraints/setup_proj.tcl` | Script de criação do projeto |
| `critical_path.tcl` (se versionado) | Script de extração de caminhos |

### 4.3 Artefatos gerados pelo Quartus (não versionar)

| Caminho | Descrição |
|---|---|
| `sobel_multicycle.qpf` | Apontador de projeto |
| `sobel_multicycle.qsf` | Atribuições (derivado do `.tcl`) |
| `db/`, `incremental_db/` | Bancos internos |
| `output_files/sobel_multicycle.fit.rpt` | Relatório de utilização |
| `output_files/sobel_multicycle.sta.rpt` | Relatório de timing |
| `critical_path_summary.rpt` | 10 piores caminhos |
| `critical_path_full.rpt` | Pior caminho detalhado |

**Recomendação:** adicionar ao `.gitignore`:

```
db/
incremental_db/
output_files/
*.qpf
*.qsf
*.rpt
quartus_install/
```

**Ressalva:** versionar `.qsf` **pode** ser útil como registro do estado efetivamente aplicado, mas ele é derivado do `.tcl`. Se versionado, deve ser tratado como artefato de auditoria, não como fonte de verdade. **Recomendação atual:** manter fora do Git e regenerar via `setup_proj.tcl`.

### 4.4 Configuração do container (versionar)

| Caminho | Descrição |
|---|---|
| `Dockerfile` | Definição da imagem |
| `devcontainer.json` | Configuração do Dev Container |
| `requirements.txt` | Dependências Python |

---

## 5. Configuração, scripts e restrições

### 5.1 `constraints/setup_proj.tcl`

Papel: criar o projeto e aplicar todas as atribuições. Executado com `quartus_sh -t`. Ver `GUIA_QUARTUS_EXPLICADO.md` §2.1 para explicação linha a linha.

**Atribuições críticas:**

- `FAMILY` / `DEVICE` — dispositivo alvo.
- `TOP_LEVEL_ENTITY` — hierarquia.
- `SEARCH_PATH "include"` — resolução do `timescale.svh`.
- 10× `SYSTEMVERILOG_FILE` — fontes.
- `SDC_FILE` — restrição.
- `PROJECT_OUTPUT_DIRECTORY` — organização.

### 5.2 `constraints/multicycle.sdc`

Papel: impor restrição de clock. Conteúdo:

```tcl
create_clock -name clk -period 10.000 [get_ports {clk}]
derive_clock_uncertainty
```

**Efeito verificado:** o `.sta.rpt` mostra o clock `clk` com período `10.000` ns e frequência `100.0 MHz`. Portanto o SDC foi efetivamente lido.

### 5.3 `critical_path.tcl`

Papel: extrair os 10 piores caminhos de setup e o pior caminho detalhado. Executado com `quartus_sta -t critical_path.tcl`. **Conteúdo exato não verificado no histórico** — foi sugerido nesta conversa e o usuário reportou os resultados de `--do_report_timing` (Opção B). Presume-se que o `.tcl` tenha sido executado (evidência: existência de `critical_path_summary.rpt`).

---

## 6. Resultados obtidos

### 6.1 Instalação

- **Verificado:** `which quartus_sh quartus_map quartus_fit quartus_sta` retorna caminhos válidos.
- **Verificado:** versão 25.1std, componentes `quartus` + `cyclonev`.

### 6.2 Utilização de recursos

Fonte: `output_files/sobel_multicycle.fit.rpt`.

| Recurso | Valor |
|---|---|
| ALMs needed | 4.601 / 32.070 (14%) |
| Registradores | 6.270 |
| DSP Blocks | **0 / 87 (0%)** |
| M10K blocks | 3 / 397 |
| Block Memory Bits | 5.904 |
| Pins | 24 |

**Distribuição de ALMs por hierarquia (com sub-hierarquia):**

| Módulo | ALMs | % |
|---|---|---|
| `line_buffer_2line` | 4.345 | 94% |
| `mac_control_fsm` | 89,7 | 2% |
| `skid_fifo2` | 34,5 (90,1 na coluna A) | <1% |
| `window_3x3` | 30,4 | <1% |
| `line_window_skid` | 27,3 | <1% |

### 6.3 Detalhamento dos M10Ks

Fonte: `output_files/sobel_multicycle.fit.rpt`.

| Instância | Depth × Width | Total bits | M10Ks | Nota do fitter |
|---|---|---|---|---|
| `line_buffer_2line\|mem1_rtl_0` | 640 × 9 | 5.760 | 1 | "No - Address Too Wide" |
| `skid_fifo2\|skid_mem_r_rtl_0` | 2 × 72 | 144 | 2 | "No - Unsupported Port Usage" |

**Observação:** `mem2` do `line_buffer_2line` **não** virou M10K nem MLAB organizada; foi espalhada em dezenas de `MLABCELL_*` individuais. Motivo reportado: `Info (276007): RAM logic "line_buffer_2line:u_line_buffer|mem2" is uninferred due to asynchronous read logic`.

### 6.4 Timing

Fonte: `output_files/sobel_multicycle.sta.rpt`.

| Corner | Fmax | Slack | End Point TNS |
|---|---|---|---|
| Slow 1100mV 85°C | 98,05 MHz | **-0,199 ns** | -0,199 |
| Slow 1100mV 0°C | 97,55 MHz | -0,251 ns | -0,251 |
| Fast 1100mV 85°C | — | +4,025 ns | 0,000 |

**Hold (slow 1100mV 85°C):** slack +0,234 ns.
**Minimum pulse width (slow 1100mV 85°C):** slack +3,851 ns.

### 6.5 Caminho crítico

Fonte: `critical_path_summary.rpt`.

| Slack | From Node | To Node | Data Delay |
|---|---|---|---|
| -0,199 ns | `col_feed_r[3]` | `line_window_skid:u_lw_skid\|mem~27` | 9,934 ns |
| -0,184 ns | `col_feed_r[3]` | `line_window_skid:u_lw_skid\|mem~27` | 9,919 ns |
| -0,166 ns | (idem) | (idem) | 9,901 ns |
| -0,163 ns | (idem) | (idem) | 9,898 ns |
| -0,085 ns | (idem) | (idem) | 9,820 ns |
| -0,080 ns | (idem) | (idem) | 9,815 ns |
| -0,045 ns | (idem) | (idem) | 9,780 ns |
| -0,033 ns | (idem) | (idem) | 9,768 ns |
| -0,014 ns | (idem) | (idem) | 9,749 ns |
| -0,001 ns | (idem) | (idem) | 9,736 ns |

**Todos os 10 caminhos têm o mesmo `From` e `To`.** Isso caracteriza um **único caminho dominante** no design.

### 6.6 Warnings e infos relevantes

Do `.map.rpt`:

| Código | Severidade | Descrição |
|---|---|---|
| 276020 | Warning | `skid_fifo2\|skid_mem_r_rtl_0` inferida com pass-through logic |
| 276027 | Warning | `mem1` inferida como RAM dual-clock |
| 276004 | Info | `line_window_skid\|mem` não inferida por tamanho inadequado |
| 276007 | Info | `line_buffer_2line\|mem2` não inferida por leitura assíncrona |

---

## 7. Análise técnica e conclusões

### 7.1 O que foi demonstrado

- **A arquitetura Multiciclo é sintetizável** e cabe no dispositivo com folga (14% dos ALMs).
- **A decisão de 0 DSPs foi respeitada** pelo sintetizador — o `mac_unit` não foi mapeado para blocos DSP.
- **A arquitetura fecha a ~98 MHz** no corner lento, com violação leve (-0,199 ns) contra o alvo de 100 MHz.
- **O gargalo está isolado** em um único caminho: `col_feed_r[3] → line_window_skid|mem~27`.
- **O SDC foi lido corretamente** — clock `clk` de 10 ns é reconhecido pelo STA.

### 7.2 O que foi parcialmente validado

- **Inferência de memória:** apenas 1 das 2 FIFOs do `line_buffer` virou M10K; a outra (`mem2`) caiu em MLAB por ter leitura assíncrona. A `skid_fifo2` consumiu 2 M10Ks para 144 bits — ineficiente, mas funcional.
- **Comportamento read-during-write:** o Quartus emitiu warning sobre `mem1` como RAM dual-clock. Não foi verificado por simulação se `wr_ptr` e `rd_ptr` podem coincidir no mesmo ciclo.

### 7.3 O que permanece sem validação

- **Correção funcional em hardware.** Sem placa física, o design só foi validado por simulação (Icarus + cocotb) e por síntese. STA não substitui teste funcional em silício.
- **Impacto real da violação de setup.** Em silício, o design pode funcionar a 100 MHz se as condições forem favoráveis, ou falhar de forma intermitente. STA é pior caso.
- **Estimativa de potência.** Não realizada.
- **Caracterização nas arquiteturas Pipeline e Paralela.** RTL não existe.

### 7.4 Limitações da interpretação

- **Números do `.fit.rpt` são pós-fit, não pós-silício.** Refletem o mapeamento do Quartus para o Cyclone V, não o comportamento físico.
- **Os números são específicos do dispositivo `5CSEMA5F31C6`.** Outro part number poderia dar valores diferentes.
- **O `IMG_WIDTH` configurado nos testes influencia tudo.** Os números reportados correspondem à configuração efetiva do RTL no momento da compilação — **[não verificado]** qual valor estava em uso, presumivelmente 4 ou 8 conforme o histórico.

---

## 8. Dúvidas em aberto, limitações e pendências

### 8.1 `line_window_skid` — gargalo arquitetural

- **Descrição:** o caminho crítico passa integralmente pelo `line_window_skid`, com 9,934 ns de delay combinacional entre `col_feed_r[3]` e `mem~27`.
- **Motivo em aberto:** não foi analisado se é possível pipelinar esse caminho sem quebrar o protocolo com o `mac_control_fsm`.
- **Impacto:** limitar o Fmax a 98 MHz no Multiciclo e potencialmente nas outras arquiteturas se herdarem o mesmo bloco.
- **Ação necessária:** análise do `line_window_skid.sv` na conversa de arquitetura/RTL.
- **Critério de resolução:** decisão documentada sobre pipelinar ou aceitar o Fmax atual.

### 8.2 `skid_fifo2` — 2 M10Ks para 144 bits

- **Descrição:** a FIFO de profundidade 2 e largura 72 bits consumiu 2 blocos M10K, quando FFs fariam o mesmo trabalho a custo menor.
- **Motivo em aberto:** não foi testado `(* ramstyle = "logic" *)` no array `skid_mem_r`.
- **Impacto:** desperdício de recursos; os 2 M10Ks poderiam ser usados por outras arquiteturas.
- **Ação necessária:** adicionar o atributo, recompilar, comparar.
- **Critério de resolução:** M10Ks reduzidos de 3 para 1 (ou próximo), com re-simulação passando.

### 8.3 `mem2` do `line_buffer` — leitura assíncrona

- **Descrição:** `mem2` foi para MLAB por ter leitura assíncrona, enquanto `mem1` virou M10K.
- **Motivo em aberto:** não se sabe se a leitura assíncrona é decisão consciente ou acidente.
- **Impacto:** ALMs adicionais; `line_buffer_2line` consome 94% dos ALMs do design.
- **Ação necessária:** revisar RTL; verificar se a leitura registrada altera o comportamento funcional.
- **Critério de resolução:** decisão documentada sobre manter em MLAB ou migrar para M10K.

### 8.4 `mem1` dual-clock — comportamento indefinido

- **Descrição:** o Quartus inferiu `mem1` como RAM dual-clock e advertiu que o comportamento read-during-write é indefinido.
- **Motivo em aberto:** não foi verificado se `wr_ptr` e `rd_ptr` podem coincidir no mesmo ciclo.
- **Impacto:** possível corrupção silenciosa em hardware.
- **Ação necessária:** adicionar assertion em simulação ou revisar o RTL.
- **Critério de resolução:** prova formal (por invariante documentado) ou por simulação exaustiva de que os ponteiros nunca coincidem no mesmo ciclo.

### 8.5 Fmax natural vs. alvo

- **Descrição:** Fmax natural de 98 MHz; alvo SDC de 100 MHz.
- **Motivo em aberto:** não se decidiu se o alvo deve ser mantido ou relaxado.
- **Impacto:** afeta a narrativa do relatório e a comparação com Pipeline/Paralela.
- **Ação necessária:** decisão na conversa de arquitetura.
- **Critério de resolução:** SDC final documentado com justificativa.

### 8.6 Escopo do Multiciclo — RTL fechado?

- **Descrição:** na conversa de arquitetura, o RTL do Multiciclo foi declarado "fechado".
- **Motivo em aberto:** não está claro se as correções acima serão aplicadas ou se os números atuais são finais.
- **Impacto:** define se o relatório vai documentar as ineficiências como características ou se o RTL será refatorado antes.
- **Ação necessária:** decisão na conversa de arquitetura.
- **Critério de resolução:** declaração explícita de "RTL congelado" ou "RTL será refatorado nas seguintes partes".

### 8.7 Estimativa de potência — pendente

- **Descrição:** PowerPlay com VCD não foi executado.
- **Motivo:** requer VCD da simulação cocotb, que precisa ser gerado.
- **Impacto:** sem números de potência para o relatório.
- **Ação necessária:** gerar VCD e rodar `quartus_pow`.
- **Critério de resolução:** `.pow.rpt` produzido e documentado.

### 8.8 Segundo vendor — não iniciado

- **Descrição:** Vivado ML Standard não instalado.
- **Motivo:** decisão consciente de adiar até ter números do Quartus.
- **Impacto:** se o relatório exigir dois vendors, faltará.
- **Ação necessária:** instalar Vivado (~50 GB), reproduzir o fluxo para Artix-7.
- **Critério de resolução:** `.rpt` do Vivado com recursos e timing de Artix-7.

---

## 9. Próximos passos

### 9.1 Imediatos (desbloqueiam os demais)

1. **Levar achados para a conversa de arquitetura.**
   - Evidência: `critical_path_summary.rpt`, `.fit.rpt`, `.sta.rpt`.
   - Decisão esperada: refatorar ou congelar.

2. **Decidir sobre `ramstyle = "logic"` na `skid_fifo2`.**
   - Objetivo: eliminar 2 M10Ks desperdiçados.
   - Resultado esperado: M10Ks reduzidos.

3. **Decidir sobre o SDC final.**
   - Opção A: manter 100 MHz e documentar a violação como característica.
   - Opção B: relaxar para 90 MHz e reportar margem positiva.

### 9.2 Aprofundamento da caracterização

4. **Gerar VCD via cocotb** e rodar `quartus_pow`.
   - Objetivo: número de potência estimada.
   - Resultado esperado: `.pow.rpt`.

5. **Instalar Vivado ML e reproduzir fluxo para Artix-7.**
   - Objetivo: segundo conjunto de números.
   - Resultado esperado: `.rpt` de utilização e timing.

### 9.3 Avanço do projeto

6. **Preparar RTL da arquitetura Pipeline.**
   - Ainda não iniciado (documentos de planejamento existem, RTL não).
   - Fora do escopo desta conversa.

7. **Repetir caracterização para Pipeline e Paralela.**
   - Quando o RTL existir, o fluxo Quartus é o mesmo: novo `setup_proj_<arq>.tcl`, novo `<arq>.sdc`, nova execução.

### 9.4 Estabilização do ambiente

8. **Documentar o `.gitignore` do projeto.**
   - Incluir `db/`, `incremental_db/`, `output_files/`, `*.qpf`, `*.qsf`.

9. **Registrar versões exatas.**
   - `quartus_sh --version`, `docker --version`, versão exata do Ubuntu.
   - Atualmente há lacunas ("[não verificado]").

---

## 10. Reprodutibilidade e manutenção

### 10.1 Pré-requisitos

- Docker instalado no host.
- VS Code com extensão Dev Containers.
- ~30 GB de espaço livre para o volume `quartus-install`.
- Conexão de rede dentro do container (para download durante instalação do Quartus).

### 10.2 Preparar o ambiente do zero

**No host:**

1. Configurar `devcontainer.json` com o mount do volume.
2. Configurar `Dockerfile` com dependências de 32 bits e `ENV PATH`.
3. Rebuild Container (`Ctrl+Shift+P` → "Dev Containers: Rebuild Container Without Cache").

**Dentro do container:**

1. Baixar o instalador SFX **pelo navegador do host** (o `wget` direto dá 403).
2. Mover para dentro do container via pasta do projeto.
3. `./qinst-lite-linux-25.1std-1129.run --target /tmp/qinst --noexec`
4. `cd /tmp/qinst && ./qinst.sh --cli --help`
5. `./qinst.sh --cli --components quartus,cyclonev --install-dir /opt/intelFPGA_lite/25.1std --delete-downloads --accept-eula`
6. Verificar: `which quartus_sh quartus_map quartus_fit quartus_sta`

### 10.3 Executar o fluxo

**Dentro do container, a partir de `/workspaces/ic-sobel-hw-fpga`:**

```bash
# Criar/recriar o projeto
quartus_sh -t constraints/setup_proj.tcl

# Compilar
quartus_sh --flow compile sobel_multicycle

# Extrair caminho crítico
quartus_sta sobel_multicycle --do_report_timing

# Opcional: extrair 10 piores caminhos detalhados
quartus_sta -t critical_path.tcl
```

### 10.4 Localização dos relatórios

| Relatório | Caminho |
|---|---|
| Recursos | `output_files/sobel_multicycle.fit.rpt` |
| Timing | `output_files/sobel_multicycle.sta.rpt` |
| Caminho crítico (resumo) | `critical_path_summary.rpt` |
| Caminho crítico (detalhado) | `critical_path_full.rpt` |

### 10.5 Verificações após execução

1. `grep -i "ALMs needed\|DSP\|M10K" output_files/sobel_multicycle.fit.rpt` — checar recursos.
2. `grep -B1 -A5 "^; Clock Name" output_files/sobel_multicycle.sta.rpt | head -20` — checar clock reconhecido.
3. `grep -A 10 "Fmax Summary" output_files/sobel_multicycle.sta.rpt` — checar Fmax.
4. `cat critical_path_summary.rpt | head -20` — checar caminho crítico.

### 10.6 Limitações conhecidas

- **Comparações entre execuções:** o Fmax depende do corner. Comparar sempre no mesmo corner (slow 1100mV 85°C é o padrão do Quartus).
- **Dependência de versão:** o `.qsf` pode não ser compatível entre versões maiores do Quartus. Se atualizar, regenerar via `setup_proj.tcl`.
- **Dispositivo alvo:** números são específicos do `5CSEMA5F31C6`. Trocar o part number exige recompilação.
- **`wget` direto da Altera:** não funciona; sempre baixar pelo navegador.

### 10.7 Estado atual

**Último estágio comprovadamente concluído:** caracterização de síntese e timing da arquitetura Multiciclo no Quartus Prime Lite 25.1std.

**Resumo numérico:**
- 4.601 ALMs (14%), 6.270 FFs, 0 DSPs, 3 M10Ks.
- Fmax natural de 98,05 MHz no corner slow 1100mV 85°C.
- Slack de -0,199 ns contra alvo de 100 MHz.
- Caminho crítico isolado em `col_feed_r[3] → line_window_skid|mem~27`.

**Principais pendências:**
1. Decisão sobre refatorar `line_window_skid` (único ganho de Fmax).
2. Decisão sobre `ramstyle = "logic"` na `skid_fifo2` (ganho de área).
3. Verificação do comportamento read-during-write de `mem1`.
4. Estimativa de potência.
5. Caracterização das arquiteturas Pipeline e Paralela (RTL inexistente).
6. Segundo vendor (Vivado) — opcional.