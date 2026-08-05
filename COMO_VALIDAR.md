# Como validar este trabalho na sua máquina

Este documento explica, passo a passo, como rodar tudo que foi
implementado até agora e conferir com seus próprios olhos que funciona
— sem precisar confiar só na minha palavra.

Ele cobre 4 coisas, nesta ordem:
1. Colocar os arquivos no lugar certo do seu repositório
2. Rodar a suíte completa de testes automatizados
3. Rodar um módulo específico, isolado (útil pra depurar)
4. Checar o estilo de código (lint) e a formatação

No final tem uma "cola" com todos os comandos juntos, pra depois que
você já tiver lido a explicação uma vez.

---

## Passo 0 — Preparar o ambiente

Você tem 2 caminhos. Use o **Caminho A** se puder — é o que o próprio
projeto já prevê, e evita qualquer problema de "faltou instalar algo".

### Caminho A — Dev Container (recomendado)

O repositório já vem com uma receita pronta (`.devcontainer/`) que
instala tudo automaticamente dentro de um container isolado.

1. Abra a pasta do repositório no VS Code.
2. `Ctrl+Shift+P` (ou `Cmd+Shift+P` no Mac) → digite e escolha **"Dev
   Containers: Reopen in Container"**.
3. Espere o container terminar de montar (a primeira vez demora um
   pouco, ele instala tudo do zero — Icarus, Verilator, cocotb,
   Verible, etc).

**Atenção — uma peça está faltando na receita do container:** o
`numpy` (biblioteca Python usada pra gerar as imagens de teste em
`test_window_3x3.py`) não está na lista de instalação automática do
projeto. Depois que o container abrir, rode isto uma vez, direto no
terminal do VS Code (já dentro do container):

```bash
pip3 install --break-system-packages numpy
```

Sem esse comando, o teste do `window_3x3` vai falhar com um erro do
tipo `ModuleNotFoundError: No module named 'numpy'` — não é bug do meu
código, é só essa peça faltando na instalação automática.

### Caminho B — sem Dev Container (ambiente manual)

Se por algum motivo você não for usar o container, precisa instalar
manualmente (Ubuntu/Debian):

```bash
sudo apt-get update
sudo apt-get install -y iverilog gtkwave

pip3 install --break-system-packages cocotb cocotb-test pytest numpy

# Verible (formatação e lint) - não tem pacote apt, precisa baixar o
# binário do GitHub. Uso uma versão fixa aqui (testada e funcionando)
# em vez de "a mais recente", porque a busca dinâmica pela ultima
# versão consulta a API do GitHub, que tem um limite de requisições por
# hora (e pode falhar de forma confusa se você bater nesse limite):
VERIBLE_RELEASE="v0.0-4084-gf3e4d98b"
ARCH=$(uname -m)
curl -sL -o /tmp/verible.tar.gz "https://github.com/chipsalliance/verible/releases/download/${VERIBLE_RELEASE}/verible-${VERIBLE_RELEASE}-linux-static-${ARCH}.tar.gz"
sudo tar -C /usr/local --strip-components=1 -xf /tmp/verible.tar.gz
rm -f /tmp/verible.tar.gz
```

*(Se quiser a versão mais recente de verdade em vez da fixa acima,
veja a lista em <https://github.com/chipsalliance/verible/releases> e
troque o valor de `VERIBLE_RELEASE` manualmente.)*

Pra conferir que tudo ficou instalado:

```bash
iverilog -V              # deve mostrar a versão do Icarus Verilog
python3 -c "import cocotb, cocotb_test, pytest, numpy; print('OK')"
verible-verilog-lint --version
```

Se as 3 linhas rodarem sem erro, está tudo pronto.

---

## Passo 1 — Colocar os arquivos no lugar certo

O arquivo `.zip` que te mandei **não é o repositório inteiro** — é só
os arquivos que criei ou modifiquei. Isso é proposital: eu não tenho
como enviar direto pro seu GitHub, então você precisa copiar esses
arquivos por cima do seu clone local do repositório
`ic-sobel-hw-fpga`.

Extraia o `.zip` em uma pasta separada (ex: `~/Downloads/sobel-etapa`)
e copie cada arquivo pro destino correspondente dentro do seu clone
real do repositório:

| Arquivo no `.zip` | Vai para (dentro do seu clone) | Situação |
|---|---|---|
| `rtl/common/line_buffer_2line.sv` | `rtl/common/line_buffer_2line.sv` | novo |
| `rtl/common/window_3x3.sv` | `rtl/common/window_3x3.sv` | novo |
| `rtl/common/abs_saturate.sv` | `rtl/common/abs_saturate.sv` | novo |
| `rtl/common/magnitude_l1.sv` | `rtl/common/magnitude_l1.sv` | novo |
| `rtl/multicycle/mac_unit.sv` | `rtl/multicycle/mac_unit.sv` | novo |
| `tb_python/test_line_buffer_2line.py` | `tb_python/test_line_buffer_2line.py` | novo |
| `tb_python/test_window_3x3.py` | `tb_python/test_window_3x3.py` | novo |
| `tb_python/test_mac_unit.py` | `tb_python/test_mac_unit.py` | novo |
| `tb_python/test_abs_saturate.py` | `tb_python/test_abs_saturate.py` | novo |
| `tb_python/test_magnitude_l1.py` | `tb_python/test_magnitude_l1.py` | novo |
| `tb_python/_cocotb_helpers.py` | `tb_python/_cocotb_helpers.py` | novo — infraestrutura compartilhada, **não** é um arquivo de teste em si (não aparece como "ponto" no Passo 2) |
| `include/timescale.svh` | `include/timescale.svh` | novo |
| `Makefile` | `Makefile` | **substitui** o que já existe (foram feitos ajustes — ver `git diff` depois) |
| `docs/ARQUITETURA_MULTICICLO.md` | `docs/ARQUITETURA_MULTICICLO.md` | **substitui** o que já existe |
| `COMO_VALIDAR.md` | `COMO_VALIDAR.md` (raiz do repo) | novo — este próprio documento |

Se você estiver num terminal Linux/Mac, dá pra fazer isso tudo de uma
vez (ajuste os caminhos para os seus):

```bash
# exemplo - ajuste ORIGEM e DESTINO para o seu caso
ORIGEM=~/Downloads/sobel-etapa3-abs_saturate-magnitude_l1
DESTINO=~/caminho/para/ic-sobel-hw-fpga

cp -r "$ORIGEM"/rtl/. "$DESTINO"/rtl/
cp -r "$ORIGEM"/tb_python/. "$DESTINO"/tb_python/
cp -r "$ORIGEM"/include/. "$DESTINO"/include/
cp "$ORIGEM"/Makefile "$DESTINO"/Makefile
cp "$ORIGEM"/docs/ARQUITETURA_MULTICICLO.md "$DESTINO"/docs/ARQUITETURA_MULTICICLO.md
```

Depois de copiar, um bom jeito de conferir o que mudou de verdade é
rodar `git status` e `git diff` dentro do repositório — o Git vai te
mostrar exatamente as diferenças, arquivo por arquivo.

---

## Passo 2 — Rodar a suíte completa de testes

Com os arquivos no lugar e o terminal aberto **na raiz do
repositório** (a pasta onde está o `Makefile`), rode:

```bash
make cocotb
```

### O que esperar ver (saída de sucesso)

```
mkdir -p sim
Rodando testes cocotb (SIM=icarus) ...
cd tb_python && SIM=icarus python3 -m pytest -q
........                                                                 [100%]
8 passed in X.XXs
```

Cada ponto (`.`) representa uma **função** de teste que passou por
completo (cada arquivo `test_*.py` roda várias verificações internas —
o ponto só aparece depois que TODAS elas passam dentro daquela
função). Hoje são 8, vindas de 5 arquivos:

| Arquivo | Funções de teste (pontos) |
|---|---|
| `test_line_buffer_2line.py` | 1 |
| `test_window_3x3.py` | 3 (a normal + a violação de contrato única + a violação sustentada, isoladas de propósito — ver documentação) |
| `test_mac_unit.py` | 1 |
| `test_abs_saturate.py` | 2 (a normal + o caso extremo de complemento de 2, também isolados) |
| `test_magnitude_l1.py` | 1 |

O número `X.XXs` é só o tempo que levou — varia de máquina pra
máquina, não importa. Esse número de "pontos" só tende a crescer
conforme mais módulos forem adicionados — não se preocupe se, numa
versão futura deste projeto, aparecer um número diferente de 8; o que
importa é `N passed` sem nenhum `failed`.

**Se aparecer `FAILED` em vez de `passed`**, o pytest imprime, logo
acima, exatamente qual verificação falhou e com qual valor — me manda
essa saída (ou investiga junto, se preferir) antes de seguir.

---

## Passo 3 — Rodar um módulo específico, isolado

Às vezes você vai querer rodar só 1 arquivo de teste (mais rápido, e
mais fácil de ler a saída). A partir da pasta `tb_python/`:

```bash
cd tb_python

# roda so o line_buffer_2line
python3 -m pytest test_line_buffer_2line.py -v

# roda so o window_3x3
python3 -m pytest test_window_3x3.py -v

# roda so o mac_unit
python3 -m pytest test_mac_unit.py -v

# roda so o abs_saturate
python3 -m pytest test_abs_saturate.py -v

# roda so o magnitude_l1
python3 -m pytest test_magnitude_l1.py -v
```

O `-v` (*verbose*) faz o pytest listar cada função de teste
individualmente, em vez de só mostrar um ponto por arquivo. Saída
esperada para o `mac_unit`, por exemplo:

```
test_mac_unit.py::test_mac_unit_runner PASSED
```

Se você quiser ver o que aconteceu **dentro** da simulação (os prints
de `dut._log.info(...)`, os nomes de cada corrotina `@cocotb.test()`
individual, etc), rode o arquivo diretamente como script Python em vez
de via pytest:

```bash
python3 test_mac_unit.py
```

Isso mostra o log completo do cocotb, incluindo uma tabela no final
tipo:

```
** TESTS=8 PASS=8 FAIL=0 SKIP=0 **
```

---

## Passo 4 — Checar o estilo de código (lint) e a formatação

Essas duas checagens não testam o *comportamento* do circuito (isso já
é o que o `make cocotb` faz) — elas conferem se o código está escrito
de acordo com as convenções do projeto (`CLAUDE.md`).

### Lint (procura por problemas de estilo/risco)

```bash
verible-verilog-lint rtl/common/*.sv rtl/multicycle/*.sv
```

**Sucesso = nenhuma saída.** Se o comando não imprimir nada e voltar
pro prompt normalmente, está tudo certo. Se houver algo pra corrigir,
ele lista arquivo, linha e a regra violada.

### Formatação (arruma espaçamento/indentação automaticamente)

```bash
make format
```

Esse comando **reescreve os arquivos automaticamente** para o padrão
de formatação do projeto (Verible). É seguro rodar quantas vezes
quiser — se já estiver tudo formatado, ele não muda nada. Se você
editar algum dos meus arquivos manualmente depois, vale rodar esse
comando de novo antes de conferir o lint.

---

## Solução de problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `ModuleNotFoundError: No module named 'numpy'` | numpy não instalado (ver Passo 0) | `pip3 install --break-system-packages numpy` |
| `iverilog: not found` / `vvp: not found` | Icarus Verilog não instalado, ou não está no Dev Container | Conferir Passo 0 (Caminho A ou B) |
| `verible-verilog-lint: not found` | Verible não instalado | Conferir Passo 0 |
| Baixar o Verible falha, ou o `.tar.gz` vem corrompido/muito pequeno (poucos bytes) | Limite de requisições da API do GitHub atingido (comum se muita gente na mesma rede consultar a API sem autenticação) | O comando do Caminho A/B já usa uma versão fixa por causa disso; se mesmo assim falhar, espere alguns minutos e tente de novo, ou baixe manualmente pelo link em <https://github.com/chipsalliance/verible/releases> |
| Erro mencionando `SIM` durante `make cocotb` | Você está usando um Makefile antigo, sem a correção que fizemos (ver seção sobre o Makefile na conversa) | Confirme que copiou o `Makefile` do `.zip` por cima do antigo |
| Teste passa isolado (Passo 3) mas falha dentro de `make cocotb`, ou vice-versa | Deveria comportar-se igual nos dois casos — se isso acontecer, é uma pista de bug real, me avisa | — |
| Quer ver mais detalhe de uma falha | `-q` (usado no `make cocotb`) esconde a saída de testes que passam | Rode o arquivo específico com `-v` (Passo 3), ou até mais detalhado com `-v --tb=long` |

---

## Cola rápida (depois de já ter lido tudo acima uma vez)

```bash
# instalar numpy (so 1a vez, se estiver faltando)
pip3 install --break-system-packages numpy

# rodar tudo
make cocotb

# rodar 1 modulo isolado, com mais detalhe
cd tb_python && python3 -m pytest test_mac_unit.py -v

# ver o log completo de 1 modulo (todas as corrotinas @cocotb.test())
cd tb_python && python3 test_mac_unit.py

# lint (sucesso = sem saida nenhuma)
verible-verilog-lint rtl/common/*.sv rtl/multicycle/*.sv

# formatacao automatica
make format
```
