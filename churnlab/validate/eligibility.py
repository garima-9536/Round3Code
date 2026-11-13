"""Independent re-computation of offer eligibility from the *exported tables* (not from generator internals).

Shared by the validator (check B01/B02) and by the evaluator (to know which offers each customer was eligible for).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PLAN_RANK = {"BASIC": 0, "STANDARD": 1, "PREMIUM": 2, "ADDON": 3}


def plan_asof(events: pd.DataFrame, subs: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """Plan code in force the day before `asof` per subscription, using events strictly before `asof`."""
    e = events[pd.to_datetime(events["event_date"]) < asof].sort_values(["subscription_id", "event_seq"])
    return e.groupby("subscription_id").last()[["to_plan_code"]].rename(columns={"to_plan_code": "plan_code"})


def price_asof(plans: pd.DataFrame, plan_codes: pd.Series, day: pd.Timestamp) -> pd.DataFrame:
    p = plans.copy()
    p["effective_from"] = pd.to_datetime(p["effective_from"])
    p["effective_to"] = pd.to_datetime(p["effective_to"])
    ok = p[(p["effective_from"] <= day) & (p["effective_to"].isna() | (p["effective_to"] >= day))]
    ok = ok.set_index("plan_code")[["monthly_price", "unit_cost"]]
    out = ok.reindex(plan_codes.to_numpy())
    out.index = plan_codes.index
    return out


def recompute(tables: dict, cfg: dict, pairs: pd.DataFrame) -> pd.DataFrame:
    """pairs: DataFrame[customer_id, offer_id]. Returns the same rows with recomputed decision / failed rules / numbers."""
    pred = pd.Timestamp(cfg["prediction_date"])
    window = int(cfg["recent_failure_window_days"])
    horizon_m = int(cfg["margin_horizon_months"])
    subs = tables["subscriptions"]
    prim = subs[subs["is_primary"] == 1].set_index("customer_id")
    cust = tables["customers"].set_index("customer_id")
    offers = tables["offers"].set_index("offer_id")
    rules = tables["eligibility_rules"].set_index("rule_id")
    bridge = tables["offer_eligibility_rules"]

    d = pairs.copy().reset_index(drop=True)
    d["subscription_id"] = prim["subscription_id"].reindex(d["customer_id"]).to_numpy()
    start = pd.to_datetime(prim["start_date"]).reindex(d["customer_id"]).to_numpy()
    d["tenure_months"] = np.floor((pred - pd.to_datetime(start)).days / 30.4375).astype(int)
    d["marketing_consent"] = cust["marketing_consent"].reindex(d["customer_id"]).to_numpy().astype(int)
    b = tables["billing_events"]
    f = b[(b["event_type"] == "PAYMENT_FAILED") & (pd.to_datetime(b["event_date"]) >= pred - pd.Timedelta(days=window)) &
          (pd.to_datetime(b["event_date"]) < pred)]
    nf = f.groupby("subscription_id").size()
    d["failed_payments_window"] = nf.reindex(d["subscription_id"]).fillna(0).astype(int).to_numpy()
    pl = plan_asof(tables["subscription_events"], subs, pred)
    d["plan_code"] = pl["plan_code"].reindex(d["subscription_id"]).to_numpy()
    pr = price_asof(tables["plans"], d["plan_code"], pred - pd.Timedelta(days=1))
    price_c = np.round(pr["monthly_price"].to_numpy() * 100).astype("int64")
    cost_c = np.round(pr["unit_cost"].to_numpy() * 100).astype("int64")
    margin_c = price_c - cost_c
    o = offers.reindex(d["offer_id"])
    typ = o["offer_type"].to_numpy()
    pct = o["discount_pct"].fillna(0).to_numpy().astype(int)
    fixed = np.round(o["fixed_credit_amount"].fillna(0).to_numpy() * 100).astype("int64")
    dur = o["duration_months"].to_numpy().astype(int)
    credit = np.where(typ == "FIXED_CREDIT", np.minimum(fixed, price_c), (price_c * pct + 50) // 100)
    planned = credit * dur
    d["monthly_margin"] = margin_c / 100
    d["offer_cost"] = planned / 100

    fails = [[] for _ in range(len(d))]
    cap_pct_used = np.full(len(d), np.nan)
    br = bridge[(pd.to_datetime(bridge["effective_from"]) <= pred) &
                (bridge["effective_to"].isna() | (pd.to_datetime(bridge["effective_to"]) >= pred))]
    for oid, grp in br.groupby("offer_id"):
        sel = np.nonzero((d["offer_id"] == oid).to_numpy())[0]
        if not len(sel):
            continue
        for rid in grp["rule_id"]:
            rr = rules.loc[rid]
            if rr["status"] != "ACTIVE" or pd.Timestamp(rr["effective_from"]) > pred or (
                    pd.notna(rr["effective_to"]) and pd.Timestamp(rr["effective_to"]) < pred):
                continue
            code, op, thr = rr["rule_code"], rr["operator"], float(rr["threshold_value"])
            if code == "MIN_TENURE_MONTHS":
                val = d["tenure_months"].to_numpy()[sel]
            elif code == "MARKETING_CONSENT":
                val = d["marketing_consent"].to_numpy()[sel]
            elif code == "MAX_FAILED_PAYMENTS_WINDOW":
                val = d["failed_payments_window"].to_numpy()[sel]
            elif code == "MARGIN_CAP_PCT":
                cap_pct_used[sel] = thr
                ok = planned[sel] * 100 <= int(thr) * margin_c[sel] * horizon_m
                for i in sel[~ok]:
                    fails[i].append(code)
                continue
            else:
                continue
            ok = {">=": val >= thr, "==": val == thr, "<=": val <= thr}[op]
            for i in sel[~ok]:
                fails[i].append(code)
    d["margin_cap_amount"] = cap_pct_used * margin_c * horizon_m / 10000
    d["failed_rules_re"] = [";".join(sorted(x)) if x else None for x in fails]
    d["decision_re"] = np.where([len(x) == 0 for x in fails], "ELIGIBLE", "INELIGIBLE")
    return d
