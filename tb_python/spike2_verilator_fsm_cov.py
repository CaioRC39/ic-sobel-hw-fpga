"""Spike 2 (Fase 4): cobertura de FSM sob Verilator, com mac_control_fsm.

NAO faz parte da suite (nome sem prefixo test_). NAO altera RTL nem testes:
reaproveita test_mac_control_fsm.py e test_fsm_state_arc_coverage.py como estao.

Perguntas (criterio de saida):
  (a) fsm_state / fsm_arc saem com total > 0 com `--coverage` puro?
      Se nao, existe flag no `verilator --help` que os habilite? (descoberta
      automatica; nenhum nome de flag e assumido)
  (b) os totais batem com 16 estados / 17 arcos do teste funcional?
  (c) a mesclagem (`verilator_coverage -write`) funciona e SOMA os pontos?
  (d) como o Verilator se comporta com $error (formato da mensagem; a
      simulacao continua apos o 1o $error?) - o executor de violacao exercita isso.

Uso (a partir de tb_python/, com o PATH do Verilator 5.052 ativo):
  SIM=verilator python3 -m pytest spike2_verilator_fsm_cov.py -v -s
"""

import logging
import os
import re
import shutil
import subprocess
from collections import defaultdict
from contextlib import contextmanager

from _cocotb_helpers import run_isolated
from spike_verilator_cov import COV_COMPILE_ARGS, INC, PROJ, _find_dat, _kind, _parse_dat, _src

FSM_DIR = os.path.join(PROJ, "sim", "spike_cov_fsm")
EXPECTED_STATES, EXPECTED_ARCS = 16, 17

FSM_SOURCES = [
    _src("rtl", "common", "abs_saturate.sv"),
    _src("rtl", "common", "magnitude_l1.sv"),
    _src("rtl", "multicycle", "mac_unit.sv"),
    _src("rtl", "multicycle", "kernel_rom.sv"),
    _src("rtl", "multicycle", "mac_control_fsm.sv"),
]
FSM_PARAMS = {"DATA_WIDTH": 8, "COEFF_WIDTH": 3, "ACC_WIDTH": 11}

# (nome, modulo de teste, testcases, expect_errors do Icarus, tolerar divergencia da guarda)
RUNS = [
    ("normal", "test_mac_control_fsm",
     "test_reset_state,test_cycle_timing,test_o_ready_low_while_busy,test_various_windows",
     0, False),
    ("fsmcov", "test_fsm_state_arc_coverage", "test_fsm_state_arc_coverage", 0, False),
    ("violacao", "test_mac_control_fsm", "test_contract_violation_detected", 4, True),
]


# ----------------------------------------------------------------------
# infraestrutura
# ----------------------------------------------------------------------
class _Tap(logging.Handler):
    """Observa o logger 'cocotb' do processo pytest (por onde passa a saida do
    simulador). Conta linhas 'ERROR:' (formato do Icarus, usado pela guarda
    P15) e linhas '%Error'/'Assertion failed' (formato esperado do Verilator,
    HIPOTESE) - para descobrir qual formato o Verilator usa de fato."""

    def __init__(self):
        super().__init__(level=logging.INFO)
        self.n_upper = 0
        self.n_vl = 0
        self.samples = []

    def emit(self, record):
        msg = record.getMessage()
        if "ERROR:" in msg:
            self.n_upper += 1
        if "%Error" in msg or "Assertion failed" in msg:
            self.n_vl += 1
            if len(self.samples) < 4:
                self.samples.append(msg.strip()[:220])


@contextmanager
def _tap():
    t = _Tap()
    lg = logging.getLogger("cocotb")
    lg.addHandler(t)
    try:
        yield t
    finally:
        lg.removeHandler(t)


def _run_fsm(tag, module, testcases, expect_errors=0, extra_flags=(), tolerate_guard=False):
    assert os.environ.get("SIM") == "verilator", "rode com SIM=verilator"
    build = os.path.join(FSM_DIR, tag)
    shutil.rmtree(build, ignore_errors=True)  # evita 'Skipping compilation'
    cov = os.path.join(build, "coverage.dat")
    guard_diverged = False
    with _tap() as tap:
        try:
            run_isolated(
                testcases,
                expect_errors=expect_errors,
                verilog_sources=FSM_SOURCES,
                includes=[INC],
                toplevel="mac_control_fsm",
                module=module,
                parameters=FSM_PARAMS,
                compile_args=list(COV_COMPILE_ARGS) + list(extra_flags),
                sim_build=build,
                plus_args=[f"+verilator+coverage+file+{cov}"],
            )
        except AssertionError as e:
            # So tolera a guarda de $error (formato/contagem diferente no Verilator);
            # qualquer outra falha de simulacao continua sendo falha.
            if not (tolerate_guard and "Guarda de $error" in str(e)):
                raise
            guard_diverged = True
    return {"build": build, "dat": _find_dat(build, cov), "tap": tap, "guard_diverged": guard_diverged}


def _totals(pts):
    tot = defaultdict(lambda: [0, 0])
    for p in pts:
        tot[_kind(p)][0] += 1
        tot[_kind(p)][1] += 1 if p["count"] > 0 else 0
    return tot


def _fmt_totals(pts):
    tot = _totals(pts)
    return "  ".join(f"{k}={h}/{n}" for k, (n, h) in sorted(tot.items())) or "(vazio)"


def _official(dat, outdir):
    exe = shutil.which("verilator_coverage")
    assert exe, "verilator_coverage ausente no PATH"
    shutil.rmtree(outdir, ignore_errors=True)
    r = subprocess.run([exe, "--annotate", outdir, dat], capture_output=True, text=True)
    lines = []
    for ln in (r.stdout + r.stderr).splitlines():
        if ln.startswith("Annotation Summary"):
            break
        lines.append(ln)
    return r.returncode, lines


def _fsm_points(pts):
    return [p for p in pts if "fsm" in _kind(p).lower()]


def _fsm_report(label, pts):
    fsm = _fsm_points(pts)
    st = [p for p in fsm if "state" in _kind(p).lower()]
    ar = [p for p in fsm if "arc" in _kind(p).lower()]
    hit = lambda L: sum(1 for p in L if p["count"] > 0)  # noqa: E731
    print(f"  [{label}] FSM: estados {hit(st)}/{len(st)}  arcos {hit(ar)}/{len(ar)}"
          f"   (funcional espera {EXPECTED_STATES}/{EXPECTED_ARCS})")
    return st, ar


def _fsm_detail(pts, limit=80):
    fsm = _fsm_points(pts)
    print(f"  pontos FSM no .dat: {len(fsm)}; hierarquias: "
          f"{sorted({p['kv'].get('h', '?') for p in fsm})}")
    for p in fsm[:limit]:
        kv = p["kv"]
        print(f"    {_kind(p):12s} contagem={p['count']:<6d} l={kv.get('l', '?')} "
              f"o={kv.get('o', '')!r}")
    if len(fsm) > limit:
        print(f"    ... (+{len(fsm) - limit} pontos omitidos)")


def _key(p):
    return tuple(sorted(p["kv"].items()))


# ----------------------------------------------------------------------
# testes do spike
# ----------------------------------------------------------------------
def test_spike2_00_help_fsm():
    exe = shutil.which("verilator")
    assert exe, "verilator nao esta no PATH"
    r = subprocess.run([exe, "--help"], capture_output=True, text=True)
    text = r.stdout + r.stderr
    print(f"\n=== verilator: {exe} ===")
    fsm_lines = [ln for ln in text.splitlines() if "fsm" in ln.lower()]
    cov_lines = [ln for ln in text.splitlines() if "coverage" in ln.lower()]
    print(f"--- linhas do --help com 'fsm' ({len(fsm_lines)}) ---")
    for ln in fsm_lines:
        print("  " + ln.rstrip())
    print(f"--- linhas do --help com 'coverage' ({len(cov_lines)}) ---")
    for ln in cov_lines:
        print("  " + ln.rstrip())
    if not fsm_lines:
        print("  AVISO: nenhuma linha com 'fsm' no --help: ou nao ha flag dedicada, ou o "
              "--help nao a documenta. NAO e prova de que FSM nao e suportada.")


def test_spike2_01_fsm_runs_and_merge():
    results, failures = {}, []
    for name, module, testcases, exp_err, tol in RUNS:
        try:
            results[name] = _run_fsm(f"run_{name}", module, testcases, exp_err, tolerate_guard=tol)
        except KeyboardInterrupt:
            raise
        except BaseException as e:  # inclui SystemExit (cocotb-test sai com sys.exit)
            failures.append((name, f"{type(e).__name__}: {str(e)[:400]}"))

    print("\n=== EXECUCOES ===")
    for name, *_ in RUNS:
        if name in results:
            r = results[name]
            t = r["tap"]
            print(f"  {name:9s} OK  guarda_divergiu={r['guard_diverged']}  "
                  f"linhas 'ERROR:'={t.n_upper}  linhas '%Error/Assertion'={t.n_vl}")
            for s in t.samples:
                print(f"      amostra: {s}")
        else:
            print(f"  {name:9s} FALHOU")
    for name, msg in failures:
        print(f"  [FALHA {name}] {msg}")

    assert results, "nenhuma execucao produziu coverage.dat"

    print("\n=== COBERTURA POR EXECUCAO ===")
    parsed = {}
    for name, r in results.items():
        pts = _parse_dat(r["dat"])
        parsed[name] = pts
        rc, lines = _official(r["dat"], os.path.join(r["build"], "annotated"))
        print(f"--- {name}: {len(pts)} pontos; verilator_coverage rc={rc}")
        print(f"    {_fmt_totals(pts)}")
        _fsm_report(name, pts)
        for ln in lines:
            print(f"    | {ln}")

    if len(results) >= 2:
        merged = os.path.join(FSM_DIR, "merged.dat")
        exe = shutil.which("verilator_coverage")
        r = subprocess.run([exe, "-write", merged] + [x["dat"] for x in results.values()],
                           capture_output=True, text=True)
        print(f"\n=== MESCLAGEM: rc={r.returncode} ===")
        assert r.returncode == 0 and os.path.isfile(merged), (r.stdout + r.stderr)[-600:]

        mpts = _parse_dat(merged)
        # soma ponto a ponto das execucoes individuais vs. o mesclado
        summed = defaultdict(int)
        for pts in parsed.values():
            for p in pts:
                summed[_key(p)] += p["count"]
        mdict = {_key(p): p["count"] for p in mpts}
        only_sum = set(summed) - set(mdict)
        only_mrg = set(mdict) - set(summed)
        diff = [k for k in set(summed) & set(mdict) if summed[k] != mdict[k]]
        print(f"  pontos: soma={len(summed)} mesclado={len(mdict)}  so_na_soma={len(only_sum)} "
              f"so_no_mesclado={len(only_mrg)}  contagens_diferentes={len(diff)}")
        print("  VEREDITO MESCLAGEM: " + (
            "SOMA CONFIRMADA (mesclado == soma ponto a ponto)"
            if not (only_sum or only_mrg or diff) else
            "DIVERGE - colar este bloco; nao assumir que a mesclagem soma"))

        rc, lines = _official(merged, os.path.join(FSM_DIR, "annotated_merged"))
        print(f"\n=== MESCLADO ({len(mpts)} pontos) ===  verilator_coverage rc={rc}")
        print(f"    {_fmt_totals(mpts)}")
        for ln in lines:
            print(f"    | {ln}")

        print("\n=== FSM NO MESCLADO ===")
        st, ar = _fsm_report("mesclado", mpts)
        _fsm_detail(mpts)
        if st or ar:
            ok = (len(st) == EXPECTED_STATES and len(ar) == EXPECTED_ARCS)
            print("  COMPARACAO COM O TESTE FUNCIONAL: " + (
                "BATE (16 estados / 17 arcos)" if ok else
                f"DIFERE ({len(st)} estados / {len(ar)} arcos) - investigar a diferenca "
                "sem presumir qual lado esta certo"))
        else:
            print("  FSM: 0 pontos com --coverage puro (ver test_spike2_02 para flags)")

        miss = [p for p in mpts if _kind(p) in ("v_line", "v_branch", "v_expr") and p["count"] == 0]
        print(f"\n=== NAO COBERTOS no mesclado (line/branch/expr): {len(miss)} ===")
        for p in miss[:60]:
            kv = p["kv"]
            print(f"    {_kind(p)} {os.path.basename(kv.get('f', '?'))}:{kv.get('l', '?')} "
                  f"h={kv.get('h', '?')} detalhe={kv.get('o', '')!r}")
        tz = defaultdict(list)
        for p in mpts:
            if _kind(p) == "v_toggle" and p["count"] == 0:
                tz[p["kv"].get("h", "?")].append(p["kv"].get("o", ""))
        print(f"\n=== TOGGLE com contagem 0 no mesclado, por hierarquia ===")
        for h, items in sorted(tz.items()):
            print(f"  {h}: {len(items)} ponto(s)")
            for o in sorted(items)[:25]:
                print(f"      {o}")

    unexpected = [n for n, _ in failures if n != "violacao"]
    assert not unexpected, f"execucoes que falharam: {unexpected}"


def test_spike2_02_fsm_flag_candidates():
    exe = shutil.which("verilator")
    r = subprocess.run([exe, "--help"], capture_output=True, text=True)
    text = r.stdout + r.stderr
    cands = sorted({m for m in re.findall(r"(?<![\w-])--[A-Za-z0-9][A-Za-z0-9-]*fsm[A-Za-z0-9-]*", text)
                    if not m.startswith("--no-")})
    print(f"\n=== FLAGS CANDIDATAS (do --help, com 'fsm', sem prefixo --no-): {cands} ===")
    if not cands:
        print("  NENHUMA candidata encontrada: este teste NAO verificou nada (sem flags a testar).")
        return
    for i, flag in enumerate(cands):
        try:
            res = _run_fsm(f"flag_{i}", "test_fsm_state_arc_coverage",
                           "test_fsm_state_arc_coverage", extra_flags=[flag])
            pts = _parse_dat(res["dat"])
            print(f"--- {flag}: compilou e rodou. {_fmt_totals(pts)}")
            _fsm_report(flag, pts)
        except Exception as e:
            print(f"--- {flag}: FALHOU ({type(e).__name__}: {str(e)[:300]})"
                  " - pode exigir argumento; nao assumir que a flag nao funciona")