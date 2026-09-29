FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# === 1. Ferramentas base + SystemVerilog + LaTeX enxuto ===
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl wget git jq ripgrep ca-certificates gnupg sudo \
        make build-essential universal-ctags \
        gtkwave iverilog verilator \
        python3 python3-pip python3-venv python3-dev \
        texlive-latex-base \
        texlive-latex-recommended \
        texlive-latex-extra \
        texlive-fonts-recommended \
        texlive-lang-portuguese \
        latexmk \
    && rm -rf /var/lib/apt/lists/*

# === 2. Verible (SystemVerilog formatter/linter) ===
RUN ARCH=$(uname -m) \
    && if [ "$ARCH" = "aarch64" ]; then ARCH="arm64"; fi \
    && VERIBLE_RELEASE=$(curl -s https://api.github.com/repos/chipsalliance/verible/releases/latest | jq -r '.tag_name') \
    && VERIBLE_TAR="verible-${VERIBLE_RELEASE}-linux-static-${ARCH}.tar.gz" \
    && wget -q "https://github.com/chipsalliance/verible/releases/download/${VERIBLE_RELEASE}/${VERIBLE_TAR}" \
    && tar -C /usr/local --strip-components=1 -xf "$VERIBLE_TAR" \
    && rm -f "$VERIBLE_TAR" \
    && chmod 755 /usr/local /usr/local/bin \
    && chmod 755 /usr/local/bin/verible-*

# === 3. Dependências Python ===
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --break-system-packages --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# === 4. Verificação (como root, antes de criar o usuário) ===
RUN verilator --version \
    && iverilog -V > /dev/null 2>&1 \
    && verible-verilog-format --version \
    && pdflatex --version | head -n1

# === 5. Cria o usuário vscode (UID/GID 1000, igual ao WSL) ===
RUN userdel -r ubuntu 2>/dev/null || true \
    && groupdel ubuntu 2>/dev/null || true \
    && groupadd --gid 1000 vscode \
    && useradd --uid 1000 --gid 1000 \
       --create-home --shell /bin/bash vscode \
    && echo "vscode ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/vscode \
    && chmod 0440 /etc/sudoers.d/vscode

# === 6. Troca para o usuário vscode ===
USER vscode

# === 7. Verificação como usuário final ===
RUN verible-verilog-format --version \
    && verilator --version \
    && iverilog -V > /dev/null 2>&1 \
    && pdflatex --version | head -n1