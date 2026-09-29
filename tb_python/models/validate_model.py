import sys
sys.path.insert(0, "/home/claude/diag/models")
from pipeline_identity_model import (
    predict_window_stream, sample_stream, expected_real_window_count,
    expected_raw_window_count, predicted_spurious_per_frame, LogicalPos
)

# -----------------------------------------------------------------------
# Validacao 1: caso de 1 frame, contra a MESMA formula de referencia ja
# usada e validada em test_win_reg_direct.py
# (_build_reference_windows_with_bottom_padding) - reimplementada aqui
# so para comparacao (fonte de verdade independente).
# -----------------------------------------------------------------------
def reference_1frame(img_width, img_height):
    """Copia literal de _build_reference_windows_with_bottom_padding
    (test_win_reg_direct.py), mas devolvendo so (row,col) de saida em
    vez do conteudo pixel, para comparar so a GEOMETRIA/ORDEM."""
    out = []
    for r in range(img_height):
        for col in range(img_width):
            out.append((r, col))
    return out

for W, H in [(4, 3), (6, 3), (8, 3), (5, 4)]:
    events = predict_window_stream(W, H, n_frames=1)
    real_positions = [(e[1].row, e[1].col) for e in events if e[0]]
    expected = reference_1frame(W, H)
    ok = real_positions == expected
    n_spurious = sum(1 for e in events if not e[0])
    print(f"W={W} H={H}: posicoes reais batem com referencia? {ok}  "
          f"(n_real={len(real_positions)} esperado={len(expected)}, n_spurious={n_spurious} esperado={W})")
    assert ok, f"FALHA: geometria nao bate para W={W} H={H}"
    assert n_spurious == W, f"FALHA: espurias={n_spurious} esperado={W}"

print("\n=== Validacao 1 (1 frame vs referencia ja validada do projeto): TODAS PASSARAM ===\n")

# -----------------------------------------------------------------------
# Validacao 2: aplica a hipotese multi-frame aos dados REAIS ja colados
# nesta conversa (Teste C, POS-Alternativa-A, W=4 H=3, 4 frames):
#   frame  win_valid  win_valid_real  win_tag!=frame_tag_r
#   1      16          12              3
#   2      16          13              3
#   3      16          13              3
#   4      14          11              0
# -----------------------------------------------------------------------
W, H, N = 4, 3, 4
events = predict_window_stream(W, H, n_frames=N)
raw_total = len(events)
real_total = sum(1 for e in events if e[0])
spurious_per_frame_predicted = predicted_spurious_per_frame(W, N)

print("=== Validacao 2: aplicando a hipotese aos dados reais ja coletados ===")
print(f"total de janelas RAW previsto pelo modelo (4 frames): {raw_total} "
      f"(esperado W*(H+1)*N = {expected_raw_window_count(W,H,N)})")
print(f"total de janelas REAIS previsto pelo modelo: {real_total} "
      f"(esperado W*H*N = {expected_real_window_count(W,H,N)})")
print(f"espurias previstas por frame (hipotese - TODO frame, nao so o 1o): "
      f"{spurious_per_frame_predicted}")

print("\n--- comparacao direta com os dados reais colados (Teste C, pos-Alternativa-A) ---")
real_win_valid = [16, 16, 16, 14]
real_win_valid_real = [12, 13, 13, 11]
print("  frame  win_valid(real,medido)  win_valid_real(real,medido)  "
      "win_valid(modelo=W*(H+1))  espurias_previstas(hipotese)")
for i in range(4):
    modelo_raw = W * (H + 1)
    print(f"  {i+1:5d}  {real_win_valid[i]:23d}  {real_win_valid_real[i]:28d}  "
          f"{modelo_raw:25d}  {spurious_per_frame_predicted[i]:29d}")

print("\n--- diagnostico ---")
for i in range(4):
    medido_filtrado = real_win_valid[i] - real_win_valid_real[i]
    previsto_pela_hipotese = spurious_per_frame_predicted[i]
    print(f"  frame {i+1}: filtrado de fato (medido) = {medido_filtrado}  "
          f"vs previsto pela hipotese (deveria filtrar) = {previsto_pela_hipotese}  "
          f"{'-> CONSISTENTE (frame 1, discard_cnt_r original)' if i == 0 and medido_filtrado == previsto_pela_hipotese else ''}"
          f"{'-> DEFICIT DE 1 (Alternativa A filtrou 3, deveria ser 4)' if i in (1,2) and medido_filtrado == previsto_pela_hipotese - 1 else ''}")
