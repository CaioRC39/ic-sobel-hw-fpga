"""Spike de viabilidade (Fase 4, F-04/A-08): cocotb + Verilator com --coverage.

NAO faz parte da suite (nome sem prefixo test_; `make cocotb` nao coleta).
NAO altera RTL nem testes existentes: reaproveita test_magnitude_l1.py e
test_mac_unit.py SEM modificacao, so trocando o simulador.

Perguntas que o spike responde (criterio de saida):
  (i)   os testes existentes passam sem alteracao sob Verilator?
  (ii)  o coverage.dat e gerado e legivel (parser proprio + verilator_coverage)?
  (iii) quantos testes exigem adaptacao? (cada falha de pytest = 1 resposta)
  (iv)  o operador ?: gera ponto de cobertura por braco? (test_spike_02)

Uso (a partir de tb_python/):
  SIM=verilator python3 -m pytest spike_verilator_cov.py -v -s

Backend alternativo (contingencia, runner nativo do cocotb):
  SIM=verilator SPIKE_BACKEND=runner python3 -m pytest spike_verilator_cov.py -v -s
"""

import importlib.metadata
import os
import re
import shutil
import subprocess
from collections import defaultdict

import pytest

from _cocotb_helpers import run_isolated

TB_DIR = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(TB_DIR)
INC = os.path.join(PROJ, "include")
SPIKE_DIR = os.path.join(PROJ, "sim", "spike_cov")


def _src(*parts):
    return os.path.join(PROJ, *parts)


# testcases=None => roda TODAS as corrotinas @cocotb.test() do modulo
# (magnitude_l1: 4; mac_unit: 9 - as mesmas dos runners oficiais).
CASES = {
    "magnitude_l1": {
        "toplevel": "magnitude_l1",
        "module": "test_magnitude_l1",
        "sources": [_src("rtl", "common", "magnitude_l1.sv")],
        "parameters": {"DATA_WIDTH": 8},
    },
    "mac_unit": {
        "toplevel": "mac_unit",
        "module": "test_mac_unit",
        "sources": [_src("rtl", "multicycle", "mac_unit.sv")],
        "parameters": {"DATA_WIDTH": 8, "COEFF_WIDTH": 3, "ACC_WIDTH": 11},
    },
}

COV_COMPILE_ARGS = ["--coverage", "-Wall"]  # sem -g2012: e flag do Icarus, nao do Verilator


# ----------------------------------------------------------------------
# execucao
# ----------------------------------------------------------------------
def _run_native(case, testcases, build, cov):
    try:
        from cocotb_tools.runner import get_runner  # cocotb >= 2.0
    except ImportError:
        from cocotb.runner import get_runner  # cocotb 1.x

    runner = get_runner("verilator")
    runner.build(
        verilog_sources=case["sources"],
        includes=[INC],
        hdl_toplevel=case["toplevel"],
        parameters=case["parameters"],
        build_args=COV_COMPILE_ARGS,
        build_dir=build,
        always=True,
    )
    runner.test(
        hdl_toplevel=case["toplevel"],
        test_module=case["module"],
        testcase=testcases,  # str separada por virgula, ou None
        build_dir=build,
        plusargs=[f"+verilator+coverage+file+{cov}"],
    )


def _find_dat(build, cov):
    if os.path.isfile(cov):
        return cov
    found = []
    for root in (build, TB_DIR, os.path.join(PROJ, "sim")):
        for dirpath, _dirs, files in os.walk(root):
            if "coverage.dat" in files:
                found.append(os.path.join(dirpath, "coverage.dat"))
    assert found, (
        "coverage.dat NAO encontrado (nem em sim_build, nem em tb_python/, nem em sim/): "
        "a simulacao rodou, mas o plusarg de arquivo nao foi honrado e o default tambem "
        "nao caiu onde procuramos - reportar isto"
    )
    found.sort(key=os.path.getmtime)
    print(f"[spike] AVISO: usando coverage.dat fora do caminho pedido: {found[-1]}")
    return found[-1]


def _run(case_name, tag, testcases=None):
    assert os.environ.get("SIM") == "verilator", (
        "rode com SIM=verilator (sem isso o spike nao mede nada)"
    )
    case = CASES[case_name]
    build = os.path.join(SPIKE_DIR, tag)
    shutil.rmtree(build, ignore_errors=True)  # evita 'Skipping compilation'
    cov = os.path.join(build, "coverage.dat")

    backend = os.environ.get("SPIKE_BACKEND", "cocotb_test")
    if backend == "runner":
        _run_native(case, testcases, build, cov)
    else:
        run_isolated(
            testcases,
            verilog_sources=case["sources"],
            includes=[INC],
            toplevel=case["toplevel"],
            module=case["module"],
            parameters=case["parameters"],
            compile_args=COV_COMPILE_ARGS,
            sim_build=build,
            plus_args=[f"+verilator+coverage+file+{cov}"],
        )
    return build, _find_dat(build, cov)


# ----------------------------------------------------------------------
# leitura do coverage.dat (formato Verilator: C '<k>\x02<v>\x01...' <contagem>)
# ----------------------------------------------------------------------
_REC = re.compile(r"^C '(.*)' (\d+)\s*$")


def _parse_dat(path):
    pts = []
    with open(path, errors="replace") as f:
        for ln in f:
            m = _REC.match(ln.rstrip("\n"))
            if not m:
                continue
            kv = {}
            for part in m.group(1).split("\x01"):
                if "\x02" in part:
                    k, v = part.split("\x02", 1)
                    kv[k] = v
            pts.append({"kv": kv, "count": int(m.group(2))})
    return pts


def _kind(p):
    return p["kv"].get("page", "?").split("/")[0]  # v_line, v_toggle, v_user...


def _report(label, build, dat):
    pts = _parse_dat(dat)
    tot = defaultdict(lambda: [0, 0])
    for p in pts:
        tot[_kind(p)][0] += 1
        tot[_kind(p)][1] += 1 if p["count"] > 0 else 0

    print(f"\n=== SPIKE {label}: {len(pts)} pontos em {dat} ===")
    for kind, (n, hit) in sorted(tot.items()):
        pct = 100.0 * hit / n if n else 0.0
        print(f"  {kind:10s} cobertos {hit}/{n} ({pct:.1f}%)")

    n_line = sum(1 for p in pts if _kind(p) == "v_line")
    print(f"  pontos v_line existentes: {n_line}"
          + ("  (AVISO: nenhum - '0 nao cobertos' de linha seria vacuo)" if n_line == 0 else ""))
    miss = [p for p in pts
            if _kind(p) in ("v_line", "v_branch", "v_expr", "v_toggle") and p["count"] == 0]
    print(f"  pontos line/branch/expr/toggle nao cobertos: {len(miss)}")
    for p in miss[:40]:
        kv = p["kv"]
        print(f"    {_kind(p)} {os.path.basename(kv.get('f', '?'))}:{kv.get('l', '?')} "
              f"col={kv.get('n', '?')} detalhe={kv.get('o', '')!r}")

    exe = shutil.which("verilator_coverage")
    if exe is None:
        print("  verilator_coverage: AUSENTE no PATH (relatorio oficial nao verificado)")
    else:
        r = subprocess.run(
            [exe, "--annotate", os.path.join(build, "annotated"), "--annotate-min", "1", dat],
            capture_output=True, text=True,
        )
        print(f"  verilator_coverage rc={r.returncode}")
        for line in (r.stdout + r.stderr).strip().splitlines()[-6:]:
            print(f"    | {line}")
    return pts


def _ternary_probe(pts, src_path, needle):
    with open(src_path) as f:
        lines = f.read().splitlines()
    ln = next((i + 1 for i, s in enumerate(lines) if needle in s), None)
    assert ln is not None, f"'{needle}' nao encontrado em {src_path}"
    base = os.path.basename(src_path)
    on_line = [p for p in pts
               if os.path.basename(p["kv"].get("f", "")) == base
               and int(p["kv"].get("l", "0") or 0) == ln]
    print(f"\n=== TESTE DO TERNARIO: {base}:{ln} -> {lines[ln - 1].strip()} ===")
    print(f"  pontos de cobertura nesta linha: {len(on_line)}")
    for p in on_line:
        kv = {k: v for k, v in p["kv"].items() if k != "f"}
        print(f"    contagem={p['count']} {kv}")
    br = [p for p in on_line if p["kv"].get("t") == "branch"]
    arms = {p["kv"].get("o") for p in br}
    if len(br) < 2 or len(arms) < 2:
        print(f"  VEREDITO: {len(br)} ponto(s) branch - ?: NAO distingue os dois bracos")
    else:
        zero = [p["kv"].get("o") for p in br if p["count"] == 0]
        print(f"  ESTRUTURA: {len(br)} pontos branch, bracos distintos {sorted(arms)}")
        if zero:
            print(f"  VEREDITO: CONFIRMADO - braco(s) {zero} com contagem 0 e visiveis")
        else:
            print("  VEREDITO: estrutura ok (1 ponto por braco); falta o caso com braco a zero "
                  "(rodar test_spike_02)")


# ----------------------------------------------------------------------
# testes do spike
# ----------------------------------------------------------------------
def test_spike_00_versions():
    out = {}
    for exe, args in (("verilator", ["--version"]), ("iverilog", ["-V"])):
        path = shutil.which(exe)
        if path is None:
            out[exe] = "AUSENTE"
            continue
        r = subprocess.run([path] + args, capture_output=True, text=True)
        out[exe] = (r.stdout or r.stderr).strip().splitlines()[0]
        out[exe + " (caminho)"] = path
    vpath = shutil.which("verilator")
    if vpath is not None:
        r = subprocess.run([vpath, "--getenv", "VERILATOR_ROOT"], capture_output=True, text=True)
        out["VERILATOR_ROOT"] = r.stdout.strip()
    for pkg in ("cocotb", "cocotb-test", "pytest"):
        try:
            out[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            out[pkg] = "AUSENTE"
    out["verilator_coverage"] = shutil.which("verilator_coverage") or "AUSENTE"
    print("\n=== VERSOES ===")
    for k, v in out.items():
        print(f"  {k}: {v}")

    assert out["verilator"] != "AUSENTE", "verilator nao esta no PATH"
    m = re.search(r"Verilator\s+(\d+)\.(\d+)", out["verilator"])
    if m and (int(m.group(1)), int(m.group(2))) < (5, 36):
        print("  AVISO: Verilator < 5.036. Pelo que lembro, o cocotb 2.0 exige >= 5.036 "
              "(NAO verificado - conferir na documentacao do cocotb). Se os testes "
              "abaixo falharem ja na compilacao, esta e a causa mais provavel.")


def test_spike_01_magnitude_full():
    build, dat = _run("magnitude_l1", "magnitude_full")
    pts = _report("magnitude_l1 (suite completa, 4 corrotinas)", build, dat)
    _ternary_probe(pts, CASES["magnitude_l1"]["sources"][0], "o_magnitude =")


def test_spike_02_magnitude_only_nosat():
    """Experimento do ternario: so test_no_saturation (nenhum caso passa de 255)."""
    build, dat = _run("magnitude_l1", "magnitude_nosat", testcases="test_no_saturation")
    pts = _report("magnitude_l1 (SO test_no_saturation)", build, dat)
    _ternary_probe(pts, CASES["magnitude_l1"]["sources"][0], "o_magnitude =")


def test_spike_03_mac_unit_full():
    build, dat = _run("mac_unit", "mac_unit_full")
    _report("mac_unit (suite completa, 9 corrotinas)", build, dat)