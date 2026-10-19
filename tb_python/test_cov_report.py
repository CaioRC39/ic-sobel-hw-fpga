"""Testes do agregador scripts/cov_report.py (Fase 4, etapa 4.3). Python puro, sem simulador.

Cada teste fabrica .dat/.json minimos em tmp_path. O formato do .dat imitado
(C '<k>\\x02<v>\\x01...' <contagem>) e o mesmo lido dos spikes 1 e 2.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import cov_report as C  # noqa: E402


def _pt(rel, page, line, o, count, n="1", t="x", h="top", root="/w"):
    kv = (f"\x01f\x02{root}/rtl/{rel}\x01l\x02{line}\x01n\x02{n}"
          f"\x01page\x02{page}\x01t\x02{t}\x01o\x02{o}\x01h\x02{h}")
    return f"C '{kv}' {count}\n"


def _run(data_dir, stem, lines, status="completed", write_dat=True):
    data_dir.mkdir(parents=True, exist_ok=True)
    if write_dat:
        (data_dir / f"{stem}.dat").write_text("".join(lines))
    (data_dir / f"{stem}.json").write_text(
        json.dumps({"status": status, "testcase": stem, "verilator": "vX"}))


def _rule(rid, **kw):
    base = {"id": rid, "file": "common/x.sv", "kind": "toggle", "reason": "r", "proof": "p",
            "class": "inalcancavel"}
    base.update(kw)
    return base


def test_sums_across_runs_ignoring_hierarchy(tmp_path):
    d = tmp_path / "cov"
    _run(d, "a", [_pt("common/x.sv", "v_line/x", 10, "case", 3, h="top.u1")])
    _run(d, "b", [_pt("common/x.sv", "v_line/x", 10, "case", 4, h="outra.u9")])
    agg, _, errs = C.load_campaign(d)
    assert errs == []
    assert len(agg.count) == 1
    (k,) = agg.count
    assert agg.count[k] == 7 and agg.cov_by[k] == {"a", "b"}


def test_covered_by_tracks_only_runs_with_hits(tmp_path):
    d = tmp_path / "cov"
    _run(d, "zero", [_pt("common/x.sv", "v_line/x", 5, "case", 0)])
    _run(d, "hit", [_pt("common/x.sv", "v_line/x", 5, "case", 2)])
    _run(d, "zero2", [_pt("common/x.sv", "v_line/x", 5, "case", 0)])
    agg, _, errs = C.load_campaign(d)
    assert errs == []
    (k,) = agg.count
    assert agg.count[k] == 2 and agg.cov_by[k] == {"hit"}


def test_integrity_errors_are_reported(tmp_path):
    _, _, errs = C.load_campaign(tmp_path / "vazio")
    assert any("nenhum sidecar" in e for e in errs)

    d = tmp_path / "cov"
    _run(d, "ok", [_pt("common/x.sv", "v_line/x", 1, "case", 1)])
    _run(d, "abort", [], status="started", write_dat=False)
    _run(d, "nodat", [], write_dat=False)
    (d / "orfao.dat").write_text("C 'x' 1\n")
    _, _, errs = C.load_campaign(d)
    text = " | ".join(errs)
    assert "execucao incompleta" in text and "abort" in text
    assert "sidecar sem .dat: nodat" in text
    assert ".dat orfao" in text and "orfao.dat" in text


def test_non_rtl_points_are_skipped_and_counted(tmp_path):
    ext = "C '\x01f\x02/usr/share/verilator/include/y.sv\x01l\x021\x01page\x02v_line/y\x01o\x02case' 1\n"
    d = tmp_path / "cov"
    _run(d, "a", [_pt("common/x.sv", "v_line/x", 1, "case", 1), ext])
    agg, _, errs = C.load_campaign(d)
    assert errs == [] and agg.skipped_non_rtl == 1 and len(agg.count) == 1

    d2 = tmp_path / "cov2"  # so pontos externos: nao pode virar "0/0 sem erro"
    _run(d2, "b", [ext])
    _, _, errs = C.load_campaign(d2)
    assert any("nenhum ponto de RTL" in e for e in errs)


def test_toggle_rule_bit_range_boundaries(tmp_path):
    d = tmp_path / "cov"
    lines = [_pt("multicycle/mac_unit.sv", "v_toggle/mac_unit", 34, f"pixel_ext[{b}]:{dr}",
                 0 if b >= 7 else 4)
             for b in range(12) for dr in ("0->1", "1->0")]
    _run(d, "a", lines)
    agg, _, errs = C.load_campaign(d)
    assert errs == []
    rule = _rule("MU-01", file="multicycle/mac_unit.sv", signal="pixel_ext",
                 bits="ACC_WIDTH-1:DATA_WIDTH", params={"ACC_WIDTH": 11, "DATA_WIDTH": 8})
    res = C.apply_rules([rule], agg, lambda rel: None)

    def bit(k):
        return int(k[5].split("[")[1].split("]")[0])

    assert len(res["excluded"]) == 6 and {bit(k) for k in res["excluded"]} == {8, 9, 10}
    left = {bit(k) for k, c in agg.count.items() if c == 0 and k not in res["excluded"]}
    assert left == {7, 11}  # fronteiras: 7 abaixo da faixa, 11 acima dela
    assert res["obsolete"] == [] and res["unneeded"] == []


def test_text_rule_matches_source_text_and_goes_obsolete_if_source_shifts(tmp_path):
    root = tmp_path / "proj"
    src = root / "rtl" / "common" / "x.sv"
    src.parent.mkdir(parents=True)
    src.write_text("module x;\n  case (s)\n    default:   y = 0;\n  endcase\nendmodule\n")
    d = tmp_path / "cov"
    _run(d, "a", [_pt("common/x.sv", "v_line/x", 3, "case", 0),
                  _pt("common/x.sv", "v_line/x", 2, "case", 5)])
    agg, _, _ = C.load_campaign(d)
    rule = _rule("X-01", kind="line", text="default: y = 0;")
    res = C.apply_rules([rule], agg, C.make_src_getter(root))
    assert len(res["excluded"]) == 1 and res["obsolete"] == []

    # fonte deslocada em 1 linha SEM refazer a campanha: a regra deve falhar alto
    src.write_text("// novo\n" + src.read_text())
    res2 = C.apply_rules([rule], agg, C.make_src_getter(root))
    assert res2["obsolete"] == ["X-01"]


def test_obsolete_unneeded_and_overlap(tmp_path):
    d = tmp_path / "cov"
    _run(d, "a", [_pt("common/x.sv", "v_toggle/x", 1, "s[0]:0->1", 0),
                  _pt("common/x.sv", "v_toggle/x", 1, "s[0]:1->0", 9),
                  _pt("common/x.sv", "v_toggle/x", 1, "t:0->1", 0)])
    agg, _, _ = C.load_campaign(d)
    rules = [_rule("A", signal="s", dir="0->1"),
             _rule("B", signal="s", dir="1->0"),       # so casa ponto coberto
             _rule("C", signal="nao_existe"),          # nao casa com nada
             _rule("D", signal="s", dir="0->1")]       # sobrepoe A
    res = C.apply_rules(rules, agg, lambda rel: None)
    assert res["obsolete"] == ["C", "D"]
    assert res["unneeded"] == ["B"]
    assert len(res["overlaps"]) == 1 and res["overlaps"][0][1:] == ("A", "D")
    assert len(res["excluded"]) == 1  # t:0->1 continua nao coberto e nao excluido


def test_rule_validation(tmp_path):
    tb = tmp_path / "tb"
    tb.mkdir()
    (tb / "test_neg.py").write_text("def test_exists():\n    pass\n")
    good = _rule("G", kind="line", text="x")
    assert C.validate_rules([good], tb) == []

    ic = dict(good, id="I", **{"class": "so-icarus"})
    assert any("proof_test" in e for e in C.validate_rules([ic], tb))
    assert C.validate_rules([dict(ic, proof_test="test_neg.py::test_exists")], tb) == []
    assert any("proof_test" in e for e in C.validate_rules([dict(ic, proof_test="test_neg.py::test_falta")], tb))
    assert any("proof_test" in e for e in C.validate_rules([dict(ic, proof_test="nao_existe.py::test_exists")], tb))

    assert any("duplicado" in e for e in C.validate_rules([good, dict(good)], tb))
    sem_proof = {k: v for k, v in good.items() if k != "proof"}
    assert any("proof" in e for e in C.validate_rules([sem_proof], tb))
    assert any("class invalida" in e for e in C.validate_rules([dict(good, **{"class": "qualquer"})], tb))
    assert any("params" in e for e in C.validate_rules([_rule("T", signal="s", bits="N-1:0")], tb))
    assert any("bits invalido" in e for e in
               C.validate_rules([_rule("T", signal="s", bits="N-1:0", params={})], tb))


def _project(tmp_path, with_rule=True):
    root = tmp_path / "proj"
    (root / "rtl" / "common").mkdir(parents=True)
    (root / "tb_python").mkdir()
    (root / "scripts").mkdir()
    (root / "rtl" / "common" / "x.sv").write_text(
        "module x;\n  assign y = a;\n  assign z = b;\n  default: q = 0;\nendmodule\n")
    lines = [_pt("common/x.sv", "v_line/x", i, "case", c) for i, c in ((1, 5), (2, 5), (3, 5), (4, 0))]
    lines += [_pt("common/x.sv", "v_toggle/x", 1, f"a[{b}]:{dr}", 0 if (b == 4 and dr == "1->0") else 3)
              for b in range(5) for dr in ("0->1", "1->0")]
    _run(root / "sim" / "cov_data", "a", lines)  # escrito DEPOIS do RTL (sem 'stale')
    if with_rule:
        (root / "scripts" / "cov_exclusions.toml").write_text(
            '[[exclude]]\nid = "X-01"\nfile = "common/x.sv"\nkind = "line"\n'
            'text = "default: q = 0;"\nclass = "inalcancavel"\nreason = "teste"\nproof = "teste"\n')
    return root


def test_main_thresholds_and_exit_codes(tmp_path, capsys):
    root = _project(tmp_path)
    r = str(root)
    # code: 3/4 bruto -> 3/3 efetivo; toggle: 9/10 = 90.0%
    assert C.main(["--root", r, "--min-code", "95", "--min-toggle", "90"]) == 0
    assert C.main(["--root", r, "--min-toggle", "95"]) == 1
    (root / "scripts" / "cov_exclusions.toml").unlink()
    assert C.main(["--root", r, "--min-code", "95"]) == 1  # sem a exclusao o bruto (75%) reprova
    out = capsys.readouterr().out
    assert "3/4" in out and "9/10" in out