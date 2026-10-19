"""Funcoes auxiliares compartilhadas pelos testbenches cocotb deste
projeto.

O nome comeca com "_" de proposito: pytest, por padrao, so coleta
arquivos "test_*.py" (ou "*_test.py") como arquivos de teste - um nome
comecando com "_" garante que este arquivo nunca sera confundido com
um testbench em si, mesmo que novos arquivos de teste sejam
adicionados no futuro.
"""

import logging
import functools
import hashlib
import json
import os
import shutil
import subprocess
from contextlib import contextmanager

from cocotb_test.simulator import run as _cocotb_run

# ----------------------------------------------------------------------
# Gancho de cobertura (Fase 4, plano D). So atua com COV_MODE=1.
# Verilator mede cobertura; quem decide "passou" continua sendo o Icarus.
# ----------------------------------------------------------------------
COV_ARGS = ["--coverage", "-Wno-fatal"]  # -Wno-fatal: aviso de lint nao pode derrubar a campanha
_COV_DROP = ("-g2012", "-Wall")  # -g2012 e do Icarus; -Wall e o gate de lint, nao o de cobertura


def _cov_data_dir():
    return os.environ.get("COV_DATA_DIR") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sim", "cov_data"
    )


@functools.lru_cache(maxsize=1)
def _verilator_version():
    exe = shutil.which("verilator")
    if exe is None:
        return "AUSENTE"
    r = subprocess.run([exe, "--version"], capture_output=True, text=True)
    return f"{exe}: {(r.stdout or r.stderr).strip().splitlines()[0]}"


def _cov_prepare(expect_errors, kwargs):
    """Adapta os kwargs de run() para o modo cobertura. Devolve (kwargs_novos, meta)."""
    assert os.environ.get("SIM") == "verilator", (
        "COV_MODE=1 exige SIM=verilator (sem isso nao ha cobertura, so uma simulacao comum)"
    )
    if expect_errors:
        import pytest

        pytest.skip(
            f"COV_MODE: runner negativo (expect_errors={expect_errors}); "
            "$error aborta a simulacao no Verilator"
        )
    sim_build = kwargs.get("sim_build")
    assert sim_build, "COV_MODE exige sim_build explicito"
    base = os.path.basename(str(sim_build).rstrip("/\\"))
    env = dict(kwargs.get("extra_env") or {})
    ident = {
        "toplevel": kwargs.get("toplevel"),
        "module": kwargs.get("module"),
        "parameters": kwargs.get("parameters") or {},
        "extra_env": env,  # inclui COCOTB_TESTCASE
        "sim_build": base,
    }
    digest = hashlib.sha1(json.dumps(ident, sort_keys=True, default=str).encode()).hexdigest()[:8]
    stem = f"{base}__{digest}"
    data_dir = _cov_data_dir()
    os.makedirs(data_dir, exist_ok=True)
    dat = os.path.join(data_dir, stem + ".dat")
    side = os.path.join(data_dir, stem + ".json")
    for p in (dat, side):  # nunca herdar resultado de campanha anterior
        if os.path.exists(p):
            os.remove(p)
    new = dict(kwargs)
    new["compile_args"] = [
       a for a in (kwargs.get("compile_args") or []) if a not in _COV_DROP
    ] + COV_ARGS
    new["sim_build"] = str(sim_build).rstrip("/\\") + "_cov"
    new["plus_args"] = list(kwargs.get("plus_args") or []) + [f"+verilator+coverage+file+{dat}"]
    meta = {
        "stem": stem,
        "dat": dat,
        "json": side,
        "toplevel": kwargs.get("toplevel"),
        "module": kwargs.get("module"),
        "testcase": env.get("COCOTB_TESTCASE"),
        "parameters": kwargs.get("parameters") or {},
        "extra_env": env,
        "sources": [os.path.basename(s) for s in (kwargs.get("verilog_sources") or [])],
        "sim_build": new["sim_build"],
        "verilator": _verilator_version(),
    }
    return new, meta


def _cov_write_meta(meta, status):
    meta["status"] = status
    with open(meta["json"], "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1, default=str)


def run_isolated(testcase=None, *, expect_errors=0, **kwargs):
    """Roda uma simulacao cocotb, opcionalmente restringindo a execucao a
    UMA ou MAIS corrotinas por nome, e GARANTE que o numero de linhas
    "ERROR:" (`$error` do RTL) no log bate com `expect_errors`.

    GUARDA CONTRA $error ESCONDIDO (P15): um `$error` so imprime texto; o
    teste cocotb nao falha por causa dele, e com `pytest -q` o log de
    teste aprovado nem aparece. Por isso o padrao e `expect_errors=0`:
    qualquer `$error` inesperado derruba o teste. Testes de "caminho
    errado" declaram quantos erros esperam (contagem EXATA - se o RTL
    passar a emitir mais ou menos, o teste falha e obriga a olhar).

    Corrige tambem um bug real de versoes desencontradas entre cocotb-test
    0.2.6 e cocotb 2.0+: o parametro `testcase=` de
    `cocotb_test.simulator.run()` define a variavel de ambiente antiga
    "TESTCASE", que o cocotb 2.0+ ignora silenciosamente (ele espera
    "COCOTB_TESTCASE", com prefixo) - sem essa correcao, TODAS as
    corrotinas `@cocotb.test()` do modulo rodam, mesmo pedindo so uma.
    Confirmado com um teste minimo isolado (3 corrotinas triviais,
    pedindo so 1 - as 3 rodaram sem esta correcao). Ver
    docs/ARQUITETURA_MULTICICLO.md, secao 4 (nota metodologica, "Quarta
    pegadinha") para o diagnostico completo.

    COV_MODE=1 (com SIM=verilator): modo cobertura, ver _cov_prepare

    Args:
        testcase: nome de uma corrotina (str), ou varios nomes
            separados por virgula. `None` (padrao) roda TODAS as
            corrotinas do modulo.
        expect_errors: numero EXATO de linhas "ERROR:" esperadas no log
            (padrao 0). Ver acima.
        **kwargs: repassados diretamente para
            cocotb_test.simulator.run() (verilog_sources, toplevel,
            module, parameters, compile_args, sim_build, etc.)

    Exemplo:
        run_isolated(
            "test_a,test_b",
            verilog_sources=[...],
            toplevel="meu_modulo",
            module="test_meu_modulo",
            parameters={...},
            sim_build="sim/sim_build_meu_modulo",
            expect_errors=0,
        )
    """
    extra_env = dict(kwargs.pop("extra_env", None) or {})
    if testcase is not None:
        extra_env["COCOTB_TESTCASE"] = testcase
    kwargs["extra_env"] = extra_env
    meta = None
    if os.environ.get("COV_MODE") == "1":
        kwargs, meta = _cov_prepare(expect_errors, kwargs)
        _cov_write_meta(meta, "started")
    with capture_errors() as capture:
        _cocotb_run(**kwargs)
    if meta is not None:
        _cov_write_meta(meta, "completed")
    assert capture.count == expect_errors, (
        f"Guarda de $error (run_isolated): esperava {expect_errors} linha(s) 'ERROR:' no log da "
        f"simulacao, obtive {capture.count}. Se o RTL deveria emitir esses erros, declare "
        f"expect_errors={capture.count} no teste; se nao, ha um $error escondido a investigar."
    )


class ErrorLogCapture(logging.Handler):
    """Handler de logging que CONTA quantas linhas contendo "ERROR:"
    passaram pelo logger "cocotb" do processo QUE CHAMA run() - nao o
    logger interno da simulacao (`cocotb.<toplevel>`, usado por
    `dut._log`), apesar do nome parecido.

    Necessario porque um `$error` do SystemVerilog e impresso
    diretamente na saida padrao do processo SEPARADO do simulador
    (vvp) - nao passa pelo mecanismo de log Python usado dentro da
    simulacao. Quem le essa saida e a retransmite como log e a
    biblioteca cocotb-test, no MESMO processo que chama run() - por
    isso a captura so funciona pendurada aqui fora, nunca dentro de uma
    corrotina `@cocotb.test()`. Ver docs/ARQUITETURA_MULTICICLO.md,
    secao 4 (nota metodologica, "Segunda pegadinha") para o diagnostico
    completo, incluindo como isso foi confirmado com um dump de VCD.

    Uso direto (equivalente ao que `capture_errors()` abaixo faz por
    voce automaticamente):
        capture = ErrorLogCapture()
        logger = logging.getLogger("cocotb")
        logger.addHandler(capture)
        try:
            run_isolated("nome_do_teste", ...)
        finally:
            logger.removeHandler(capture)
        assert capture.count == N  # ou capture.found, para so >=1
    """

    def __init__(self):
        super().__init__(level=logging.INFO)
        self.count = 0

    @property
    def found(self) -> bool:
        return self.count > 0

    def emit(self, record):
        if "ERROR:" in record.getMessage():
            self.count += 1


@contextmanager
def capture_errors():
    """Gerenciador de contexto que registra um ErrorLogCapture antes de
    rodar a simulacao e garante a remocao dele depois, mesmo se a
    simulacao lancar uma excecao no meio.

    Uso:
        with capture_errors() as capture:
            run_isolated("nome_do_teste", ...)
        assert capture.count == N
    """
    capture = ErrorLogCapture()
    logger = logging.getLogger("cocotb")
    logger.addHandler(capture)
    try:
        yield capture
    finally:
        logger.removeHandler(capture)
