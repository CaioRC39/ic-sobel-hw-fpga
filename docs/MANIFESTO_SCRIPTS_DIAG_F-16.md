# Manifesto — Scripts de diagnóstico da sessão F-16 (2026-08-29)

Todos os scripts abaixo foram executados de verdade em um ambiente de
reprodução isolado (Icarus 12.0 + cocotb 2.0.1 + pytest, reconstruído a
partir dos arquivos do Project Knowledge nesta sessão de chat — **não**
é o repositório real do usuário). Seguem o mesmo padrão já usado no
projeto para instrumentação diagnóstica (`test_sobel_multicycle_trace.py`,
`test_lb_valid_in_minimal_trace.py`): **não fazem parte da suíte
normal** (`make cocotb`), servem só para este diagnóstico pontual.

Como o CLAUDE.md do próprio projeto exige (§15.9, §15.11.2), registro
aqui **honestamente** quais scripts continham bugs na própria
instrumentação (não no RTL) e foram corrigidos ou descartados durante
a sessão — para que ninguém reuse a versão errada por engano.

## Rodar

```bash
cd tb_python
rm -rf ../sim/sim_build_<nome>
python3 -m pytest test_<nome>.py -v -s -o log_cli=true --log-cli-level=INFO
```

## Status por arquivo

| Arquivo | Status | Papel na conclusão final |
|---|---|---|
| `test_single_frame_low_contrast.py` | ✅ Confiável, decisivo | Prova que o bug existe em 1 frame isolado, sem fronteira (10/12 errado) |
| `test_win_reg_direct.py` | ✅ Confiável, decisivo | Cross-check `win_reg`→saída real: 0 divergências. Isola a causa em "como a janela é montada" |
| `test_lb_isolated_burst_pattern.py` | ✅ Confiável (versão final) | `line_buffer_2line` isolado, com o padrão real de pacing: 0 divergências. **Atenção:** a 1ª versão deste script tinha um bug de timing próprio (faltava `await RisingEdge` antes de ler a saída) que produzia 8 falsos-positivos — corrigido dentro do próprio arquivo, com o bug documentado no cabeçalho/comentários |
| `test_extract_gap_pattern.py` | ✅ Confiável | Extrai a sequência real de gaps entre pulsos via detecção de mudança de `wr_ptr1_r` (registrador, não fio combinacional) |
| `test_pair_with_real_gap_pattern.py` | ✅ Confiável, decisivo | Par isolado `line_buffer_2line`+`window_3x3`, sem `sobel_multicycle`: reproduz o defeito de forma limpa |
| `test_pair_fix.py` | ✅ Confiável — resultado NEGATIVO importante | Testa `WarmThresh=IMG_WIDTH`: falha por vazamento de X. Correção tentada e revertida, registrada para não ser repetida |
| `test_single_frame_window_content.py` | ✅ Confiável | Primeira captura de conteúdo de janela mostrando o padrão "1 valor a menos" em `i_line1` |
| `test_raw_content_dump.py` | ✅ Confiável | Dump de conteúdo bruto ao longo dos 4 frames, usado para comparação estrutural |
| `test_colcnt_sequence_trace.py` | ⚠️ Dados corretos, interpretação inicial abandonada | Mediu corretamente a contagem de pulsos por frame (16,12,14,16), mas a hipótese formada a partir disso (relacionada a 3-B/3-C) foi posteriormente invalidada por `test_single_frame_low_contrast` |
| `test_compare_boundaries.py` | ⚠️ Dados corretos, interpretação inicial abandonada | Comparou as 3 fronteiras de frame; parte da linha de investigação sobre tags/rearm que se mostrou não ser a causa raiz real |
| `test_tag_at_boundary_trace.py` | ⚠️ Dados corretos, interpretação inicial abandonada | Mesma observação acima — usado para formar a hipótese (descartada) de que 3-C mascarava a tag que 3-B deveria usar |
| `test_lb_output_unconditional.py` | ⚠️ Parcialmente confuso | Primeira tentativa de traço incondicional; revelou uma inconsistência que levou à descoberta de que a leitura de sinais combinacionais (`lb_valid_in`) é sensível ao ponto de amostragem — lição aplicada nos scripts seguintes |
| `test_content_vs_continuous.py` | ❌ Bug de indexação próprio — **não usar** | A referência de janela "stream contínuo" construída à mão continha um erro de indexação (mostrava ~100% de mismatch mesmo dentro do frame 1, que a suíte oficial já valida como correto). Mantido aqui só por transparência/histórico, não corrobora nada |

## Conclusão que sobrevive a esse processo de eliminação

Independente das 4 tentativas com bug de instrumentação própria (linhas
com ⚠️/❌ acima), a conclusão final é sustentada por **3 fontes
independentes e confiáveis**: `test_single_frame_low_contrast.py`,
`test_win_reg_direct.py`, e `test_pair_with_real_gap_pattern.py`
(mais o resultado negativo de `test_pair_fix.py`, que refina a causa
raiz mostrando que a correção óbvia não é trivial).
