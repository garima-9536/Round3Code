"""Step 9: export CSV / JSON / SQL seed data, ground truth, docs and the source manifest."""
from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__, docs
from .schema import T as SCHEMA, ddl

JSON_MAX_ROWS = 100_000
BATCH = 500


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _csv_ready(df: pd.DataFrame, name: str) -> pd.DataFrame:
    out = df.copy()
    for f in SCHEMA[name].fields:
        if f.type == "decimal":
            out[f.name] = out[f.name].map(lambda x: None if pd.isna(x) else f"{x:.2f}")
    return out


def write_csv(df: pd.DataFrame, path: Path, name: str):
    _csv_ready(df, name).to_csv(path, index=False, lineterminator="\n")


def _sql_cols(df: pd.DataFrame, name: str):
    cols = []
    for f in SCHEMA[name].fields:
        s = df[f.name]
        if f.type in ("int", "bool"):
            vals = [("NULL" if pd.isna(x) else str(int(x))) for x in s]
        elif f.type == "decimal":
            vals = [("NULL" if pd.isna(x) else f"{x:.2f}") for x in s]
        else:
            vals = [("NULL" if (x is None or (isinstance(x, float) and np.isnan(x)) or x is pd.NA) else "'" + str(x).replace("'", "''") + "'") for x in s]
        cols.append(vals)
    return cols


def write_sql_table(fh, df: pd.DataFrame, name: str):
    cols = ", ".join(f.name for f in SCHEMA[name].fields)
    rows = ["(" + ",".join(r) + ")" for r in zip(*_sql_cols(df, name))]
    for i in range(0, len(rows), BATCH):
        fh.write(f"INSERT INTO {name} ({cols}) VALUES\n" + ",\n".join(rows[i:i + BATCH]) + ";\n")


def export(g, out_dir, command: str, sql: bool = True) -> dict:
    out = Path(out_dir)
    (out / "data").mkdir(parents=True, exist_ok=True)
    (out / "ground_truth").mkdir(exist_ok=True)
    (out / "docs").mkdir(exist_ok=True)
    (out / "sql").mkdir(exist_ok=True)
    files = {}

    for name, df in g.tables.items():
        p = out / "data" / f"{name}.csv"
        write_csv(df, p, name)
        files[f"data/{name}.csv"] = {"rows": int(len(df)), "sha256": sha256(p)}
        if len(df) <= JSON_MAX_ROWS:
            jp = out / "data" / f"{name}.json"
            _csv_ready(df, name).to_json(jp, orient="records", indent=None)
        else:  # large tables: JSON Lines (one record per line)
            jp = out / "data" / f"{name}.jsonl"
            _csv_ready(df, name).to_json(jp, orient="records", lines=True)
        files[f"data/{jp.name}"] = {"rows": int(len(df)), "sha256": sha256(jp)}

    gt = g.ground_truth
    gt.to_csv(out / "ground_truth" / "ground_truth.csv", index=False, lineterminator="\n")
    summary = gt.groupby("issue_type").size().to_dict()
    (out / "ground_truth" / "ground_truth.json").write_text(
        json.dumps({"counts_by_issue_type": summary, "records": json.loads(gt.to_json(orient="records"))}, indent=1), encoding="utf-8")
    g.latent.to_csv(out / "ground_truth" / "latent_truth.csv", index=False, lineterminator="\n")
    (out / "ground_truth" / "true_effects.json").write_text(json.dumps(g.truth, indent=1), encoding="utf-8")
    for fn in ("ground_truth.csv", "ground_truth.json", "latent_truth.csv", "true_effects.json"):
        p = out / "ground_truth" / fn
        files[f"ground_truth/{fn}"] = {"sha256": sha256(p)}

    (out / "docs" / "data_dictionary.md").write_text(docs.data_dictionary_md(), encoding="utf-8")
    (out / "docs" / "er_diagram.md").write_text(docs.er_diagram_md(), encoding="utf-8")
    (out / "sql" / "schema.sql").write_text(ddl(), encoding="utf-8")
    files["sql/schema.sql"] = {"sha256": sha256(out / "sql" / "schema.sql")}
    if sql:
        sp = out / "sql" / "seed.sql"
        with open(sp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("BEGIN TRANSACTION;\n")
            for name, df in g.tables.items():
                write_sql_table(fh, df, name)
            fh.write("COMMIT;\n")
        files["sql/seed.sql"] = {"sha256": sha256(sp)}

    manifest = {
        "generator": {"name": "churnlab", "version": __version__, "command": command},
        "seed": g.cfg.seed,
        "config": g.cfg.to_dict(),
        "external_data": {
            "used": False,
            "note": "No external or public data was used or redistributed. All records are synthetic. "
                    "Generic public subscription/telecom churn schemas were consulted for schema inspiration only; no data, "
                    "files or fields were copied. Retrieval date / license / attribution: not applicable.",
        },
        "files": files,
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest
