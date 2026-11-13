"""Step 10: regenerate twice with the same seed and compare row counts and checksums."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .config import Config
from .export import export
from .generate.pipeline import generate


def run_repro(cfg: Config, report_path: Path) -> bool:
    tmp = Path(tempfile.mkdtemp(prefix="churnlab_repro_"))
    manifests = []
    try:
        for i in (1, 2):
            g = generate(cfg)
            manifests.append(export(g, tmp / f"run{i}", f"repro run {i} seed={cfg.seed} customers={cfg.n_customers}", sql=True))
        other = Config(**{**cfg.__dict__, "seed": cfg.seed + 1})
        differs = not generate(other).tables["usage_snapshots"].equals(generate(cfg).tables["usage_snapshots"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    f1, f2 = manifests[0]["files"], manifests[1]["files"]
    ok = f1.keys() == f2.keys()
    rows = []
    for k in sorted(f1):
        same_hash = f1[k]["sha256"] == f2.get(k, {}).get("sha256")
        same_rows = f1[k].get("rows") == f2.get(k, {}).get("rows")
        ok &= same_hash and same_rows
        rows.append((k, f1[k].get("rows", ""), f2.get(k, {}).get("rows", ""), f1[k]["sha256"][:16], f2.get(k, {}).get("sha256", "")[:16],
                     "OK" if same_hash and same_rows else "MISMATCH"))
    L = ["# Reproducibility check", "",
         f"- generator command: `python -m churnlab repro --customers {cfg.n_customers} --seed {cfg.seed}`",
         f"- seed: **{cfg.seed}**, customers: **{cfg.n_customers:,}**",
         "- method: the full generate+export pipeline was run twice in fresh directories; row counts and SHA-256 of every exported file were compared",
         f"- a different seed ({cfg.seed + 1}) produces different data: **{differs}**",
         f"- **result: {'IDENTICAL (reproducible)' if ok else 'MISMATCH'}**", "",
         "| file | rows run1 | rows run2 | sha256 run1 | sha256 run2 | match |", "|---|---|---|---|---|---|"]
    for r in rows:
        L.append("| " + " | ".join(str(x) for x in r) + " |")
    L.append("")
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(L), encoding="utf-8")
    print(f"[repro] {'IDENTICAL' if ok else 'MISMATCH'} -> {report_path}")
    return bool(ok and differs)
