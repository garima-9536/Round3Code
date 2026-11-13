"""Orchestrates master -> history -> campaign -> events -> derived -> anomalies -> ground truth."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from ..config import Config
from ..rng import Streams
from ..schema import T as SCHEMA
from . import anomalies, derive, emit, master, prospects as prospect_gen
from .campaign import run_campaign
from .simulate import resolve, simulate_history


def finalize(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """Order columns per schema, normalise types, sort by primary key."""
    t = SCHEMA[name]
    out = pd.DataFrame(index=df.index)
    for f in t.fields:
        col = df[f.name]
        if f.type == "date":
            col = pd.to_datetime(col)
            col = col.dt.strftime("%Y-%m-%d")
            col = col.where(col.notna(), None)
        elif f.type == "datetime":
            col = col.where(col.notna(), None)
        elif f.type == "decimal":
            col = pd.to_numeric(col).round(2)
        elif f.type in ("int", "bool"):
            col = pd.to_numeric(col)
            col = col.astype("Int64") if (not f.required or col.isna().any()) else col.astype("int64")
        else:
            col = col.astype(object).where(col.notna(), None)
        out[f.name] = col
    return out.sort_values(t.pk, kind="stable").reset_index(drop=True)


def hide_override_flag(contacts: pd.DataFrame, evals: pd.DataFrame) -> pd.DataFrame:
    """Make manual overrides look like ordinary system contacts (no flag, no role, no audit entry).

    The only trace left in the inputs is what a real analyst would also have: the contact points at an eligibility
    evaluation whose decision is INELIGIBLE. The labelled truth stays in ground_truth (INELIGIBLE_OFFER_SENT)."""
    out = contacts.copy()
    ov = (out["contact_source"] == "MANUAL_OVERRIDE").to_numpy()
    key = evals.set_index(["customer_id", "offer_id"])["evaluation_id"]
    idx = pd.MultiIndex.from_arrays([out.loc[ov, "customer_id"], out.loc[ov, "offer_id"]])
    out.loc[ov, "eligibility_evaluation_id"] = key.reindex(idx).to_numpy()
    out.loc[ov, "contact_source"] = "AUTO_ELIGIBLE"
    out.loc[ov, "launched_by_role"] = "SYSTEM"
    return out


def generate(cfg: Config) -> SimpleNamespace:
    streams = Streams(cfg.seed)
    plans = master.build_plans(cfg)
    offers = master.build_offers(cfg)
    rules, bridge = master.build_rules(cfg)

    P = master.build_population(cfg, streams)
    H = simulate_history(cfg, P, streams)
    R0 = resolve(cfg, P, H)
    C = run_campaign(cfg, P, H, R0, offers, rules, bridge, streams)

    s = emit.build_sub_arrays(cfg, P, H, C)
    sev = emit.emit_subscription_events(cfg, P, H, s, streams)
    usage = emit.emit_usage(cfg, P, H, s, streams)
    billing = emit.emit_billing(cfg, P, H, s, streams)
    cases = emit.emit_cases(cfg, P, H, s, streams)

    subs = derive.derive_subscriptions(sev, s, P)
    customers = derive.derive_customers(subs, P)
    churn = derive.derive_churn_outcomes(cfg, subs, sev)

    # observed experiment facts (source records) keyed by contact
    cidx = C.cidx
    obs = pd.DataFrame({
        "contact_id": C.contacts["contact_id"].to_numpy(),
        "viewed": C.viewed[cidx].astype(int),
        "accepted": C.accepted[cidx].astype(int),
        "accepted_at": np.where(C.accepted[cidx], C.accepted_at[cidx].astype("datetime64[D]").astype(str), None),
    })
    base_ret = derive.derive_retention(cfg, C.contacts, obs, billing, subs)
    A = anomalies.inject(cfg, C, C.contacts, C.evals, base_ret, subs, sev, streams)

    contacts = pd.concat([C.contacts, A.new_contacts], ignore_index=True)
    if len(A.new_contacts):
        new_ret = derive.derive_retention(cfg, A.new_contacts, A.new_obs, billing, subs)
        mc = new_ret["contact_id"].isin(A.multi_contact_ids)
        new_ret.loc[mc, "retention_attributed"] = 1
        new_ret.loc[mc, "attributed_offer_id"] = new_ret.loc[mc, "offer_id"]
        retention = pd.concat([base_ret, new_ret], ignore_index=True)
    else:
        retention = base_ret
    if len(A.extra_churn):
        churn = pd.concat([churn, A.extra_churn], ignore_index=True)

    prospects, prospect_events = prospect_gen.build_prospects(cfg, P, streams)

    if not cfg.expose_override_flag:
        contacts = hide_override_flag(contacts, C.evals)

    tables = {
        "customers": customers, "prospects": prospects, "prospect_events": prospect_events, "plans": plans, "subscriptions": subs, "subscription_events": sev, "usage_snapshots": usage,
        "billing_events": billing, "support_cases": cases, "offers": offers, "eligibility_rules": rules,
        "offer_eligibility_rules": bridge, "eligibility_evaluations": C.evals, "campaigns": master.build_campaigns(cfg), "campaign_contacts": contacts,
        "churn_outcomes": churn, "retention_outcomes": retention,
        "admin_audit_log": derive.build_audit(plans, offers, rules, contacts),
    }
    tables = {k: finalize(v, k) for k, v in tables.items()}

    # ---- ground truth (never read by validator-input features or evaluation features) ---------------------
    gt = A.ground_truth
    inscope = np.nonzero(C.inscope)[0]
    grp = np.array(["NONE", "TREATMENT", "CONTROL"], dtype=object)[C.group]
    offer_ids = np.array(C.offer_ids, dtype=object)
    latent = pd.DataFrame({
        "customer_id": P.cust_ids[inscope],
        "campaign_group": grp[inscope],
        "manual_override": C.override[inscope].astype(int),
        "hypothetical_offer_id": np.where(C.group[inscope] > 0, offer_ids[C.choice[inscope]], None),
        "would_accept_offer": C.would_accept[inscope].astype(int),
        "churn_in_horizon_if_not_offered": C.y0[inscope].astype(int),
        "churn_in_horizon_if_offered": C.y1[inscope].astype(int),
        "true_individual_effect": (C.y0[inscope].astype(int) - C.y1[inscope].astype(int)),
        "offer_effect_log_odds": np.round(np.where(C.would_accept[inscope], C.delta[inscope], 0.0), 4),
        "seasonal_user": P.seasonal[inscope].astype(int),
        "latent_risk": np.round(P.risk0[inscope], 4),
        "price_sensitivity": np.round(P.price_sens[inscope], 4),
        "backlash_trait": P.backlash[inscope].astype(int),
    })
    elig_mask = C.elig.any(1)[inscope]
    clean = latent[(latent["campaign_group"] != "NONE") & (latent["manual_override"] == 0)]
    treated = clean[clean["campaign_group"] == "TREATMENT"]
    acc = clean[clean["would_accept_offer"] == 1]
    truth = {
        "definition": "true_individual_effect = churn if not offered - churn if offered (accepting); both potential outcomes "
                      "simulated with common random numbers; units: customers",
        "n_eligible_randomised": int(len(clean)),
        "true_itt_effect_all_eligible": float(clean["true_individual_effect"].mean()),
        "true_itt_effect_treated_arm": float(treated["true_individual_effect"].mean()) if len(treated) else None,
        "true_effect_on_would_accept": float(acc["true_individual_effect"].mean()) if len(acc) else None,
        "would_accept_rate": float(clean["would_accept_offer"].mean()),
        "churn_rate_if_not_offered": float(clean["churn_in_horizon_if_not_offered"].mean()),
        "per_offer_true_itt": {o: float(g["true_individual_effect"].mean()) for o, g in clean.groupby("hypothetical_offer_id")},
    }
    return SimpleNamespace(tables=tables, ground_truth=gt, latent=latent, truth=truth, cfg=cfg, camp=C, population=P)
