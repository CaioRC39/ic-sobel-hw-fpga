import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge
from _cocotb_helpers import run_isolated

DATA_WIDTH = 8
IMG_WIDTH = 6


async def _reset(dut):
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    dut.i_tag.value = 0
    dut.i_rearm.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def _step(dut, valid: int, pixel: int, tag: int = 0, rst_n: int = 1, rearm: int = 0):
    dut.rst_n.value = rst_n
    dut.i_valid.value = valid
    dut.i_pixel.value = pixel
    dut.i_tag.value = tag
    dut.i_rearm.value = rearm
    await RisingEdge(dut.clk)
    await ReadOnly()
    out = {
        "valid": int(dut.o_valid.value),
        "curr": int(dut.o_curr.value),
        "line1": int(dut.o_line1.value),
        "line2": int(dut.o_line2.value),
        "curr_tag": int(dut.o_curr_tag.value),
        "line1_tag": int(dut.o_line1_tag.value),
        "line2_tag": int(dut.o_line2_tag.value),
    }
    await NextTimeStep()
    return out


@cocotb.test()
async def test_reset_state(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    await ReadOnly()
    assert dut.o_curr.value == 0
    assert dut.o_line1.value == 0
    assert dut.o_line2.value == 0
    assert dut.o_curr_tag.value == 0
    assert dut.o_line1_tag.value == 0
    assert dut.o_line2_tag.value == 0
    await NextTimeStep()



@cocotb.test()
async def test_delay_and_zero_padding(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    n_cycles = 5 * IMG_WIDTH
    pixels = [(i * 7 + 3) % 256 for i in range(n_cycles)]

    history = []
    for t, pix in enumerate(pixels):
        out = await _step(dut, valid=1, pixel=pix, tag=0)
        history.append(pix)

        exp_curr = pix
        exp_line1 = history[t - IMG_WIDTH] if t >= IMG_WIDTH else 0
        exp_line2 = history[t - 2 * IMG_WIDTH] if t >= 2 * IMG_WIDTH else 0

        assert out["valid"] == 1
        assert out["curr"] == exp_curr
        assert out["line1"] == exp_line1
        assert out["line2"] == exp_line2


@cocotb.test()
async def test_ignores_invalid_cycles(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)
    random.seed(1234)

    n_real_pixels = 4 * IMG_WIDTH
    history = []
    real_t = 0
    for _ in range(n_real_pixels):
        for _ in range(random.randint(0, 2)):
            out = await _step(dut, valid=0, pixel=0xFF, tag=1)
            assert out["valid"] == 0

        pix = (real_t * 13 + 5) % 256
        out = await _step(dut, valid=1, pixel=pix, tag=0)

        history.append(pix)
        exp_line1 = history[real_t - IMG_WIDTH] if real_t >= IMG_WIDTH else 0
        exp_line2 = history[real_t - 2 * IMG_WIDTH] if real_t >= 2 * IMG_WIDTH else 0

        assert out["valid"] == 1
        assert out["curr"] == pix
        assert out["line1"] == exp_line1
        assert out["line2"] == exp_line2
        real_t += 1


@cocotb.test()
async def test_midstream_reset(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    for t in range(10):
        await _step(dut, valid=1, pixel=50 + t, tag=0)

    for _ in range(3):
        out = await _step(dut, valid=0, pixel=0, tag=0, rst_n=0)
        assert out["curr"] == 0
        assert out["line1"] == 0
        assert out["line2"] == 0
        assert out["curr_tag"] == 0
        assert out["line1_tag"] == 0
        assert out["line2_tag"] == 0

    history = []
    for t in range(4 * IMG_WIDTH):
        out = await _step(dut, valid=1, pixel=200 + t, tag=0, rst_n=1)
        history.append(200 + t)
        exp_line1 = history[t - IMG_WIDTH] if t >= IMG_WIDTH else 0
        exp_line2 = history[t - 2 * IMG_WIDTH] if t >= 2 * IMG_WIDTH else 0
        assert out["curr"] == 200 + t
        assert out["line1"] == exp_line1
        assert out["line2"] == exp_line2


@cocotb.test()
async def test_tag_constant_within_frame_always_matches(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    n_cycles = 6 * IMG_WIDTH
    for t in range(n_cycles):
        out = await _step(dut, valid=1, pixel=(t * 11 + 1) % 256, tag=1)
        assert out["curr_tag"] == 1, f"t={t}"
        assert out["line1_tag"] == 1, f"t={t}"
        assert out["line2_tag"] == 1, f"t={t}"


@cocotb.test()
async def test_tag_lockstep_across_3_frame_boundaries(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    frame_len = 3 * IMG_WIDTH
    frame_tags = [0, 1, 0]
    hist_pix, hist_tag = [], []
    gt = 0

    for tag in frame_tags:
        for _ in range(frame_len):
            pix = (gt * 7 + 3) % 256
            out = await _step(dut, valid=1, pixel=pix, tag=tag)
            hist_pix.append(pix)
            hist_tag.append(tag)

            assert out["curr_tag"] == tag, f"gt={gt}"
            if gt >= IMG_WIDTH:
                assert out["line1_tag"] == hist_tag[gt - IMG_WIDTH], f"gt={gt}"
            if gt >= 2 * IMG_WIDTH:
                assert out["line2_tag"] == hist_tag[gt - 2 * IMG_WIDTH], f"gt={gt}"
            gt += 1


@cocotb.test()
async def test_tag_survives_frame_boundary_in_memory(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    frame1_len = 3 * IMG_WIDTH
    frame2_len = 3 * IMG_WIDTH
    hist_pix, hist_tag = [], []

    for t in range(frame1_len):
        pix = (t * 3 + 1) % 256
        out = await _step(dut, valid=1, pixel=pix, tag=0)
        hist_pix.append(pix)
        hist_tag.append(0)
        assert out["curr_tag"] == 0

    for t in range(frame2_len):
        gt = frame1_len + t
        pix = (t * 5 + 2) % 256
        out = await _step(dut, valid=1, pixel=pix, tag=1)
        hist_pix.append(pix)
        hist_tag.append(1)

        exp_line1_tag = hist_tag[gt - IMG_WIDTH]
        exp_line2_tag = hist_tag[gt - 2 * IMG_WIDTH]

        assert out["curr_tag"] == 1
        assert out["line1_tag"] == exp_line1_tag, f"t(global)={gt}"
        assert out["line2_tag"] == exp_line2_tag, f"t(global)={gt}"


@cocotb.test()
async def test_rearm_prevents_residual_tag_leak(dut):
    """Contraste direto com test_tag_survives_frame_boundary_in_memory
    (que demonstra o vazamento SEM i_rearm): aqui, i_rearm e pulsado no
    1o ciclo de cada frame (mesmo padrao que sobel_multicycle.sv vai
    usar) - o_line1_tag/o_line2_tag NUNCA devem mostrar a tag do frame
    ANTERIOR apos a fronteira; durante os IMG_WIDTH+1/IMG_WIDTH
    primeiros ciclos do novo frame, devem refletir a tag ATUAL (zero-
    padding herdando i_tag, mesmo raciocinio da borda superior do
    frame 1) - nunca o residuo real do frame antigo ainda fisicamente
    presente na memoria circular."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    frame1_len = 3 * IMG_WIDTH
    frame2_len = 3 * IMG_WIDTH

    for t in range(frame1_len):
        pix = (t * 3 + 1) % 256
        await _step(dut, valid=1, pixel=pix, tag=0, rearm=(t == 0))

    for t in range(frame2_len):
        pix = (t * 5 + 2) % 256
        out = await _step(dut, valid=1, pixel=pix, tag=1, rearm=(t == 0))

        assert out["curr_tag"] == 1, f"t(frame2)={t}"
        assert out["line1_tag"] == 1, (
            f"t(frame2)={t}: com i_rearm, line1_tag NUNCA deveria mostrar "
            f"a tag do frame anterior (0) - obtido={out['line1_tag']}"
        )
        assert out["line2_tag"] == 1, (
            f"t(frame2)={t}: com i_rearm, line2_tag NUNCA deveria mostrar "
            f"a tag do frame anterior (0) - obtido={out['line2_tag']}"
        )


@cocotb.test()
async def test_read_before_write_on_wrap(dut):
    """Documenta e verifica a dependência de read-before-write em mem1.

    O RTL usa o padrão clássico de FIFO circular: no mesmo ciclo, lê
    mem1[wr_ptr1_r] (valor antigo, gravado IMG_WIDTH ciclos atrás) e
    sobrescreve mem1[wr_ptr1_r] com o pixel atual. Em simulação, isso é
    garantido pela semântica de atribuição não-bloqueante do
    SystemVerilog; em hardware, depende de o BRAM ser configurado em
    modo read-first. O Quartus reportou a inferência de mem1 como RAM
    dual-clock com read-during-write indefinido (warning 276027) — se
    a síntese futura mudar para write-first, este módulo produzirá
    saída errada em hardware, sem falhar em simulação. Este teste é o
    registro explícito dessa dependência, e falharia se o RTL algum dia
    fosse refatorado de forma a violar a semântica read-before-write.

    Este teste NÃO adiciona cobertura nova em relação a
    test_delay_and_zero_padding (que já valida o mesmo comportamento de
    forma implícita) — seu valor é documental: nomeia a propriedade,
    explica por que ela importa, e roda por 3 voltas completas do
    ponteiro (não apenas 1)."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    # Valores únicos, nunca repetidos, para que antigo e novo sejam
    # sempre distinguíveis: 100, 101, 102, ...
    n_cycles = 3 * IMG_WIDTH + 5
    pixels = [100 + i for i in range(n_cycles)]

    history = []
    n_checked = 0
    for t, pix in enumerate(pixels):
        out = await _step(dut, valid=1, pixel=pix, tag=0)
        history.append(pix)

        # A propriedade só é observável quando warm1 já é verdadeiro —
        # antes disso, o zero-padding (não read-before-write) é quem
        # determina o_line1. WarmThresh = IMG_WIDTH + 1 (ver RTL); a
        # primeira leitura válida aparece exatamente em t = IMG_WIDTH.
        if t >= IMG_WIDTH:
            exp_line1 = history[t - IMG_WIDTH]
            assert out["line1"] == exp_line1, (
                f"t={t}: o_line1={out['line1']} esperado={exp_line1}. "
                f"Se falha em simulação, a semântica read-before-write "
                f"está quebrada no RTL; se passa aqui mas o hardware "
                f"falhar, o BRAM foi sintetizado em write-first (ver "
                f"comentário de contrato em line_buffer_2line.sv)."
            )
            n_checked += 1

    dut.i_valid.value = 0
    await RisingEdge(dut.clk)

    # Cobertura mínima: 2 voltas completas do ponteiro já garantem
    # colisão entre leitura e escrita em todos os endereços.
    assert n_checked >= 2 * IMG_WIDTH, (
        f"n_checked={n_checked}: cobertura insuficiente para garantir "
        f"colisão de leitura/escrita em todos os endereços "
        f"(esperado >= {2 * IMG_WIDTH})"
    )


@cocotb.test()
async def test_slot_extra_preserves_delay(dut):
    """Valida que a correcao da slot extra em mem1 nao alterou o delay funcional.

    O RTL agora usa profundidade IMG_WIDTH+1 em mem1 e le de wr_ptr1_next
    (endereco seguinte ao escrito) em vez de wr_ptr1_r. Essa correcao elimina
    a colisao same-cycle same-address por construcao, mas DEVE preservar o
    delay de IMG_WIDTH ciclos entre i_pixel e o_line1.

    Este teste roda ciclos suficientes para cobrir pelo menos 2 wraps
    completos do ponteiro, garantindo que a leitura do endereco "seguinte"
    nao introduz salto de 1 ciclo na volta do buffer circular.
    """
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await _reset(dut)

    # Cobre pelo menos 2 wraps da profundidade (IMG_WIDTH + 1)
    n_cycles = 4 * (IMG_WIDTH + 1) + 2
    pixels = [(i * 19 + 7) % 256 for i in range(n_cycles)]

    history = []
    for t, pix in enumerate(pixels):
        out = await _step(dut, valid=1, pixel=pix, tag=0)
        history.append(pix)

        if t >= IMG_WIDTH:
            exp_line1 = history[t - IMG_WIDTH]
            assert out["line1"] == exp_line1, (
                f"t={t}: o_line1={out['line1']} esperado={exp_line1}. "
                f"Se falha aqui, a correcao da slot extra mudou o delay; "
                f"se passa, o delay de IMG_WIDTH foi preservado."
            )

    # Cobertura minima: pelo menos 2 wraps completos
    assert n_cycles >= 2 * (IMG_WIDTH + 1), (
        f"n_cycles={n_cycles} insuficiente para cobrir 2 wraps de "
        f"profundidade {IMG_WIDTH + 1}"
    )


def test_line_buffer_2line_runner():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_build = os.path.join(proj_root, "sim", "sim_build_line_buffer_2line")

    run_isolated(
        "test_reset_state,test_delay_and_zero_padding,test_ignores_invalid_cycles,"
        "test_midstream_reset,test_tag_constant_within_frame_always_matches,"
        "test_tag_lockstep_across_3_frame_boundaries,"
        "test_tag_survives_frame_boundary_in_memory,"
        "test_rearm_prevents_residual_tag_leak,"
        "test_read_before_write_on_wrap,"
        "test_slot_extra_preserves_delay",
        verilog_sources=[
            os.path.join(proj_root, "rtl", "common", "line_buffer_2line.sv"),
        ],
        includes=[os.path.join(proj_root, "include")],
        toplevel="line_buffer_2line",
        module="test_line_buffer_2line",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": IMG_WIDTH},
        compile_args=["-g2012", "-Wall"],
        sim_build=sim_build,
    )

if __name__ == "__main__":
    test_line_buffer_2line_runner()