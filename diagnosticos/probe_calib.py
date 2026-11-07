"""Sonda de calibracao (Frente 2, etapa 4.6). NAO faz parte da suite normal
(nome probe_*, rodar explicitamente, depois arquivar em diagnosticos/). NAO altera RTL.

Objetivo: medir, para W=640, quantos ciclos/s cada simulador entrega sob cocotb com o
MESMO driver (_feed_image_and_collect, ja validado) e o MESMO callback on_cycle que o
teste de frame completo (4.7) vai usar (le o_status a cada ciclo). Com isso se projeta
o tempo de 640x480 por extrapolacao linear (premissa a conferir, nao fato).

Modos (escolhidos por variavel de ambiente, NAO por parametro):
  icarus          SIM=icarus   (padrao)
  verilator       SIM=verilator                         (sem --coverage)
  verilator+cov   SIM=verilator COV_MODE=1              (com --coverage; o .dat vai
                                                         para uma pasta TEMPORARIA, nunca
                                                         para sim/cov_data)

Casos (H = linhas por frame; frames = quadros back-to-back na mesma simulacao):
  (3,1) e (6,1): dao a inclinacao (ciclos por pixel) e eliminam o termo fixo.
  (3,4)        : 4 frames de 640x3 - exercita fronteira de frame/rearm/win_cnt_r em W=640
                 a custo baixo (~160 mil ciclos), e confere a linearidade com os outros.

Cada caso imprime 2 linhas, que e o que deve ser colado de volta:
  CALIB_SIM   (dentro da simulacao: ciclos, tempo SO de simulacao, ciclos/s, o_status)
  CALIB_TOTAL (fora: tempo total = build + simulacao; build ~ total - sim_wall_s)

A massa de teste e de baixo contraste (pixels em [0,12], |Gx|+|Gy| <= 96 < 255), com
guarda anti-saturacao. Alem de medir, a sonda confere saida == golden e o_status == 000.

Como rodar (a partir de tb_python/, com -s para ver os prints):
  SIM=icarus   python3 -m pytest probe_calib.py -v -s
  SIM=verilator python3 -m pytest probe_calib.py -v -s
  COV_MODE=1 SIM=verilator python3 -m pytest probe_calib.py -v -s
Para 1 caso so (ids: 3-1, 6-1, 3-4):  ... probe_calib.py -v -s -k "3-1"
Largura alternativa (so para teste rapido do script): CALIB_W=16 ...
O sim_build e apagado antes de cada caso (build medido de verdade; sem cache obsoleto).
"""

import os
import shutil
import time

import numpy as np
import pytest

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from _cocotb_helpers import run_isolated
from test_sobel_multicycle import _feed_image_and_collect, _reference_sobel_l1

DATA_WIDTH, COEFF_WIDTH, ACC_WIDTH = 8, 3, 11
CLK_NS = 10


def _images(w, h, n):
    # baixo contraste real: pixels em [0,12] => |Gx|+|Gy| <= 96 < 255
    return [((np.arange(h * w) * (3 + f) + f * 7) % 13).reshape(h, w) for f in range(n)]


def _mode():
    if os.environ.get("COV_MODE") == "1":
        return "verilator+cov"
    return "verilator" if os.environ.get("SIM") == "verilator" else "icarus"


@cocotb.test()
async def calib_probe(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    dut.rst_n.value = 0
    dut.i_valid.value = 0
    dut.i_pixel.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    w = int(os.environ["TEST_IMG_WIDTH"])
    h = int(os.environ["TEST_IMG_HEIGHT"])
    nfr = int(os.environ.get("CALIB_FRAMES", "1"))

    images = _images(w, h, nfr)
    expected = [p for im in images for p in _reference_sobel_l1(im)]
    n_sat = sum(1 for v in expected if v == 255)
    assert n_sat == 0, f"massa saturou ({n_sat}/{len(expected)}): teste invalido"

    acc = {"cycles": 0, "status": 0}

    def on_cycle(cyc, i_valid, i_pixel):
        acc["cycles"] = cyc + 1
        acc["status"] |= int(dut.o_status.value)

    t0 = time.perf_counter()
    collected = await _feed_image_and_collect(
        dut, np.vstack(images), stall_prob=0.0, seed=0, on_cycle=on_cycle)
    dt = time.perf_counter() - t0

    ok = collected == expected
    cyc = acc["cycles"]
    print(f"\nCALIB_SIM mode={_mode()} W={w} H={h} frames={nfr} px={len(expected)} "
          f"cycles={cyc} sim_wall_s={dt:.2f} cyc_per_s={cyc / dt:.0f} "
          f"cyc_per_px={cyc / len(expected):.2f} o_status={acc['status']:03b} golden_ok={ok}",
          flush=True)

    assert len(collected) == len(expected), f"len(collected)={len(collected)} != {len(expected)}"
    assert ok, "saida diverge do golden"
    assert acc["status"] == 0, f"o_status={acc['status']:03b} (esperado 000)"


@pytest.mark.parametrize("h,frames", [(3, 1), (6, 1), (3, 4)], ids=lambda v: str(v))
def test_calib_runner(h, frames, tmp_path, monkeypatch):
    w = int(os.environ.get("CALIB_W", "640"))
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mode = _mode()
    if mode == "verilator+cov":
        monkeypatch.setenv("COV_DATA_DIR", str(tmp_path))  # nao poluir sim/cov_data
    tag = {"icarus": "ic", "verilator": "vl", "verilator+cov": "vlcov"}[mode]
    sim_build = os.path.join(root, "sim", f"sim_build_calib_{tag}_w{w}_h{h}")
    for d in (sim_build, sim_build + "_cov"):
        shutil.rmtree(d, ignore_errors=True)

    # -g2012/-Wall sao flags do Icarus; no modo cobertura o gancho os remove sozinho.
    compile_args = ["-Wno-fatal"] if mode == "verilator" else ["-g2012", "-Wall"]

    t0 = time.perf_counter()
    run_isolated(
        "calib_probe",
        verilog_sources=[os.path.join(root, "rtl", d, f) for d, f in [
            ("common", "line_buffer_2line.sv"), ("common", "window_3x3.sv"),
            ("common", "line_window_skid.sv"), ("common", "abs_saturate.sv"),
            ("common", "magnitude_l1.sv"), ("multicycle", "mac_unit.sv"),
            ("multicycle", "kernel_rom.sv"), ("multicycle", "mac_control_fsm.sv"),
            ("multicycle", "skid_fifo2.sv"), ("multicycle", "sobel_multicycle.sv")]],
        includes=[os.path.join(root, "include")],
        toplevel="sobel_multicycle",
        module="probe_calib",
        parameters={"DATA_WIDTH": DATA_WIDTH, "IMG_WIDTH": w, "IMG_HEIGHT": h,
                    "COEFF_WIDTH": COEFF_WIDTH, "ACC_WIDTH": ACC_WIDTH},
        compile_args=compile_args,
        sim_build=sim_build,
        extra_env={"TEST_IMG_WIDTH": str(w), "TEST_IMG_HEIGHT": str(h),
                   "CALIB_FRAMES": str(frames)},
    )
    total = time.perf_counter() - t0
    print(f"CALIB_TOTAL mode={mode} W={w} H={h} frames={frames} total_wall_s={total:.1f} "
          f"(build + simulacao + partida)", flush=True)
