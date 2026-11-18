"""Modelo (Camada 1, dominio de PULSOS) da hipotese window_3x3_stream.

Ver RESUMO_ESTADO_PROJETO_POS_MULTICICLO.md, secao 13. NAO e RTL, NAO modela
ciclos de clock: so "qual janela sai em qual pulso". Um pulso = um ciclo com
i_valid=1.

Contrato assumido de line_buffer_2line (ja validado por test_delay_and_zero_padding
e test_line_buffer_depth): no pulso n, curr=pix[n], line1=pix[n-W], line2=pix[n-2W].
Antes de haver historico o modelo entrega LIXO ALEATORIO (nao zero) de proposito:
se o resultado final nao depende dele, o aquecimento e o i_rearm ficam redundantes.

Hipotese testada: shift-registers nunca reiniciados + 4 mascaras por posicao do
CENTRO (rc, cc):
    cc == 0    -> zera coluna esquerda (antiga)
    cc == W-1  -> zera coluna direita (nova)
    rc == 0    -> zera linha de cima (line2)
    rc == H-1  -> zera linha de baixo (curr)
O centro e um contador modulo W*H, defasado em W+1 pulsos da chegada.
Inicial: pos = (-(W+1)) mod W*H; `started` sobe quando pos==0 (pulso W+1).

Semantica de fim de stream (decisao B): `started` pegajoso, restart() explicito,
descarga de W+1 pulsos. Alternativa registrada, NAO implementada: nunca descarregar
(a cauda do frame k sairia durante o frame k+1; ultimo frame nunca completa).

W>=2 (W=1 nao e suportado pelo projeto). H>=1.
"""
import random
from collections import deque


class WindowStream:
    def __init__(self, w, h, seed=0, mask_left=True, mask_right=True,
                 mask_top=True, mask_bottom=True, init_shift=0, start_mode="pos0"):
        assert w >= 2 and h >= 1
        self.w, self.h, self.n_pos = w, h, w * h
        self.mask_left, self.mask_right = mask_left, mask_right
        self.mask_top, self.mask_bottom = mask_top, mask_bottom
        self.init_shift = init_shift  # so para mutantes (deslocamento de latencia)
        assert start_mode in ("pos0", "counter")
        self.start_mode = start_mode
        self._rng = random.Random(seed)
        n = 2 * w + 1
        self.buf = deque((self._poison() for _ in range(n)), maxlen=n)
        # sr[0]=coluna mais nova (direita), sr[2]=mais antiga (esquerda); cada coluna = (l2, l1, curr)
        self.sr = [tuple(self._poison() for _ in range(3)) for _ in range(3)]
        self.restart()

    def _poison(self):
        return self._rng.randint(1, 255)

    def poison_pixel(self):
        return self._poison()

    def restart(self):
        """Re-arma so contadores e `started` (historico e shift-registers ficam)."""
        self.pos = (self.n_pos - self.w - 1 + self.init_shift) % self.n_pos
        self.started = False
        self.warm = 0

    def step(self, pixel):
        """1 pulso de entrada. Devolve (valid_out, janela 3x3 [linha][coluna])."""
        w, h = self.w, self.h
        self.buf.append(pixel)
        curr = self.buf[-1]
        line1 = self.buf[-1 - w]
        line2 = self.buf[-1 - 2 * w]
        self.sr = [(line2, line1, curr)] + self.sr[:2]
        rc, cc = divmod(self.pos, w)
        if self.start_mode == "pos0":
            if self.pos == 0:
                self.started = True
        else:  # "counter": independe de W*H (vale para H=1)
            if self.warm >= w + 1:
                self.started = True
            else:
                self.warm += 1
        cols = [list(self.sr[2]), list(self.sr[1]), list(self.sr[0])]  # esq, meio, dir
        if self.mask_left and cc == 0:
            cols[0] = [0, 0, 0]
        if self.mask_right and cc == w - 1:
            cols[2] = [0, 0, 0]
        if self.mask_top and rc == 0:
            for c in cols:
                c[0] = 0
        if self.mask_bottom and rc == h - 1:
            for c in cols:
                c[2] = 0
        win = [[cols[j][i] for j in range(3)] for i in range(3)]
        self.pos = (self.pos + 1) % self.n_pos
        return self.started, win


def run_stream(model, pixels):
    """Alimenta uma lista de pixels (1 por pulso). Devolve (valids, windows_validas)."""
    valids, wins = [], []
    for p in pixels:
        v, win = model.step(p)
        valids.append(v)
        if v:
            wins.append(win)
    return valids, wins
