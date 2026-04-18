#!/bin/bash
set -xe

# === Atualiza pacotes e instala ferramentas de SystemVerilog ===
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    curl git gtkwave iverilog verilator universal-ctags \
    make build-essential python3-pip jq wget ripgrep \
    dbus-x11

# Node.js já vem via feature, mas garantimos
npm --version

# === Instala cocotb (já tínhamos) ===
pip3 install --break-system-packages cocotb cocotb-test pytest

# === Instala OpenClaude CLI (global) ===
npm install -g @gitlawb/openclaude

# === Instala Verible (mais recente) ===
ARCH=$(uname -m)
if [[ $ARCH == "aarch64" ]]; then ARCH="arm64"; fi
VERIBLE_RELEASE=$(curl -s https://api.github.com/repos/chipsalliance/verible/releases/latest | jq -r '.tag_name')
VERIBLE_TAR="verible-${VERIBLE_RELEASE}-linux-static-${ARCH}.tar.gz"
wget -q "https://github.com/chipsalliance/verible/releases/download/${VERIBLE_RELEASE}/${VERIBLE_TAR}"
tar -C /usr/local --strip-components=1 -xf $VERIBLE_TAR
rm -f $VERIBLE_TAR

echo "✅ OpenClaude + SystemVerilog instalado com sucesso!"
echo "   Comandos úteis:"
echo "     openclaude                  → Inicia o agente interativo"
echo "     openclaude --help           → Lista todos os comandos"
echo "     make help                   → Comandos do projeto"