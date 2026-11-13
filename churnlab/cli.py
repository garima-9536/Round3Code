"""Command line: python -m churnlab {generate,validate,evaluate,all,repro} ..."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .config import Config, scaled_config
from .export import export
from .generate.pipeline import generate

DEFAULT_OUT = Path("output")


def _cfg_from_args(a) -> Config:
    n = a.customers if a.customers else None
    cfg = scaled_config(str(n) if n else a.scale)
    cfg.seed = a.seed
    cfg.n_campaigns = getattr(a, "campaigns", 1)
    cfg.expose_override_flag = not getattr(a, "hide_override_flag", False)
    return cfg


def cmd_generate(a) -> Path:
    cfg = _cfg_from_args(a)
    out = Path(a.out) if a.out else DEFAULT_OUT / a.scale
    t = time.time()
    g = generate(cfg)
    command = "python -m churnlab generate " + " ".join(sys.argv[2:])
    export(g, out, command, sql=not a.no_sql)
    print(f"[generate] {cfg.n_customers:,} customers, seed={cfg.seed} -> {out}  ({time.time() - t:.1f}s)")
    return out


def cmd_validate(a, out: Path | None = None) -> dict:
    from .validate.checks import run_validation
    out = out or Path(a.out)
    s = run_validation(out, check_sql_load=not getattr(a, "no_sql", False))
    print(f"[validate] {'PASS' if s['passed'] else 'FAIL'}  errors={s['total_error_violations']}  rule_violations={s['total_rule_violations']}  "
          f"-> {out / 'validation' / 'validation_summary.md'}")
    return s


def cmd_evaluate(a, out: Path | None = None) -> dict:
    from .evaluate.report import run_evaluation
    out = out or Path(a.out)
    r = run_evaluation(out)
    print(f"[evaluate] report -> {out / 'evaluation' / 'evaluation_report.md'}")
    return r


def cmd_report(a, out: Path | None = None) -> Path:
    from .report_html import build_report
    path = build_report(out or Path(a.out))
    print(f"[report] open in a browser -> {path}")
    return path


def cmd_demo(a) -> None:
    """Generate + validate + evaluate + report in one go (default: starter scale into output/demo), then print the headline results."""
    a.out = a.out or str(DEFAULT_OUT / "demo")
    out = cmd_generate(a)
    ok = cmd_validate(a, out)["passed"]
    ev = cmd_evaluate(a, out)
    cmd_report(a, out)
    x = ev["offer_experiment"]
    itt, naive = x["incremental_lift_ITT"], x["naive_correlational_estimates"]
    print("\nHeadline results")
    print(f"  validation                    : {'PASS' if ok else 'FAIL'}")
    print(f"  naive (accepters vs others)   : {naive['accepters_vs_non_accepters_churn_reduction'] * 100:+.2f} pts churn reduction")
    print(f"  randomised test (ITT)         : {itt['churn_reduction_abs'] * 100:+.2f} pts  (95% CI {itt['ci95'][0] * 100:+.2f} to {itt['ci95'][1] * 100:+.2f}, p={itt['p_value']:.3f})")
    print(f"  offer cost on likely stayers  : {x['scored_against_ground_truth']['share_of_total_offer_cost_wasted'] * 100:.0f}%")
    sys.exit(0 if ok else 1)


def cmd_repro(a):
    from .repro import run_repro
    cfg = _cfg_from_args(a)
    ok = run_repro(cfg, Path(a.report) if a.report else Path("docs") / f"repro_check_{a.scale}.md")
    sys.exit(0 if ok else 1)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="churnlab")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, need_out=True):
        p.add_argument("--scale", default="starter", choices=["starter", "full"], help="starter=1,500 customers, full=20,000")
        p.add_argument("--customers", type=int, default=0, help="override customer count")
        p.add_argument("--seed", type=int, default=20261022)
        p.add_argument("--out", default=None, help="output directory (default output/<scale>)")
        p.add_argument("--no-sql", action="store_true", help="skip seed.sql export / SQL load check")
        p.add_argument("--campaigns", type=int, default=1, choices=[1, 2], help="1 = single campaign (default); 2 = one campaign per segment")
        p.add_argument("--hide-override-flag", action="store_true", help="manual overrides are indistinguishable from automatic contacts")

    for name in ("generate", "all"):
        p = sub.add_parser(name)
        common(p)
    p = sub.add_parser("validate")
    p.add_argument("--out", required=True)
    p.add_argument("--no-sql", action="store_true")
    p = sub.add_parser("evaluate")
    p.add_argument("--out", required=True)
    p = sub.add_parser("report", help="build an interactive HTML report (report.html) from a finished run")
    p.add_argument("--out", required=True)
    p = sub.add_parser("demo", help="starter-scale generate + validate + evaluate + report into output/demo, then print headline results")
    common(p)
    p = sub.add_parser("repro")
    common(p)
    p.add_argument("--report", default=None)
    sub.add_parser("docs", help="write docs/data_dictionary.md and docs/er_diagram.md from the schema")

    a = ap.parse_args(argv)
    if a.cmd == "docs":
        from . import docs
        Path("docs").mkdir(exist_ok=True)
        Path("docs/data_dictionary.md").write_text(docs.data_dictionary_md(), encoding="utf-8")
        Path("docs/er_diagram.md").write_text(docs.er_diagram_md(), encoding="utf-8")
        print("[docs] wrote docs/data_dictionary.md and docs/er_diagram.md")
    elif a.cmd == "generate":
        cmd_generate(a)
    elif a.cmd == "validate":
        sys.exit(0 if cmd_validate(a)["passed"] else 1)
    elif a.cmd == "evaluate":
        cmd_evaluate(a)
    elif a.cmd == "all":
        out = cmd_generate(a)
        ok = cmd_validate(a, out)["passed"]
        cmd_evaluate(a, out)
        sys.exit(0 if ok else 1)
    elif a.cmd == "report":
        cmd_report(a)
    elif a.cmd == "demo":
        cmd_demo(a)
    elif a.cmd == "repro":
        cmd_repro(a)


if __name__ == "__main__":
    main()
