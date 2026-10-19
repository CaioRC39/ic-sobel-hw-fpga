#!/usr/bin/env python3
"""Agregador de cobertura de codigo (Fase 4, etapa 4.3).

Le a campanha gerada por `make cov-triage` (sim/cov_data/*.dat + *.json) e:
  - agrega por (arquivo RTL, pagina, linha, coluna, tipo, detalhe), IGNORANDO a hierarquia
    (chave 'h'), para somar o teste unitario de um modulo com o teste do sistema;
  - aplica exclusoes de scripts/cov_exclusions.toml (opcional), com 2 classes:
      inalcancavel  - ponto que nao ocorre no projeto
      so-icarus     - ponto coberto so por runner negativo no Icarus (proof_test verificado)
  - mostra SEMPRE bruto e efetivo; falha em campanha incompleta, regra obsoleta/sobreposta,
    regra invalida e (em modo --check) RTL mais novo que a campanha.

Metrica 'code' = line + branch + expr (decisao D2); toggle separado.
Saida: 0 ok; 1 abaixo do limite (--min-code/--min-toggle); 2 erro de integridade.
"""

import argparse
import ast
import json
import re
import sys
import tomllib
from collections import defaultdict
from pathlib import Path

CODE_KINDS = ("v_line", "v_branch", "v_expr")
CLASSES = ("inalcancavel", "so-icarus")
RULE_KINDS = ("toggle", "line", "branch", "expr")
_REC = re.compile(r"^C '(.*)' (\d+)\s*$")
_SIG = re.compile(r"^(?P<name>[A-Za-z_]\w*)(?:\[(?P<bit>\d+)\])?:(?P<dir>[01]->[01])$")


# ----------------------------------------------------------------------
# leitura do .dat e agregacao
# ----------------------------------------------------------------------
def parse_dat(path):
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
            pts.append((kv, int(m.group(2))))
    return pts


def rtl_rel(path):
    """Caminho relativo a rtl/ (ex.: 'common/x.sv'); None se nao for arquivo do RTL."""
    parts = Path(path).parts
    if "rtl" not in parts:
        return None
    i = len(parts) - 1 - parts[::-1].index("rtl")
    rest = parts[i + 1:]
    return "/".join(rest) if rest else None


def make_key(kv):
    rel = rtl_rel(kv.get("f", ""))
    if rel is None:
        return None
    return (rel, kv.get("page", "?"), kv.get("l", ""), kv.get("n", ""), kv.get("t", ""),
            kv.get("o", ""))


def kind_of(key):
    return key[1].split("/")[0]


def _sort_key(k):
    return (k[0], k[1], int(k[2]) if k[2].isdigit() else 0, k[5])


class Agg:
    def __init__(self):
        self.count = defaultdict(int)       # chave -> soma das contagens
        self.cov_by = defaultdict(set)      # chave -> execucoes com contagem > 0
        self.runs = []
        self.skipped_non_rtl = 0
        self.dup_keys = 0

    def add_run(self, stem, pts):
        seen = set()
        for kv, c in pts:
            k = make_key(kv)
            if k is None:
                self.skipped_non_rtl += 1
                continue
            if k in seen:
                self.dup_keys += 1
            seen.add(k)
            self.count[k] += c
            if c > 0:
                self.cov_by[k].add(stem)
        self.runs.append(stem)


def load_campaign(data_dir):
    data_dir = Path(data_dir)
    agg, metas, errors = Agg(), [], []
    sidecars = sorted(data_dir.glob("*.json"))
    if not sidecars:
        errors.append(f"nenhum sidecar .json em {data_dir} (a campanha nao rodou?)")
    for sp in sidecars:
        stem = sp.stem
        try:
            meta = json.loads(sp.read_text())
        except ValueError:
            errors.append(f"sidecar ilegivel: {sp.name}")
            continue
        if meta.get("status") != "completed":
            errors.append(f"execucao incompleta (abortou?): {stem} testcase={meta.get('testcase')}")
            continue
        dat = sp.with_suffix(".dat")
        if not dat.is_file():
            errors.append(f"sidecar sem .dat: {stem}")
            continue
        pts = parse_dat(dat)
        if not pts:
            errors.append(f".dat vazio: {stem}")
            continue
        agg.add_run(stem, pts)
        metas.append(meta)
    stems = {p.stem for p in sidecars}
    for dp in sorted(data_dir.glob("*.dat")):
        if dp.stem not in stems:
            errors.append(f".dat orfao (sem sidecar): {dp.name}")
    if sidecars and not agg.count and not errors:
        errors.append("nenhum ponto de RTL encontrado (o caminho dos pontos nao contem 'rtl/'?)")
    return agg, metas, errors


def stale_sources(root, data_dir):
    sc = list(Path(data_dir).glob("*.json"))
    if not sc:
        return []
    oldest = min(p.stat().st_mtime for p in sc)
    root = Path(root)
    return sorted(str(p.relative_to(root)) for p in (root / "rtl").rglob("*.sv")
                  if p.stat().st_mtime > oldest)


# ----------------------------------------------------------------------
# regras de exclusao
# ----------------------------------------------------------------------
def _eval_int(text, params):
    def ev(n):
        if isinstance(n, ast.Constant) and type(n.value) is int:
            return n.value
        if isinstance(n, ast.Name):
            if n.id not in params:
                raise ValueError(f"parametro '{n.id}' ausente em params")
            return int(params[n.id])
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult)):
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Add):
                return a + b
            return a - b if isinstance(n.op, ast.Sub) else a * b
        raise ValueError(f"expressao nao permitida: {text!r}")

    return ev(ast.parse(text.strip(), mode="eval").body)


def eval_bits(expr, params):
    """'ACC_WIDTH-1:DATA_WIDTH' -> (hi, lo). Aceita tambem um unico bit ('4')."""
    hi_s, _, lo_s = expr.partition(":")
    hi = _eval_int(hi_s, params)
    lo = _eval_int(lo_s, params) if lo_s.strip() else hi
    if lo > hi:
        raise ValueError(f"faixa invertida: {expr!r} -> {hi}:{lo}")
    return hi, lo


def load_rules(path):
    if path is None or not Path(path).is_file():
        return []
    with open(path, "rb") as f:
        return list(tomllib.load(f).get("exclude", []))


def validate_rules(rules, tb_dir):
    errs, seen = [], set()
    for i, r in enumerate(rules):
        rid = r.get("id", f"#{i}")
        if rid in seen:
            errs.append(f"{rid}: id duplicado")
        seen.add(rid)
        for fld in ("id", "file", "kind", "reason", "proof", "class"):
            if not str(r.get(fld, "")).strip():
                errs.append(f"{rid}: campo obrigatorio ausente: {fld}")
        if r.get("class") not in CLASSES:
            errs.append(f"{rid}: class invalida {r.get('class')!r} (use {CLASSES})")
        kind = r.get("kind")
        if kind not in RULE_KINDS:
            errs.append(f"{rid}: kind invalido {kind!r} (use {RULE_KINDS})")
        elif kind == "toggle":
            if not r.get("signal"):
                errs.append(f"{rid}: toggle exige 'signal'")
            if r.get("bits"):
                if not isinstance(r.get("params"), dict):
                    errs.append(f"{rid}: bits exige params (tabela com os valores dos parametros)")
                else:
                    try:
                        eval_bits(r["bits"], r["params"])
                    except (ValueError, SyntaxError) as e:
                        errs.append(f"{rid}: bits invalido: {e}")
        elif not r.get("text"):
            errs.append(f"{rid}: {kind} exige 'text' (texto da linha de fonte)")
        if r.get("class") == "so-icarus":
            fpart, sep, name = str(r.get("proof_test", "")).partition("::")
            ok = False
            if sep:
                p = Path(tb_dir) / fpart
                if p.is_file():
                    base = re.escape(name.split("[")[0])
                    ok = bool(re.search(rf"^\s*(async\s+)?def {base}\b",
                                        p.read_text(errors="replace"), re.M))
            if not ok:
                errs.append(f"{rid}: so-icarus exige proof_test 'arquivo.py::teste' existente "
                            f"em tb_python/ (obtido {r.get('proof_test')!r})")
    return errs


def make_src_getter(root):
    cache = {}

    def get_src(rel):
        if rel not in cache:
            p = Path(root) / "rtl" / rel
            cache[rel] = p.read_text(errors="replace").splitlines() if p.is_file() else None
        return cache[rel]

    return get_src


def rule_matches(rule, key, get_src):
    rel, page, line, _col, _t, detail = key
    kind = page.split("/")[0]
    if rule["file"] != rel or ("v_" + rule["kind"]) != kind:
        return False
    if kind == "v_toggle":
        m = _SIG.match(detail)
        if not m or m["name"] != rule["signal"]:
            return False
        if rule.get("dir") and m["dir"] != rule["dir"]:
            return False
        if rule.get("bits"):
            if m["bit"] is None:
                return False
            hi, lo = eval_bits(rule["bits"], rule["params"])
            return lo <= int(m["bit"]) <= hi
        return True
    if rule.get("detail") and rule["detail"] != detail:
        return False
    src = get_src(rel)
    if not src or not line.isdigit() or not (1 <= int(line) <= len(src)):
        return False
    return " ".join(rule["text"].split()) in " ".join(src[int(line) - 1].split())


def apply_rules(rules, agg, get_src):
    owner, matched, overlaps = {}, defaultdict(list), []
    for key in agg.count:
        for r in rules:
            if rule_matches(r, key, get_src):
                if key in owner:
                    overlaps.append((key, owner[key], r["id"]))
                    continue
                owner[key] = r["id"]
                matched[r["id"]].append(key)
    by_id = {r["id"]: r for r in rules}
    return {
        # so se exclui ponto NAO coberto; ponto coberto casado por regra continua coberto
        "excluded": {k: by_id[rid]["class"] for k, rid in owner.items() if agg.count[k] == 0},
        "obsolete": sorted(r["id"] for r in rules if not matched[r["id"]]),
        "unneeded": sorted(r["id"] for r in rules
                           if matched[r["id"]] and not any(agg.count[k] == 0 for k in matched[r["id"]])),
        "overlaps": overlaps,
        "matched": matched,
    }


# ----------------------------------------------------------------------
# totais e relatorio
# ----------------------------------------------------------------------
def tally(agg, excluded):
    t = defaultdict(lambda: defaultdict(
        lambda: {"total": 0, "hit": 0, "inalcancavel": 0, "so-icarus": 0}))
    for k, c in agg.count.items():
        d = t[k[0]][kind_of(k)]
        d["total"] += 1
        if c > 0:
            d["hit"] += 1
        elif k in excluded:
            d[excluded[k]] += 1
    return t


def _sum(tf, kinds):
    s = {"total": 0, "hit": 0, "inalcancavel": 0, "so-icarus": 0}
    for k in kinds:
        d = tf.get(k)
        if d:
            for fld in s:
                s[fld] += d[fld]
    return s


def _den(s):
    return s["total"] - s["inalcancavel"] - s["so-icarus"]


def _pct_val(s):
    den = _den(s)
    return 100.0 * s["hit"] / den if den else None


def _pct(h, d):
    return f"{100.0 * h / d:5.1f}%" if d else "  n/a"


def print_report(agg, tab, res, metas, n_rules, stale, max_list, get_src):
    print("=== COBERTURA DE CODIGO (Fase 4) ===")
    print(f"execucoes agregadas: {len(agg.runs)}   pontos unicos: {len(agg.count)}")
    print(f"verilator: {sorted({m.get('verilator', '?') for m in metas})}")
    print(f"pontos fora de rtl/ ignorados: {agg.skipped_non_rtl}   "
          f"chaves repetidas dentro de um .dat: {agg.dup_keys}")
    print(f"regras de exclusao carregadas: {n_rules}")
    if stale:
        print(f"AVISO: RTL mais novo que a campanha ({len(stale)}: {', '.join(stale[:5])}); "
              "refaca 'make cov-triage'")
    print("metrica 'code' = line+branch+expr (D2); 'toggle' separado\n")

    print(f"{'arquivo':36s}{'code bruto':>18s}{'code efetivo':>18s}"
          f"{'toggle bruto':>18s}{'toggle efetivo':>18s}{'excl inalc/icarus':>20s}")
    tot = {"c": _sum({}, ()), "t": _sum({}, ())}
    for f in sorted(tab):
        c, t = _sum(tab[f], CODE_KINDS), _sum(tab[f], ("v_toggle",))
        for name, s in (("c", c), ("t", t)):
            for fld in tot[name]:
                tot[name][fld] += s[fld]
        exs = f"{c['inalcancavel'] + t['inalcancavel']}/{c['so-icarus'] + t['so-icarus']}"
        print(f"{f:36s}{_row_raw(c):>18s}{_row_eff(c):>18s}{_row_raw(t):>18s}{_row_eff(t):>18s}{exs:>20s}")
    c, t = tot["c"], tot["t"]
    exs = f"{c['inalcancavel'] + t['inalcancavel']}/{c['so-icarus'] + t['so-icarus']}"
    print(f"{'TOTAL':36s}{_row_raw(c):>18s}{_row_eff(c):>18s}{_row_raw(t):>18s}{_row_eff(t):>18s}{exs:>20s}")

    fsm = [k for k in agg.count if "fsm" in kind_of(k)]
    if fsm:
        print(f"\nFSM (Verilator): {sum(1 for k in fsm if agg.count[k] > 0)}/{len(fsm)} pontos cobertos")
    else:
        print("\nFSM (Verilator): 0 pontos (extrator experimental nao reconhece mac_control_fsm). "
              "Fonte oficial: test_fsm_state_arc_coverage (estados e arcos).")

    if n_rules:
        print("\n--- exclusoes aplicadas (id: excluidos de casados) ---")
        for rid, keys in sorted(res["matched"].items()):
            print(f"  {rid}: {sum(1 for k in keys if agg.count[k] == 0)} de {len(keys)}")
        for rid in res["unneeded"]:
            print(f"  AVISO exclusao desnecessaria (todos os pontos casados ja cobertos): {rid}")

    unc = sorted((k for k, c in agg.count.items() if c == 0 and k not in res["excluded"]),
                 key=_sort_key)
    print(f"\n=== NAO COBERTOS E NAO EXCLUIDOS: {len(unc)} ===")
    shown = unc if max_list <= 0 else unc[:max_list]
    for k in shown:
        kind = kind_of(k)
        if kind == "v_toggle":
            print(f"  toggle {k[0]} {k[5]}")
        else:
            src = get_src(k[0])
            ok = src and k[2].isdigit() and 1 <= int(k[2]) <= len(src)
            txt = " ".join(src[int(k[2]) - 1].split())[:80] if ok else "?"
            print(f"  {kind[2:]:6s} {k[0]}:{k[2]} [{k[5]}] {txt}")
    if len(unc) > len(shown):
        print(f"  ... (+{len(unc) - len(shown)} omitidos; use --max-list 0)")


def _row_raw(s):
    return f"{s['hit']}/{s['total']} {_pct(s['hit'], s['total'])}"


def _row_eff(s):
    return f"{s['hit']}/{_den(s)} {_pct(s['hit'], _den(s))}"


def print_trace(agg, needle):
    hits = [k for k in sorted(agg.count, key=_sort_key) if needle in " ".join(k)]
    print(f"\n=== TRACE '{needle}': {len(hits)} ponto(s) ===")
    for k in hits[:200]:
        who = sorted(agg.cov_by.get(k, ()))
        print(f"  {k[0]}:{k[2]} [{k[1]}] {k[5]} -> soma={agg.count[k]} "
              f"cobertos_por={who if who else 'NINGUEM'}")


# ----------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("--data", default=None)
    ap.add_argument("--rules", default=None)
    ap.add_argument("--min-code", type=float, default=None)
    ap.add_argument("--min-toggle", type=float, default=None)
    ap.add_argument("--max-list", type=int, default=400)
    ap.add_argument("--trace", default=None)
    args = ap.parse_args(argv)

    root = (Path(args.root) if args.root else Path(__file__).resolve().parent.parent).resolve()
    data = Path(args.data) if args.data else root / "sim" / "cov_data"
    rules_path = Path(args.rules) if args.rules else root / "scripts" / "cov_exclusions.toml"
    check = args.min_code is not None or args.min_toggle is not None

    agg, metas, errors = load_campaign(data)
    try:
        rules = load_rules(rules_path)
    except tomllib.TOMLDecodeError as e:
        rules = []
        errors.append(f"arquivo de exclusoes ilegivel ({rules_path.name}): {e}")
    errors += validate_rules(rules, root / "tb_python")
    stale = stale_sources(root, data) if data.is_dir() else []
    if check and stale:
        errors.append(f"RTL mais novo que a campanha: {', '.join(stale[:5])} (refaca make cov-triage)")

    if errors:
        print("=== ERRO DE INTEGRIDADE ===")
        for e in errors:
            print(f"  - {e}")
        return 2

    get_src = make_src_getter(root)
    res = apply_rules(rules, agg, get_src)
    tab = tally(agg, res["excluded"])
    print_report(agg, tab, res, metas, len(rules), stale, args.max_list, get_src)
    if args.trace:
        print_trace(agg, args.trace)

    problems = [f"regra obsoleta (nao casa com nenhum ponto): {rid}" for rid in res["obsolete"]]
    problems += [f"sobreposicao: ponto {k[0]}:{k[2]} {k[5]!r} casado por {a} e {b}"
                 for k, a, b in res["overlaps"]]
    if problems:
        print("\n=== ERRO DE INTEGRIDADE (regras) ===")
        for p in problems:
            print(f"  - {p}")
        return 2

    failed = []
    for f in sorted(tab):
        for label, kinds, lim in (("code", CODE_KINDS, args.min_code),
                                  ("toggle", ("v_toggle",), args.min_toggle)):
            if lim is None:
                continue
            p = _pct_val(_sum(tab[f], kinds))
            if p is not None and p < lim:
                failed.append(f"{f}: {label} efetivo {p:.1f}% < {lim}%")
    if failed:
        print("\n=== ABAIXO DO LIMITE ===")
        for x in failed:
            print(f"  - {x}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())