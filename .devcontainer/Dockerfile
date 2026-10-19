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

# === 2. Dependências de 32 bits para o Quartus ===
RUN dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        g++-multilib \
        libxft2:i386 libncurses6:i386 libxext6:i386 libx11-6:i386 \
        libxau6:i386 libxdmcp6:i386 libbsd0:i386 libmd0:i386 \
        libtinfo6:i386 zlib1g:i386 libpng16-16:i386 libfreetype6:i386 \
        libfontconfig1:i386 libexpat1:i386 libglib2.0-0:i386 \
        libglx0:i386 libgl1:i386 libice6:i386 libsm6:i386 \
        libuuid1:i386 libselinux1:i386 libpcre2-8-0:i386 \
        libattr1:i386 libacl1:i386 libgcc-s1:i386 libstdc++6:i386 \
    && rm -rf /var/lib/apt/lists/*

# === 3. Verible (SystemVerilog formatter/linter) ===
RUN ARCH=$(uname -m) \
    && if [ "$ARCH" = "aarch64" ]; then ARCH="arm64"; fi \
    && VERIBLE_RELEASE=$(curl -s https://api.github.com/repos/chipsalliance/verible/releases/latest | jq -r '.tag_name') \
    && VERIBLE_TAR="verible-${VERIBLE_RELEASE}-linux-static-${ARCH}.tar.gz" \
    && wget -q "https://github.com/chipsalliance/verible/releases/download/${VERIBLE_RELEASE}/${VERIBLE_TAR}" \
    && tar -C /usr/local --strip-components=1 -xf "$VERIBLE_TAR" \
    && rm -f "$VERIBLE_TAR" \
    && chmod 755 /usr/local /usr/local/bin \
    && chmod 755 /usr/local/bin/verible-*

# === 4. Dependências Python ===
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --break-system-packages --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# === 5. Verificação ===
RUN verilator --version \
    && iverilog -V > /dev/null 2>&1 \
    && verible-verilog-format --version \
    && pdflatex --version | head -n1

# === 6. Cria o usuário vscode (UID/GID 1000) ===
RUN userdel -r ubuntu 2>/dev/null || true \
    && groupdel ubuntu 2>/dev/null || true \
    && groupadd --gid 1000 vscode \
    && useradd --uid 1000 --gid 1000 \
       --create-home --shell /bin/bash vscode \
    && echo "vscode ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/vscode \
    && chmod 0440 /etc/sudoers.d/vscode

# === 7. Diretório do volume (será montado sobre este) ===
RUN mkdir -p /opt/intelFPGA_lite \
    && chown vscode:vscode /opt/intelFPGA_lite

# === 8. PATH para o Quartus e Questa (aponta para dentro do volume) ===
# Quartus
ENV PATH=$PATH:/opt/intelFPGA_lite/25.1std/quartus/bin
# Questa
ENV PATH=$PATH:/opt/intelFPGA_lite/25.1std/questa_fse/questa_fse/bin

# === 9. Troca para o usuário vscode ===
USER vscode

# === 10. Verificação final ===
RUN verible-verilog-format --version \
    && verilator --version \
    && iverilog -V > /dev/null 2>&1 \
    && pdflatex --version | head -n1