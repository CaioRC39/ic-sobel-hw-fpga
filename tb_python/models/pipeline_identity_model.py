"""
Modelo de latencia/identidade do pipeline de sobel_multicycle.sv.
Ver docs/MODELO_LATENCIA_PIPELINE.md para objetivo, premissas,
derivacao completa e status de validacao (confirmado vs hipotese).

CAMADA 1 (ORDEM/IDENTIDADE) - esta e a camada implementada aqui.

Objetivo: dado o stream continuo de amostras que entram em
line_buffer_2line (reais + 1 linha de padding por frame, sem gap entre
frames - mesmo principio de projeto ja documentado para window_3x3.sv),
predizer, PARA CADA janela que window_3x3 emite (ordem global,
continua, w=0,1,2,...), a qual posicao logica de saida ela corresponde
- (frame, linha_saida, coluna) se for uma janela REAL, ou None se for
ESPURIA (nao corresponde a nenhuma saida real esperada).

Este modelo e puramente COMBINATORIO/DE ORDEM - nao modela ciclos de
relogio, backpressure ou stall. Serve para responder "qual janela e
qual", nao "em que ciclo". Ver docs/MODELO_LATENCIA_PIPELINE.md secao
2.2 para a Camada 2 (tempo/ciclos), fora do escopo deste arquivo.

Derivado por leitura de window_3x3.sv e line_buffer_2line.sv (2 fatos
estruturais, citados no cabecalho de predict_window_stream). A parte
de UM UNICO FRAME e validada por CONSTRUCAO contra uma referencia ja
usada e confirmada no projeto (_build_reference_windows_with_bottom_padding,
test_win_reg_direct.py) - ver test_pipeline_identity_model.py.

A parte de MULTIPLOS FRAMES (janela espuria em CADA fronteira, nao so
no frame 0) e HIPOTESE - corroborada por evidencia ja coletada nesta
investigacao (ver docs/MODELO_LATENCIA_PIPELINE.md secao 5), mas NAO
confirmada por execucao direcionada contra o RTL real.
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class LogicalPos:
    """Posicao logica de uma amostra ou de uma janela de saida."""
    frame: int
    row: int
    col: int


def sample_stream(img_width: int, img_height: int, n_frames: int) -> List[LogicalPos]:
    """Stream logico continuo de amostras (frame,row,col) na MESMA
    ordem/quantidade que sobel_multicycle.sv alimenta line_buffer_2line:
    IMG_WIDTH*(IMG_HEIGHT+1) amostras por frame (IMG_HEIGHT linhas reais
    + 1 linha de padding interna, row index == IMG_HEIGHT), sem gap
    entre frames - mesmo stream que window_3x3.sv realmente enxerga
    (nao tem nocao de frame, ver ARQUITETURA_MULTICICLO.md secao 4.2)."""
    out = []
    for f in range(n_frames):
        for row in range(img_height + 1):
            for col in range(img_width):
                out.append(LogicalPos(f, row, col))
    return out


def predict_window_stream(
    img_width: int, img_height: int, n_frames: int
) -> List[Tuple[bool, Optional[LogicalPos]]]:
    """Prediz, em ordem, cada janela que window_3x3 emite.

    Fato estrutural (a): a janela emitida enquanto se alimenta a
    amostra de entrada na linha r esta CENTRADA em i_line1, que vale a
    amostra da linha r-1 (line_buffer_2line.sv, mem1 - atraso de 1
    linha, mesma coluna). Alimentar a linha de ENTRADA r produz janelas
    de SAIDA para a linha r-1.

    Fato estrutural (b): window_3x3 nunca emite janela na 1a coluna de
    uma linha (precisa do vizinho esquerdo, is_first_col forca
    valid_r=0) - as colunas 1..W-1 da linha de entrada produzem W-1
    janelas de saida, para as colunas de saida 0..W-2 respectivamente
    (o CENTRO da janela na coluna de entrada c e a coluna de saida
    c-1). O "ciclo fantasma" da borda direita (1 pulso extra apos a
    ultima coluna real de cada linha) produz a W-esima janela, coluna
    de saida W-1. Total: W janelas de saida por linha de entrada,
    cobrindo as W colunas de saida exatamente 1x cada.

    HIPOTESE (nao confirmada por execucao - ver docs/MODELO_LATENCIA_
    PIPELINE.md secao 5): i_rearm (Alternativa 3-C) forca line1/line2 de
    volta a zero-padding no 1o ciclo de CADA frame, nao so no power-up -
    logo, alimentar a linha 0 de QUALQUER frame produz uma linha de
    saida "-1" (virtual, fora de 0..IMG_HEIGHT-1) - nao so no frame 0.
    Este modelo MARCA essas janelas como espurias (is_real=False) em
    TODO frame, refletindo a GEOMETRIA do RTL tal como lida - o que
    ainda nao esta confirmado e se o mecanismo de descarte do lado do
    integrador (discard_cnt_r/warmup_done_r em sobel_multicycle.sv)
    de fato FILTRA essas janelas em todo frame, ou so no frame 0 (ver
    secao 5 do documento para a analise que motiva a suspeita de que
    NAO filtra).

    Retorna lista de (is_real, LogicalPos-ou-None), 1 entrada por
    janela emitida, na ordem exata de emissao.
    """
    events: List[Tuple[bool, Optional[LogicalPos]]] = []
    for f in range(n_frames):
        for r in range(img_height + 1):
            out_row = r - 1
            is_real_row = 0 <= out_row < img_height
            for c in range(1, img_width):  # colunas 1..W-1 (fato b)
                out_col = c - 1
                events.append(
                    (is_real_row, LogicalPos(f, out_row, out_col) if is_real_row else None)
                )
            # ciclo fantasma da borda direita - coluna de saida W-1
            events.append(
                (is_real_row, LogicalPos(f, out_row, img_width - 1) if is_real_row else None)
            )
    return events


def expected_real_window_count(img_width: int, img_height: int, n_frames: int) -> int:
    """Numero de janelas REAIS esperadas (deveria bater com
    IMG_WIDTH*IMG_HEIGHT*n_frames - o mesmo h*w usado por
    _reference_sobel_l1 em test_sobel_multicycle.py)."""
    return img_width * img_height * n_frames


def expected_raw_window_count(img_width: int, img_height: int, n_frames: int) -> int:
    """Numero TOTAL de janelas emitidas por window_3x3 (reais +
    espurias), incluindo a linha virtual '-1' de CADA frame (hipotese)."""
    return img_width * (img_height + 1) * n_frames


def predicted_spurious_per_frame(img_width: int, n_frames: int) -> List[int]:
    """Sob a hipotese, quantas janelas espurias cada frame contribui -
    deveria ser IMG_WIDTH em TODO frame (nao so no frame 0)."""
    return [img_width for _ in range(n_frames)]
