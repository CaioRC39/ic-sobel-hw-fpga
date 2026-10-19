"""Testes do gancho COV_MODE de _cocotb_helpers.run_isolated (Fase 4, etapa 4.1).

Python puro: _cocotb_run e substituido por um falso; nenhum simulador e usado.
Garantem que (a) sem COV_MODE nada muda, e (b) com COV_MODE a chamada e
adaptada corretamente, sem colisao de arquivos e sem mutar argumentos do chamador.
"""

import json

import pytest

import _cocotb_helpers as H

BASE = dict(
    verilog_sources=["/x/a.sv", "/x/b.sv"],
    includes=["/x/inc"],
    toplevel="top",
    module="test_x",
    parameters={"W": 4},
    compile_args=["-g2012", "-Wall"],
    sim_build="/tmp/zz/sim_build_x",
)


def _spy(monkeypatch):
    calls = []
    monkeypatch.setattr(H, "_cocotb_run", lambda **kw: calls.append(kw))
    return calls


def _cov_env(monkeypatch, tmp_path):
    monkeypatch.setenv("COV_MODE", "1")
    monkeypatch.setenv("SIM", "verilator")
    monkeypatch.setenv("COV_DATA_DIR", str(tmp_path))


def test_default_mode_is_unchanged(monkeypatch):
    calls = _spy(monkeypatch)
    monkeypatch.delenv("COV_MODE", raising=False)
    H.run_isolated("t1", **BASE)
    kw = calls[0]
    assert kw["compile_args"] == ["-g2012", "-Wall"]
    assert kw["sim_build"] == "/tmp/zz/sim_build_x"
    assert "plus_args" not in kw
    assert kw["extra_env"] == {"COCOTB_TESTCASE": "t1"}


def test_cov_mode_adapts_call_and_writes_sidecar(monkeypatch, tmp_path):
    _cov_env(monkeypatch, tmp_path)
    seen = {}

    def fake(**kw):
        sidecars = list(tmp_path.glob("*.json"))
        assert len(sidecars) == 1, "sidecar deveria existir ANTES da simulacao"
        seen["during"] = json.loads(sidecars[0].read_text())["status"]
        seen["kw"] = kw

    monkeypatch.setattr(H, "_cocotb_run", fake)
    H.run_isolated("t1", **BASE)

    kw = seen["kw"]
    assert seen["during"] == "started"
    assert kw["compile_args"] == ["--coverage", "-Wno-fatal"]
    assert kw["sim_build"] == "/tmp/zz/sim_build_x_cov"
    (plus,) = kw["plus_args"]
    assert plus.startswith("+verilator+coverage+file+") and plus.endswith(".dat")
    assert str(tmp_path) in plus
    meta = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert meta["status"] == "completed"
    assert meta["toplevel"] == "top" and meta["testcase"] == "t1"
    assert meta["parameters"] == {"W": 4}
    assert meta["sources"] == ["a.sv", "b.sv"]


def test_cov_mode_skips_negative_runners(monkeypatch, tmp_path):
    _cov_env(monkeypatch, tmp_path)
    calls = _spy(monkeypatch)
    with pytest.raises(pytest.skip.Exception):
        H.run_isolated("t1", expect_errors=2, **BASE)
    assert calls == []


def test_cov_mode_requires_verilator(monkeypatch, tmp_path):
    _cov_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SIM", "icarus")
    calls = _spy(monkeypatch)
    with pytest.raises(AssertionError, match="SIM=verilator"):
        H.run_isolated("t1", **BASE)
    assert calls == []


def test_cov_mode_paths_are_distinct_per_configuration(monkeypatch, tmp_path):
    """Mesmo sim_build, execucoes diferentes (como em test_pipeline_status):
    nao podem sobrescrever o mesmo .dat; a mesma execucao repetida da o mesmo caminho."""
    _cov_env(monkeypatch, tmp_path)
    calls = _spy(monkeypatch)
    H.run_isolated("t1", extra_env={"PROBE_MODE": "B"}, **BASE)
    H.run_isolated("t1", extra_env={"PROBE_MODE": "C"}, **BASE)
    H.run_isolated("t1", extra_env={"PROBE_MODE": "B"}, **BASE)
    p = [c["plus_args"][0] for c in calls]
    assert p[0] != p[1]
    assert p[0] == p[2]


def test_cov_mode_does_not_mutate_caller_args(monkeypatch, tmp_path):
    _cov_env(monkeypatch, tmp_path)
    _spy(monkeypatch)
    args = ["-g2012", "-Wall"]
    H.run_isolated("t1", **dict(BASE, compile_args=args))
    assert args == ["-g2012", "-Wall"]