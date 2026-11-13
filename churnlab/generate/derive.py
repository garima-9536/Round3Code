"""Step 6: derived values (statuses, dates, outcomes) computed from source event records."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import ids
from ..config import Config
from .master import METHODS, REGIONS, CHANNELS, SEGMENTS

END_TYPES = ["CANCELLED", "TERMINATED_NONPAYMENT"]


def derive_subscriptions(ev: pd.DataFrame, s, P) -> pd.DataFrame:
    ev = ev.sort_values(["subscription_id", "event_seq"])
    first = ev.groupby("subscription_id").first()
    last = ev.groupby("subscription_id").last()
    end = ev[ev["event_type"].isin(END_TYPES)].set_index("subscription_id")
    df = pd.DataFrame({"subscription_id": first.index})
    df = df.set_index("subscription_id")
    df["start_date"] = first["event_date"]
    df["initial_plan_code"] = first["to_plan_code"]
    df["current_plan_code"] = last["to_plan_code"]
    df["end_date"] = end["event_date"].reindex(df.index)
    df["status"] = end["event_type"].reindex(df.index).map({"CANCELLED": "CANCELLED", "TERMINATED_NONPAYMENT": "TERMINATED_NONPAYMENT"}).fillna("ACTIVE")
    df = df.reset_index()
    # static attributes from the sub-level arrays
    meta = pd.DataFrame({
        "subscription_id": s.sub_ids, "customer_id": P.cust_ids[s.cust], "is_primary": s.is_primary.astype(int),
        "product_type": np.where(s.is_primary, "CORE", "ADDON"),
        "payment_method": np.array(METHODS, dtype=object)[P.method[s.cust]],
    })
    df = meta.merge(df, on="subscription_id", how="left")
    df["billing_day"] = 1
    df["cohort_month"] = pd.to_datetime(df["start_date"]).dt.strftime("%Y-%m")
    cols = ["subscription_id", "customer_id", "product_type", "is_primary", "initial_plan_code", "current_plan_code", "start_date",
            "end_date", "status", "payment_method", "billing_day", "cohort_month"]
    return df[cols].sort_values("subscription_id").reset_index(drop=True)


def derive_customers(subs: pd.DataFrame, P) -> pd.DataFrame:
    prim = subs[subs["is_primary"] == 1].set_index("customer_id")
    df = pd.DataFrame({
        "customer_id": P.cust_ids,
        "segment": np.array(SEGMENTS, dtype=object)[P.seg],
        "region": np.array(REGIONS, dtype=object)[P.region],
        "acquisition_channel": np.array(CHANNELS, dtype=object)[P.chan],
        "marketing_consent": P.consent.astype(int),
    })
    df["signup_date"] = prim["start_date"].reindex(df["customer_id"]).to_numpy()
    df["status_as_of_data_end"] = np.where(prim["status"].reindex(df["customer_id"]).to_numpy() == "ACTIVE", "ACTIVE", "CHURNED")
    return df[["customer_id", "signup_date", "segment", "region", "acquisition_channel", "marketing_consent", "status_as_of_data_end"]]


def _terminal_events(ev: pd.DataFrame) -> pd.DataFrame:
    t = ev[ev["event_type"].isin(END_TYPES)]
    return t.set_index("subscription_id")


def churn_row_frame(cfg: Config, subs: pd.DataFrame, ev: pd.DataFrame, customer_ids) -> pd.DataFrame:
    """ChurnOutcome rows for the given customers, derived from subscription events."""
    pred = pd.Timestamp(cfg.prediction_date)
    hend = pd.Timestamp(cfg.horizon_end)
    prim = subs[subs["is_primary"] == 1].set_index("customer_id").loc[list(customer_ids)]
    term = _terminal_events(ev)
    sid = prim["subscription_id"].to_numpy()
    evd = term["event_date"].reindex(sid).to_numpy()
    evid = term["subscription_event_id"].reindex(sid).to_numpy()
    evtype = term["event_type"].reindex(sid).to_numpy()
    d = pd.Series(pd.to_datetime(evd))
    in_h = ((d >= pred) & (d < hend)).to_numpy()
    after = (d >= hend).to_numpy()
    has = d.notna().to_numpy()
    df = pd.DataFrame({
        "churn_outcome_id": [ids.churn(c) for c in prim.index],
        "customer_id": prim.index.to_numpy(),
        "subscription_id": sid,
        "prediction_date": cfg.prediction_date,
        "horizon_end_date": cfg.horizon_end,
        "churn_definition": "PRIMARY_SUBSCRIPTION_ENDED_IN_HORIZON",
        "churned_in_horizon": in_h.astype(int),
        "churn_event_id": np.where(has, evid, None),
        "churn_event_date": np.where(has, d.dt.date, None),
        "churn_type": np.where(has, np.where(evtype == "CANCELLED", "VOLUNTARY", "INVOLUNTARY"), None),
        "days_to_churn": pd.array(np.where(has, (d - pred).dt.days, -10**9), dtype="Int64"),
        "churned_after_horizon": after.astype(int),
    })
    df["days_to_churn"] = df["days_to_churn"].where(df["days_to_churn"] > -10**8, pd.NA)
    return df


def derive_churn_outcomes(cfg: Config, subs: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    prim = subs[subs["is_primary"] == 1]
    start = pd.to_datetime(prim["start_date"])
    end = pd.to_datetime(prim["end_date"])
    pred = pd.Timestamp(cfg.prediction_date)
    pop = (start < pred) & (end.isna() | (end >= pred))
    return churn_row_frame(cfg, subs, ev, prim.loc[pop, "customer_id"]).sort_values("customer_id").reset_index(drop=True)


def derive_retention(cfg: Config, contacts: pd.DataFrame, obs: pd.DataFrame, billing: pd.DataFrame, subs: pd.DataFrame,
                     first_number: int = 1) -> pd.DataFrame:
    """RetentionOutcome rows for `contacts`. `obs` has contact_id, viewed, accepted, accepted_at (source facts)."""
    pred = pd.Timestamp(cfg.prediction_date)
    hend = pd.Timestamp(cfg.horizon_end)
    c = contacts.merge(obs, on="contact_id", how="left")
    b = billing[["subscription_id", "event_date", "event_type", "amount", "service_cost", "offer_id"]].copy()
    b["event_date"] = pd.to_datetime(b["event_date"])
    win = b[(b["event_date"] >= pred) & (b["event_date"] < hend)]
    rev = win[win["event_type"] == "PAYMENT"].groupby("subscription_id")["amount"].sum()
    svc = win[win["event_type"] == "INVOICE"].groupby("subscription_id")["service_cost"].sum()
    cr = b[b["event_type"] == "CREDIT"].groupby(["subscription_id", "offer_id"])["amount"].agg(["sum", "count"])
    sub_end = subs.set_index("subscription_id")["end_date"]
    end = pd.to_datetime(sub_end.reindex(c["subscription_id"]).to_numpy())
    retained = (pd.isna(end) | (end >= hend)).astype(int)
    key = pd.MultiIndex.from_arrays([c["subscription_id"], c["offer_id"].fillna("")])
    cost = cr["sum"].reindex(key).fillna(0).to_numpy()
    cnt = cr["count"].reindex(key).fillna(0).astype(int).to_numpy()
    revenue = rev.reindex(c["subscription_id"]).fillna(0).to_numpy()
    service = svc.reindex(c["subscription_id"]).fillna(0).to_numpy()
    treat = (c["randomization_group"] == "TREATMENT").to_numpy()
    accepted = c["accepted"].fillna(0).astype(int).to_numpy()
    attributed = (treat & (accepted == 1) & (retained == 1)).astype(int)
    n = np.arange(first_number, first_number + len(c))
    out = pd.DataFrame({
        "retention_outcome_id": [ids.retention(int(k)) for k in c["contact_id"].str[-6:].astype(int)],
        "contact_id": c["contact_id"], "customer_id": c["customer_id"], "subscription_id": c["subscription_id"],
        "offer_id": c["offer_id"], "randomization_group": c["randomization_group"],
        "offer_viewed": c["viewed"].fillna(0).astype(int), "offer_accepted": accepted,
        "accepted_at": c["accepted_at"], "offer_cost": np.round(cost, 2), "credits_applied_count": cnt,
        "retained_at_horizon_end": retained, "revenue_collected_horizon": np.round(revenue, 2),
        "service_cost_horizon": np.round(service, 2), "net_margin_horizon": np.round(revenue - service, 2),
        "retention_attributed": attributed,
        "attributed_offer_id": np.where(attributed == 1, c["offer_id"], None),
    })
    return out


def build_audit(plans: pd.DataFrame, offers: pd.DataFrame, rules: pd.DataFrame, contacts: pd.DataFrame) -> pd.DataFrame:
    """Administrative actions that created the reference data and every manual eligibility override."""
    rows = []

    def at(d, days, hour, minute=0):
        return pd.Timestamp(d) + pd.Timedelta(days=days, hours=hour, minutes=minute)

    for r in plans.itertuples():
        rows.append((at(r.effective_from, -7, 9), "SYSTEM_ADMIN", "USR-001", "PRICE_VERSION_PUBLISHED", "plans", r.plan_id,
                     f"monthly_price={r.monthly_price:.2f}; unit_cost={r.unit_cost:.2f}"))
    for r in offers.itertuples():
        rows.append((at(r.valid_from, -7, 10), "MARKETING_OPS", "USR-101", "OFFER_PUBLISHED", "offers", r.offer_id, r.offer_name))
    for r in rules.itertuples():
        rows.append((at(r.effective_from, -3, 11), "SYSTEM_ADMIN", "USR-002", "RULE_ACTIVATED", "eligibility_rules", r.rule_id,
                     f"{r.rule_code} {r.operator} {r.threshold_value:g}"))
        if r.status == "RETIRED":
            rows.append((at(r.effective_to, 1, 12), "SYSTEM_ADMIN", "USR-002", "RULE_RETIRED", "eligibility_rules", r.rule_id,
                         f"superseded by {r.superseded_by_rule_id}"))
    ov = contacts[contacts["contact_source"] == "MANUAL_OVERRIDE"].sort_values("contact_id")
    for i, r in enumerate(ov.itertuples()):
        base = 101 if r.launched_by_role == "MARKETING_OPS" else 201
        rows.append((at(r.contact_date, -1, 15, i % 60), r.launched_by_role, f"USR-{base + i % 3}", "ELIGIBILITY_OVERRIDE",
                     "campaign_contacts", r.contact_id, "manual override of the eligibility engine; override_reason not recorded"))
    df = pd.DataFrame(rows, columns=["event_time", "actor_role", "actor_id", "action", "entity_table", "entity_id", "details"])
    df = df.sort_values(["event_time", "entity_id"], kind="stable").reset_index(drop=True)
    df["audit_id"] = [f"AUD-{i:06d}" for i in range(1, len(df) + 1)]
    df["event_time"] = df["event_time"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return df

