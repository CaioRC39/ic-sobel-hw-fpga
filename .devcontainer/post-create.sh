#!/bin/bash
set -xe

# === Atualiza pacotes e instala ferramentas de SystemVerilog ===
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    curl git gtkwave iverilog verilator universal-ctags \
    make build-essential python3-pip jq wget ripgrep \
    dbus-x11

# === Instala LaTeX completo (essencial para artigo científico) ===
apt-get install -y \
    texlive-full \
    latexmk \
    texlive-lang-portuguese \
    texlive-science \
    texlive-bibtex-extra

# === Instala dependências Python ===
pip3 install --break-system-packages -r requirements.txt

# === Instala Verible (mais recente) ===
ARCH=$(uname -m)
if [[ $ARCH == "aarch64" ]]; then ARCH="arm64"; fi
VERIBLE_RELEASE=$(curl -s https://api.github.com/repos/chipsalliance/verible/releases/latest | jq -r '.tag_name')
VERIBLE_TAR="verible-${VERIBLE_RELEASE}-linux-static-${ARCH}.tar.gz"
wget -q "https://github.com/chipsalliance/verible/releases/download/${VERIBLE_RELEASE}/${VERIBLE_TAR}"
tar -C /usr/local --strip-components=1 -xf $VERIBLE_TAR
rm -f $VERIBLE_TAR

echo "✅ SystemVerilog + LaTeX + Python instalado com sucesso!"
echo "   Comandos úteis:"
echo "     make help                   → Comandos do projeto"
echo "     pdflatex --version          → Verifica LaTeX"
echo "     latexmk -pdf article.tex    → Compila artigo"