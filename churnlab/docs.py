"""Renders the data dictionary and ER diagram from schema.py (so docs can never drift from the schema)."""
from __future__ import annotations

from .schema import RELATIONSHIPS, T


def _cell(x) -> str:
    return str(x).replace("|", "\\|") if x not in (None, "") else ""


def data_dictionary_md() -> str:
    out = ["# Data dictionary", "",
           "Generated from `churnlab/schema.py` (single source of truth). `req` = required (NOT NULL). "
           "`DERIVED` in a rule means the value is computed from source records, not independently generated.", ""]
    out.append("| Table | Entity | Kind | Primary key | Description |")
    out.append("|---|---|---|---|---|")
    for t in T.values():
        out.append(f"| `{t.name}` | {t.entity} | {t.kind} | {', '.join(t.pk)} | {_cell(t.description)} |")
    out.append("")
    for t in T.values():
        out += [f"## {t.name}", "", f"**Entity:** {t.entity} - {t.description}  ", f"**Primary key:** `{', '.join(t.pk)}`", "",
                "| field | type | req | allowed values / range | unit | unique | validation rule |", "|---|---|---|---|---|---|---|"]
        for f in t.fields:
            allowed = ""
            if f.allowed:
                allowed = ", ".join(str(a) for a in f.allowed)
            elif f.pattern:
                allowed = f"regex `{f.pattern}`"
            elif f.min is not None or f.max is not None:
                allowed = f"{'' if f.min is None else f.min} .. {'' if f.max is None else f.max}"
            uniq = "yes" if (f.unique or (len(t.pk) == 1 and f.name == t.pk[0])) else ""
            out.append(f"| `{f.name}` | {f.type} | {'Y' if f.required else 'N'} | {_cell(allowed)} | {_cell(f.unit)} | {uniq} | {_cell(f.rule)} |")
        rels = [r for r in RELATIONSHIPS if r.child == t.name]
        if rels:
            out += ["", "**Foreign keys**", ""]
            for r in rels:
                out.append(f"- `{r.child_col}` -> `{r.parent}.{r.parent_col}` ({r.cardinality}; {'optional' if r.optional else 'required'}) {r.note}")
        out.append("")
    out += ["## Ground truth (separate files, never used as features)", "",
            "| file | content |", "|---|---|",
            "| `ground_truth/ground_truth.csv` / `.json` | one row per injected anomaly: issue_type, entity, expected decision, expected detecting check |",
            "| `ground_truth/latent_truth.csv` | per in-scope customer: potential churn outcomes with/without offer, latent traits (seasonal user, risk, price sensitivity) |",
            "| `ground_truth/true_effects.json` | true average treatment effects (overall and per offer) used only to score estimators |", ""]
    return "\n".join(out)


def er_diagram_md() -> str:
    lines = ["# Entity relationship diagram", "", "```mermaid", "erDiagram"]
    sym = {"1:N": "||--o{", "N:1": "}o--||", "1:0..1": "||--o|", "N:0..1": "}o--o|", "1:1": "||--||", "N:M bridge": "}o--||"}
    for r in RELATIONSHIPS:
        s = sym.get(r.cardinality, "||--o{")
        if r.cardinality in ("N:1", "N:M bridge"):
            lines.append(f"    {r.parent} ||--o{{ {r.child} : \"{r.child_col}\"")
        elif r.child == r.parent:
            lines.append(f"    {r.parent} ||--o{{ {r.child} : \"{r.child_col}\"")
        else:
            lines.append(f"    {r.parent} {s.replace('}o--||','||--o{')} {r.child} : \"{r.child_col}\"")
    lines += ["```", "", "## Cardinality and lifecycle notes", "",
              "| Relationship | Cardinality | Optional | Note |", "|---|---|---|---|"]
    for r in RELATIONSHIPS:
        lines.append(f"| {r.child}.{r.child_col} -> {r.parent}.{r.parent_col} | {r.cardinality} | {'yes' if r.optional else 'no'} | {_cell(r.note)} |")
    lines += ["", "**Lifecycle states**", "",
              "- Subscription: `ACTIVE -> CANCELLED | TERMINATED_NONPAYMENT` (terminal, derived from `subscription_events`; plan changes and price changes are events, never overwrites).",
              "- Invoice: `INVOICE -> (CREDIT) -> PAYMENT | PAYMENT_FAILED x1..3 -> WRITE_OFF`; every invoice must reconcile to zero balance.",
              "- Support case: `OPEN -> ESCALATED -> RESOLVED` with explicit timestamps.",
              "- Offer / rule: effective-dated (`valid_from/valid_to`, `effective_from/effective_to`); superseded rules are `RETIRED`, never edited.",
              "- Campaign contact: `HOLDOUT` (control) or `DELIVERED/BOUNCED` (treatment); a customer is in exactly one arm per campaign.", ""]
    return "\n".join(lines)
