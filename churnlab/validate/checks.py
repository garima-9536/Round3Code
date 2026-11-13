"""Step 8: validation suite.

Severity: ERROR = structural / arithmetic integrity (must be zero);  RULE = business-rule exception
(expected only for the injected, labelled anomalies). The ground truth is read ONLY in `reconcile_with_ground_truth`
to score detection - never by the checks themselves.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ..schema import ISSUE_TYPES, RELATIONSHIPS, T as SCHEMA
from .coverage import boundary_md, boundary_report, distribution_acceptance, distribution_md, distribution_report
from .eligibility import PLAN_RANK, price_asof, recompute

TOL = 0.0051


# ----------------------------------------------------------------------------------------------------------
def load_tables(data_dir: Path) -> dict:
    tables = {}
    for name, t in SCHEMA.items():
        df = pd.read_csv(Path(data_dir) / f"{name}.csv", dtype=str, keep_default_na=False, na_values=[""])
        for f in t.fields:
            s = df[f.name]
            if f.type in ("int", "bool"):
                df[f.name] = pd.to_numeric(s, errors="coerce").astype("Int64")
            elif f.type == "decimal":
                df[f.name] = pd.to_numeric(s, errors="coerce")
            elif f.type == "date":
                df[f.name] = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
            elif f.type == "datetime":
                df[f.name] = pd.to_datetime(s, format="%Y-%m-%d %H:%M:%S", errors="coerce")
        tables[name] = df
    return tables


class Collector:
    def __init__(self):
        self.parts = []
        self.checks_run = {}

    def ran(self, check_id, description):
        self.checks_run.setdefault(check_id, {"description": description, "violations": 0})

    def add(self, check_id, severity, table, entity_id, detail, customer_id=None):
        eid = pd.Series(entity_id).reset_index(drop=True).astype(str)
        if len(eid) == 0:
            return
        det = detail if isinstance(detail, str) else pd.Series(detail).reset_index(drop=True)
        cid = None if customer_id is None else pd.Series(customer_id).reset_index(drop=True)
        self.parts.append(pd.DataFrame({"check_id": check_id, "severity": severity, "table": table, "entity_id": eid,
                                        "customer_id": cid, "detail": det}))
        if check_id in self.checks_run:
            self.checks_run[check_id]["violations"] += len(eid)

    def frame(self) -> pd.DataFrame:
        if not self.parts:
            return pd.DataFrame(columns=["check_id", "severity", "table", "entity_id", "customer_id", "detail"])
        return pd.concat(self.parts, ignore_index=True)


def _pk(df, t):
    return df[t.pk[0]] if len(t.pk) == 1 else df[t.pk].astype(str).agg("|".join, axis=1)


# ---- structural -----------------------------------------------------------------------------------------
def check_structure(tb, C: Collector):
    C.ran("S01", "primary-key uniqueness and non-null")
    C.ran("S02", "foreign-key integrity")
    C.ran("S03", "required fields, enums, ranges, id patterns, parseable types")
    for name, t in SCHEMA.items():
        df = tb[name]
        pk = _pk(df, t)
        dup = pk.duplicated(keep=False)
        C.add("S01", "ERROR", name, pk[dup], "duplicate primary key")
        C.add("S01", "ERROR", name, pk[df[t.pk].isna().any(axis=1)], "null primary key")
        for f in t.fields:
            s = df[f.name]
            ent = pk
            if f.required:
                C.add("S03", "ERROR", name, ent[s.isna()], f"{f.name}: required value missing/unparseable")
            nn = s.notna()
            if f.allowed:
                bad = nn & ~s.isin(f.allowed)
                C.add("S03", "ERROR", name, ent[bad], f"{f.name}: value not in allowed set")
            if f.pattern:
                bad = nn & ~s.astype(str).str.match(f.pattern)
                C.add("S03", "ERROR", name, ent[bad], f"{f.name}: id/pattern mismatch")
            if f.min is not None and f.type in ("int", "decimal"):
                C.add("S03", "ERROR", name, ent[nn & (s < f.min)], f"{f.name}: below minimum {f.min}")
            if f.max is not None and f.type in ("int", "decimal"):
                C.add("S03", "ERROR", name, ent[nn & (s > f.max)], f"{f.name}: above maximum {f.max}")
    for r in RELATIONSHIPS:
        child, parent = tb[r.child], tb[r.parent]
        vals = child[r.child_col]
        miss = vals.notna() & ~vals.isin(set(parent[r.parent_col].dropna()))
        C.add("S02", "ERROR", r.child, _pk(child, SCHEMA[r.child])[miss], f"FK {r.child_col} -> {r.parent}.{r.parent_col} not found")


# ---- dates / lifecycle -----------------------------------------------------------------------------------
def check_dates_lifecycle(tb, cfg, C: Collector):
    for cid, desc in [("D01", "date ordering across entities"), ("L01", "lifecycle transitions"), ("C01", "arm/offer consistency")]:
        C.ran(cid, desc)
    subs = tb["subscriptions"].set_index("subscription_id")
    ev = tb["subscription_events"].copy()
    pred = pd.Timestamp(cfg["prediction_date"])

    s = tb["subscriptions"]
    bad = s["end_date"].notna() & (s["end_date"] < s["start_date"])
    C.add("D01", "ERROR", "subscriptions", s["subscription_id"][bad], "end_date before start_date")
    p = tb["plans"]
    C.add("D01", "ERROR", "plans", p["plan_id"][p["effective_to"].notna() & (p["effective_to"] < p["effective_from"])], "effective_to < effective_from")
    o = tb["offers"]
    C.add("D01", "ERROR", "offers", o["offer_id"][o["valid_to"] < o["valid_from"]], "valid_to < valid_from")

    ev = ev.sort_values(["subscription_id", "event_seq"])
    ev["start"] = subs["start_date"].reindex(ev["subscription_id"]).to_numpy()
    ev["end"] = subs["end_date"].reindex(ev["subscription_id"]).to_numpy()
    eid = ev["subscription_event_id"]
    C.add("D01", "ERROR", "subscription_events", eid[ev["event_date"] < ev["start"]], "event before subscription start")
    C.add("D01", "ERROR", "subscription_events", eid[ev["end"].notna() & (ev["event_date"] > ev["end"])], "event after subscription end")
    g = ev.groupby("subscription_id")
    ev["prev_date"] = g["event_date"].shift()
    ev["prev_to"] = g["to_plan_code"].shift()
    ev["prev_plan_id"] = g["plan_id"].shift()
    ev["seq_expected"] = g.cumcount() + 1
    C.add("D01", "ERROR", "subscription_events", eid[ev["prev_date"].notna() & (ev["event_date"] < ev["prev_date"])], "events not chronological")
    C.add("L01", "ERROR", "subscription_events", eid[ev["event_seq"] != ev["seq_expected"]], "event_seq not contiguous 1..n")
    first_bad = ev["event_seq"].eq(1) & (ev["event_type"] != "ACTIVATED")
    C.add("L01", "ERROR", "subscription_events", eid[first_bad], "first event is not ACTIVATED")
    C.add("L01", "ERROR", "subscription_events", eid[ev["event_seq"].gt(1) & ev["event_type"].eq("ACTIVATED")], "ACTIVATED repeated")
    term = ev["event_type"].isin(["CANCELLED", "TERMINATED_NONPAYMENT"])
    last = ev["event_seq"].eq(g["event_seq"].transform("max"))
    C.add("L01", "ERROR", "subscription_events", eid[term & ~last], "events after terminal event")
    C.add("L01", "ERROR", "subscription_events", eid[ev["event_type"].isin(["PLAN_UPGRADE", "PLAN_DOWNGRADE"]) & (ev["from_plan_code"] != ev["prev_to"])],
          "plan change from_plan does not match previous plan")
    rk = lambda x: x.map(PLAN_RANK)
    up = ev["event_type"].eq("PLAN_UPGRADE") & (rk(ev["to_plan_code"]) <= rk(ev["from_plan_code"]))
    dn = ev["event_type"].eq("PLAN_DOWNGRADE") & (rk(ev["to_plan_code"]) >= rk(ev["from_plan_code"]))
    C.add("L01", "ERROR", "subscription_events", eid[up | dn], "upgrade/downgrade direction inconsistent with plan rank")
    pc = ev["event_type"].eq("PRICE_CHANGE") & ((ev["to_plan_code"] != ev["prev_to"]) | (ev["plan_id"] == ev["prev_plan_id"]))
    C.add("L01", "ERROR", "subscription_events", eid[pc], "PRICE_CHANGE must keep the plan and move to a new price version")
    C.add("L01", "ERROR", "subscription_events", eid[ev["reason_code"].notna() & ~term], "reason_code on a non-terminal event")
    C.add("L01", "ERROR", "subscription_events", eid[term & ev["reason_code"].isna()], "terminal event without reason_code")
    cb = ev.merge(tb["subscriptions"][["subscription_id", "product_type"]], on="subscription_id")
    C.add("L01", "ERROR", "subscription_events", cb["subscription_event_id"][(cb["product_type"] == "ADDON") != (cb["to_plan_code"] == "ADDON")],
          "ADDON/CORE plan mismatch")
    # plan_id validity at event date
    pl = tb["plans"].set_index("plan_id")
    pf = pl["effective_from"].reindex(ev["plan_id"]).to_numpy()
    pt = pl["effective_to"].reindex(ev["plan_id"]).to_numpy()
    pcode = pl["plan_code"].reindex(ev["plan_id"]).to_numpy()
    badp = (ev["event_date"].to_numpy() < pf) | (pd.notna(pt) & (ev["event_date"].to_numpy() > pt)) | (pcode != ev["to_plan_code"].to_numpy())
    C.add("L01", "ERROR", "subscription_events", eid[badp], "plan_id not effective on event date / differs from to_plan_code")

    # usage
    u = tb["usage_snapshots"]
    us = u.merge(tb["subscriptions"][["subscription_id", "start_date", "end_date"]], on="subscription_id", how="left")
    uid = us["snapshot_id"]
    first_of_month = us["snapshot_month"].dt.day == 1
    C.add("D01", "ERROR", "usage_snapshots", uid[~first_of_month], "snapshot_month not first of month")
    sm_start = us["start_date"].dt.to_period("M").dt.to_timestamp()
    C.add("D01", "ERROR", "usage_snapshots", uid[us["snapshot_month"] < sm_start], "snapshot before subscription start month")
    C.add("D01", "ERROR", "usage_snapshots", uid[us["end_date"].notna() & (us["snapshot_month"] > us["end_date"])], "snapshot after subscription end")
    C.add("D01", "ERROR", "usage_snapshots", uid[us["active_days"] > us["days_in_service"]], "active_days > days_in_service")
    C.add("D01", "ERROR", "usage_snapshots", uid[us["active_days"] > us["sessions"]], "active_days > sessions")
    dup = u.duplicated(["subscription_id", "snapshot_month"], keep="first")
    C.add("S01", "ERROR", "usage_snapshots", u["snapshot_id"][dup], "duplicate (subscription, month) snapshot")

    # billing
    b = tb["billing_events"].merge(tb["subscriptions"][["subscription_id", "start_date", "end_date"]], on="subscription_id", how="left")
    bid = b["billing_event_id"]
    C.add("D01", "ERROR", "billing_events", bid[b["event_date"] < b["start_date"]], "billing event before subscription start")
    C.add("D01", "ERROR", "billing_events", bid[b["end_date"].notna() & (b["event_date"] > b["end_date"])], "billing event after subscription end")
    nonin = b["event_type"] != "INVOICE"
    C.add("L01", "ERROR", "billing_events", bid[nonin & b["invoice_id"].isna()], "non-invoice event without invoice_id")
    C.add("L01", "ERROR", "billing_events", bid[~nonin & b["invoice_id"].notna()], "INVOICE with invoice_id")
    C.add("L01", "ERROR", "billing_events", bid[(b["event_type"] == "CREDIT") != b["offer_id"].notna()], "offer_id only (and always) on CREDIT")
    C.add("L01", "ERROR", "billing_events", bid[(b["event_type"] == "PAYMENT_FAILED") != b["failure_reason"].notna()], "failure_reason only on PAYMENT_FAILED")
    inv = tb["billing_events"].set_index("billing_event_id")
    ref = b[nonin & b["invoice_id"].notna()]
    refd = inv["event_date"].reindex(ref["invoice_id"]).to_numpy()
    refs = inv["subscription_id"].reindex(ref["invoice_id"]).to_numpy()
    refp = inv["billing_period"].reindex(ref["invoice_id"]).to_numpy()
    C.add("D01", "ERROR", "billing_events", ref["billing_event_id"][(ref["event_date"].to_numpy() < refd) | (refs != ref["subscription_id"].to_numpy()) | (refp != ref["billing_period"].to_numpy())],
          "event precedes / mismatches its invoice")

    # support
    c = tb["support_cases"].merge(tb["subscriptions"][["subscription_id", "start_date", "end_date"]], on="subscription_id", how="left")
    cid = c["case_id"]
    for col in ("first_response_at", "escalated_at", "resolved_at"):
        C.add("D01", "ERROR", "support_cases", cid[c[col].notna() & (c[col] < c["opened_at"])], f"{col} before opened_at")
    C.add("D01", "ERROR", "support_cases", cid[c["first_response_at"].notna() & c["resolved_at"].notna() & (c["first_response_at"] > c["resolved_at"])], "first response after resolution")
    od = c["opened_at"].dt.normalize()
    C.add("D01", "ERROR", "support_cases", cid[od < c["start_date"]], "case opened before subscription start")
    C.add("D01", "ERROR", "support_cases", cid[c["end_date"].notna() & (od >= c["end_date"])], "case opened on/after subscription end")
    st = c["status"]
    C.add("L01", "ERROR", "support_cases", cid[(st == "RESOLVED") != c["resolved_at"].notna()], "status RESOLVED iff resolved_at set")
    C.add("L01", "ERROR", "support_cases", cid[(st == "ESCALATED") & c["escalated_at"].isna()], "ESCALATED without escalated_at")
    C.add("L01", "ERROR", "support_cases", cid[c["csat_score"].notna() & (st != "RESOLVED")], "csat on unresolved case")

    # campaign
    cc = tb["campaign_contacts"]
    C.add("D01", "ERROR", "campaign_contacts", cc["contact_id"][cc["contact_date"] < pred], "contact before prediction date")
    ctrl = cc["randomization_group"] == "CONTROL"
    C.add("C01", "ERROR", "campaign_contacts", cc["contact_id"][ctrl & (cc["offer_id"].notna() | (cc["contact_status"] != "HOLDOUT") | cc["channel"].notna())], "CONTROL must be HOLDOUT with no offer/channel")
    C.add("C01", "ERROR", "campaign_contacts", cc["contact_id"][~ctrl & (cc["offer_id"].isna() | (cc["contact_status"] == "HOLDOUT") | cc["channel"].isna())], "TREATMENT must carry offer and channel")
    r = tb["retention_outcomes"].merge(cc[["contact_id", "contact_date", "randomization_group", "offer_id", "customer_id", "subscription_id"]],
                                       on="contact_id", suffixes=("", "_c"), how="left")
    C.add("D01", "ERROR", "retention_outcomes", r["retention_outcome_id"][r["accepted_at"].notna() & (r["accepted_at"] < r["contact_date"])], "accepted before contact")
    C.add("C01", "ERROR", "retention_outcomes", r["retention_outcome_id"][(r["offer_accepted"] == 1) & (r["offer_viewed"] != 1)], "accepted without viewing")
    C.add("C01", "ERROR", "retention_outcomes", r["retention_outcome_id"][(r["offer_accepted"] == 1) != r["accepted_at"].notna()], "accepted_at iff accepted")
    C.add("C01", "ERROR", "retention_outcomes", r["retention_outcome_id"][(r["randomization_group"] != r["randomization_group_c"]) | (r["customer_id"] != r["customer_id_c"]) | (r["subscription_id"] != r["subscription_id_c"]) | ((r["offer_id"].fillna("") != r["offer_id_c"].fillna("")))],
          "retention row disagrees with its contact")
    C.add("C01", "ERROR", "retention_outcomes", r["retention_outcome_id"][(r["randomization_group"] == "CONTROL") & ((r["offer_viewed"] == 1) | (r["offer_accepted"] == 1))], "CONTROL cannot view/accept")


# ---- arithmetic / derived ------------------------------------------------------------------------------------
def check_arithmetic(tb, cfg, C: Collector):
    for cid, desc in [("A01", "usage_hours = sessions x avg minutes / 60"), ("A02", "invoice reconciliation (invoice = credits + payments + write-offs)"),
                      ("A03", "invoice amount / service cost match plan price list"), ("A04", "subscription & customer fields derive from events"),
                      ("A05", "churn outcomes derive from subscription events"), ("A06", "retention outcome values derive from billing/events"),
                      ("A07", "support resolution_hours = resolved_at - opened_at"), ("A09", "usage plan_code = plan in force")]:
        C.ran(cid, desc)
    u = tb["usage_snapshots"]
    hrs = (u["sessions"] * u["avg_session_minutes"] / 60).round(2)
    C.add("A01", "ERROR", "usage_snapshots", u["snapshot_id"][(hrs - u["usage_hours"]).abs() > TOL], "usage_hours not derived from sessions x minutes")

    b = tb["billing_events"]
    inv = b[b["event_type"] == "INVOICE"].set_index("billing_event_id")
    sums = b[b["event_type"] != "INVOICE"].pivot_table(index="invoice_id", columns="event_type", values="amount", aggfunc="sum", fill_value=0.0)
    for col in ("CREDIT", "PAYMENT", "WRITE_OFF"):
        if col not in sums:
            sums[col] = 0.0
    sm = sums.reindex(inv.index).fillna(0.0)
    bal = inv["amount"] - sm["CREDIT"] - sm["PAYMENT"] - sm["WRITE_OFF"]
    C.add("A02", "ERROR", "billing_events", inv.index[bal.abs() > TOL], pd.Series([f"balance {x:.2f}" for x in bal[bal.abs() > TOL]]))
    # a paid invoice with write-off, or failed attempts not leading anywhere
    pf = b[b["event_type"] == "PAYMENT_FAILED"].groupby("invoice_id").size().reindex(inv.index).fillna(0)
    pay = b[b["event_type"] == "PAYMENT"].groupby("invoice_id").size().reindex(inv.index).fillna(0)
    wo = b[b["event_type"] == "WRITE_OFF"].groupby("invoice_id").size().reindex(inv.index).fillna(0)
    C.add("A02", "ERROR", "billing_events", inv.index[(pay > 1) | (wo > 1) | ((pay > 0) & (wo > 0))], "invoice has multiple/conflicting settlements")

    # plan in force at the invoice date, from subscription events
    ev = tb["subscription_events"][["subscription_id", "event_date", "to_plan_code", "event_seq"]].sort_values("event_date", kind="stable")
    q = inv.reset_index()[["billing_event_id", "subscription_id", "event_date", "amount", "service_cost"]].sort_values("event_date", kind="stable")
    m = pd.merge_asof(q, ev, left_on="event_date", right_on="event_date", by="subscription_id", direction="backward")
    pl = tb["plans"].copy()
    parts = []
    for code, grp in m.groupby("to_plan_code"):
        pp = pl[pl["plan_code"] == code].sort_values("effective_from")
        g2 = pd.merge_asof(grp.sort_values("event_date"), pp[["effective_from", "effective_to", "monthly_price", "unit_cost"]],
                           left_on="event_date", right_on="effective_from", direction="backward")
        parts.append(g2)
    m2 = pd.concat(parts)
    bad = m2["monthly_price"].isna() | ((m2["amount"] - m2["monthly_price"]).abs() > TOL) | ((m2["service_cost"] - m2["unit_cost"]).abs() > TOL) | \
        (m2["effective_to"].notna() & (m2["event_date"] > m2["effective_to"]))
    C.add("A03", "ERROR", "billing_events", m2["billing_event_id"][bad], "invoice amount/service_cost differ from plan price in force")

    # usage plan code vs plan in force (month start, or start date for the first month)
    us = u.merge(tb["subscriptions"][["subscription_id", "start_date"]], on="subscription_id")
    us["key"] = np.maximum(us["snapshot_month"].to_numpy(), us["start_date"].to_numpy())
    um = pd.merge_asof(us.sort_values("key"), ev.sort_values("event_date"), left_on="key", right_on="event_date", by="subscription_id", direction="backward")
    C.add("A09", "ERROR", "usage_snapshots", um["snapshot_id"][um["plan_code"] != um["to_plan_code"]], "usage plan_code differs from plan in force")

    # subscriptions / customers derived from events
    se = tb["subscription_events"].sort_values(["subscription_id", "event_seq"])
    first = se.groupby("subscription_id").first()
    lastr = se.groupby("subscription_id").last()
    termr = se[se["event_type"].isin(["CANCELLED", "TERMINATED_NONPAYMENT"])].set_index("subscription_id")
    s = tb["subscriptions"].set_index("subscription_id")
    sid = s.index.to_series()
    C.add("A04", "ERROR", "subscriptions", sid[s["start_date"] != first["event_date"].reindex(s.index)], "start_date != ACTIVATED date")
    C.add("A04", "ERROR", "subscriptions", sid[s["initial_plan_code"] != first["to_plan_code"].reindex(s.index)], "initial_plan_code != ACTIVATED plan")
    C.add("A04", "ERROR", "subscriptions", sid[s["current_plan_code"] != lastr["to_plan_code"].reindex(s.index)], "current_plan_code != last event plan")
    te = termr["event_date"].reindex(s.index)
    C.add("A04", "ERROR", "subscriptions", sid[(s["end_date"].fillna(pd.Timestamp("1900-01-01")) != te.fillna(pd.Timestamp("1900-01-01")))], "end_date != terminal event date")
    exp_status = termr["event_type"].reindex(s.index).fillna("ACTIVE")
    C.add("A04", "ERROR", "subscriptions", sid[s["status"] != exp_status], "status != terminal event type")
    C.add("A04", "ERROR", "subscriptions", sid[s["cohort_month"] != s["start_date"].dt.strftime("%Y-%m")], "cohort_month != start month")
    prim = tb["subscriptions"][tb["subscriptions"]["is_primary"] == 1].set_index("customer_id")
    cu = tb["customers"].set_index("customer_id")
    C.add("A04", "ERROR", "customers", cu.index.to_series()[cu["signup_date"] != prim["start_date"].reindex(cu.index)], "signup_date != primary start")
    exp_c = np.where(prim["status"].reindex(cu.index) == "ACTIVE", "ACTIVE", "CHURNED")
    C.add("A04", "ERROR", "customers", cu.index.to_series()[cu["status_as_of_data_end"].to_numpy() != exp_c], "customer status != primary subscription status")
    missing_primary = cu.index.difference(prim.index)
    C.add("A04", "ERROR", "customers", pd.Series(missing_primary), "customer without primary subscription")
    sub_ids = set(tb["subscriptions"]["subscription_id"])
    C.add("A04", "ERROR", "subscriptions", tb["subscriptions"]["subscription_id"][tb["subscriptions"]["subscription_id"] !=
          ("SUB-" + tb["subscriptions"]["customer_id"] + "-" + tb["subscriptions"].groupby("customer_id").cumcount().add(1).astype(str).str.zfill(2))],
          "subscription_id not SUB-<customer>-NN in order")

    # churn outcomes
    pred = pd.Timestamp(cfg["prediction_date"])
    hend = pred + pd.DateOffset(months=int(cfg["horizon_months"]))
    co = tb["churn_outcomes"]
    C.add("A05", "ERROR", "churn_outcomes", co["churn_outcome_id"][(co["prediction_date"] != pred) | (co["horizon_end_date"] != hend)], "prediction/horizon dates differ from configuration")
    pe = tb["subscriptions"].set_index("subscription_id")
    start = pe["start_date"].reindex(co["subscription_id"]).to_numpy()
    end = pe["end_date"].reindex(co["subscription_id"]).to_numpy()
    scored = co[(co["churn_event_date"].isna() | (co["churn_event_date"] >= pred))].copy()   # T01 handles earlier rows
    ends = pe["end_date"].reindex(scored["subscription_id"]).to_numpy()
    exp = pd.notna(ends) & (ends >= pred) & (ends < hend)
    C.add("A05", "ERROR", "churn_outcomes", scored["churn_outcome_id"][scored["churned_in_horizon"].to_numpy() != exp.astype(int)], "churned_in_horizon != lifecycle")
    C.add("A05", "ERROR", "churn_outcomes", scored["churn_outcome_id"][(scored["churn_event_date"].fillna(pd.Timestamp("1900-01-01")).to_numpy() != np.where(pd.notna(ends), ends, np.datetime64("1900-01-01")))],
          "churn_event_date != subscription end_date")
    exp_after = pd.notna(ends) & (ends >= hend)
    C.add("A05", "ERROR", "churn_outcomes", scored["churn_outcome_id"][scored["churned_after_horizon"].to_numpy() != exp_after.astype(int)], "churned_after_horizon wrong")
    dtc = (scored["churn_event_date"] - pred).dt.days
    C.add("A05", "ERROR", "churn_outcomes", scored["churn_outcome_id"][scored["churn_event_date"].notna() & (scored["days_to_churn"].astype("float") != dtc)], "days_to_churn wrong")
    termmap = termr["event_type"].reindex(scored["subscription_id"]).map({"CANCELLED": "VOLUNTARY", "TERMINATED_NONPAYMENT": "INVOLUNTARY"})
    C.add("A05", "ERROR", "churn_outcomes", scored["churn_outcome_id"][scored["churn_type"].fillna("").to_numpy() != termmap.fillna("").to_numpy()], "churn_type != terminal event")
    # completeness: every primary subscription alive at the prediction date has exactly one label
    ps = tb["subscriptions"][(tb["subscriptions"]["is_primary"] == 1)]
    alive = ps[(ps["start_date"] < pred) & (ps["end_date"].isna() | (ps["end_date"] >= pred))]
    miss = alive[~alive["customer_id"].isin(set(co["customer_id"]))]
    C.add("A05", "ERROR", "churn_outcomes", miss["customer_id"], "scored customer has no ChurnOutcome")

    # support
    cs = tb["support_cases"]
    rh = ((cs["resolved_at"] - cs["opened_at"]).dt.total_seconds() / 3600).round(2)
    C.add("A07", "ERROR", "support_cases", cs["case_id"][cs["resolved_at"].notna() & ((rh - cs["resolution_hours"]).abs() > TOL)], "resolution_hours != resolved_at - opened_at")

    # retention outcomes
    r = tb["retention_outcomes"]
    bb = b.copy()
    win = bb[(bb["event_date"] >= pred) & (bb["event_date"] < hend)]
    rev = win[win["event_type"] == "PAYMENT"].groupby("subscription_id")["amount"].sum()
    svc = win[win["event_type"] == "INVOICE"].groupby("subscription_id")["service_cost"].sum()
    cr = bb[bb["event_type"] == "CREDIT"].groupby(["subscription_id", "offer_id"])["amount"].agg(["sum", "count"])
    key = pd.MultiIndex.from_arrays([r["subscription_id"], r["offer_id"].fillna("")])
    cost = cr["sum"].reindex(key).fillna(0).to_numpy()
    cnt = cr["count"].reindex(key).fillna(0).to_numpy()
    rid = r["retention_outcome_id"]
    C.add("A06", "ERROR", "retention_outcomes", rid[np.abs(cost - r["offer_cost"].to_numpy()) > TOL], "offer_cost != sum(CREDIT)")
    C.add("A06", "ERROR", "retention_outcomes", rid[cnt != r["credits_applied_count"].to_numpy()], "credits_applied_count != count(CREDIT)")
    rv = rev.reindex(r["subscription_id"]).fillna(0).to_numpy()
    sv = svc.reindex(r["subscription_id"]).fillna(0).to_numpy()
    C.add("A06", "ERROR", "retention_outcomes", rid[np.abs(rv - r["revenue_collected_horizon"].to_numpy()) > TOL], "revenue_collected_horizon mismatch")
    C.add("A06", "ERROR", "retention_outcomes", rid[np.abs(sv - r["service_cost_horizon"].to_numpy()) > TOL], "service_cost_horizon mismatch")
    C.add("A06", "ERROR", "retention_outcomes", rid[np.abs(rv - sv - r["net_margin_horizon"].to_numpy()) > TOL], "net_margin_horizon != revenue - service cost")
    endr = pe["end_date"].reindex(r["subscription_id"]).to_numpy()
    ret = (pd.isna(endr) | (endr >= hend)).astype(int)
    C.add("A06", "ERROR", "retention_outcomes", rid[ret != r["retained_at_horizon_end"].to_numpy().astype(int)], "retained_at_horizon_end != lifecycle")
    C.add("A06", "ERROR", "retention_outcomes", rid[(r["offer_cost"] > 0) & (r["offer_accepted"] != 1)], "offer cost without acceptance")


# ---- business rules ---------------------------------------------------------------------------------------------
def check_business(tb, cfg, C: Collector):
    for cid, desc in [("B01", "offers sent only to customers eligible by the effective rules"), ("B02", "eligibility decision log reproducible"),
                      ("B03", "offer cost within margin cap for accepted offers"),
                      ("X01", "treatment/control leakage (customer in both arms)"), ("X02", "one contact per customer per campaign"),
                      ("X03", "a retained customer is attributed to at most one offer"), ("T01", "churn label must not precede the prediction date")]:
        C.ran(cid, desc)
    ev = tb["eligibility_evaluations"]
    rc = recompute(tb, cfg, ev[["customer_id", "offer_id"]])
    ids_ = ev["evaluation_id"].reset_index(drop=True)
    bad = (rc["decision_re"].to_numpy() != ev["decision"].to_numpy()) | \
          ((rc["offer_cost"].to_numpy() - ev["offer_cost"].to_numpy()).__abs__() > TOL) | \
          ((rc["monthly_margin"].to_numpy() - ev["monthly_margin"].to_numpy()).__abs__() > TOL) | \
          (rc["tenure_months"].to_numpy() != ev["tenure_months"].to_numpy()) | \
          (rc["failed_payments_window"].to_numpy() != ev["failed_payments_window"].to_numpy())
    C.add("B02", "ERROR", "eligibility_evaluations", ids_[bad], "decision/inputs differ from independent recomputation")

    cc = tb["campaign_contacts"]
    sent = cc[cc["offer_id"].notna()]
    rcs = recompute(tb, cfg, sent[["customer_id", "offer_id"]])
    inel = (rcs["decision_re"] == "INELIGIBLE").to_numpy()
    det = ("ineligible for offer: " + rcs["failed_rules_re"].fillna("")).reset_index(drop=True)
    C.add("B01", "RULE", "campaign_contacts", sent["contact_id"].reset_index(drop=True)[inel], det[inel], customer_id=sent["customer_id"].reset_index(drop=True)[inel])

    r = tb["retention_outcomes"]
    acc = r[r["offer_accepted"] == 1]
    ra = recompute(tb, cfg, acc[["customer_id", "offer_id"]])
    over = (acc["offer_cost"].to_numpy() - ra["offer_cost"].to_numpy()) > TOL
    C.add("B03", "ERROR", "retention_outcomes", acc["retention_outcome_id"][over], "actual offer cost exceeds planned cost at evaluation")

    # duplicates / leakage
    cc = cc.sort_values("contact_id")
    grp = cc.groupby(["customer_id", "campaign_id"])
    n = grp["contact_id"].transform("size")
    rank = grp.cumcount()
    two_arms = grp["randomization_group"].transform("nunique") > 1
    later = (n > 1) & (rank > 0)
    C.add("X01", "RULE", "campaign_contacts", cc["contact_id"][later & two_arms], "customer is in both TREATMENT and CONTROL for the campaign", customer_id=cc["customer_id"][later & two_arms])
    C.add("X02", "RULE", "campaign_contacts", cc["contact_id"][later], "more than one contact for the same customer in the campaign", customer_id=cc["customer_id"][later])

    ra = r.sort_values("contact_id")
    attr = ra[ra["retention_attributed"] == 1]
    a_rank = attr.groupby("customer_id").cumcount()
    dup_attr = a_rank > 0
    bad_attr = (attr["offer_accepted"] != 1) | (attr["retained_at_horizon_end"] != 1) | (attr["randomization_group"] != "TREATMENT")
    mask = dup_attr | bad_attr
    C.add("X03", "RULE", "campaign_contacts", attr["contact_id"][mask], "retention attributed to more than one offer / without acceptance", customer_id=attr["customer_id"][mask])
    C.add("X03", "ERROR", "retention_outcomes", ra["retention_outcome_id"][(ra["retention_attributed"] == 1) != ra["attributed_offer_id"].notna()], "attributed_offer_id must be set iff attributed")

    co = tb["churn_outcomes"]
    pred = pd.Timestamp(cfg["prediction_date"])
    early = co["churn_event_date"].notna() & (co["churn_event_date"] < pred)
    C.add("T01", "RULE", "churn_outcomes", co["churn_outcome_id"][early], "churn_event_date precedes prediction_date", customer_id=co["customer_id"][early])


# ---- prospects (pre-customer funnel) --------------------------------------------------------------------------------
def check_prospects(tb, cfg, C: Collector):
    C.ran("L02", "prospect funnel lifecycle (CREATED first, single terminal event last, trial once)")
    C.ran("A08", "prospect status/closing fields derive from events and agree with the customer record")
    pr = tb["prospects"]
    pe = tb["prospect_events"].sort_values(["prospect_id", "event_seq"])
    cu = tb["customers"].set_index("customer_id")
    data_end = pd.Timestamp(cfg["window_start"]) + pd.DateOffset(months=int(cfg["n_months"])) - pd.Timedelta(days=1)
    g = pe.groupby("prospect_id")
    eid = pe["prospect_event_id"]
    typ = pe["event_type"]
    term = typ.isin(["CONVERTED", "LOST"])
    C.add("L02", "ERROR", "prospect_events", eid[pe["event_seq"] != g.cumcount() + 1], "event_seq not contiguous 1..n")
    C.add("L02", "ERROR", "prospect_events", eid[(pe["event_seq"] == 1) != (typ == "CREATED")], "CREATED must be exactly the first event")
    C.add("L02", "ERROR", "prospect_events", eid[term & (pe["event_seq"] != g["event_seq"].transform("max"))], "events after the terminal event")
    C.add("L02", "ERROR", "prospect_events", eid[term & term.groupby(pe["prospect_id"]).cumsum().gt(1)], "more than one terminal event")
    C.add("L02", "ERROR", "prospect_events", eid[(typ == "TRIAL_STARTED") & pe.duplicated(["prospect_id", "event_type"], keep="first")], "trial started more than once")
    C.add("L02", "ERROR", "prospect_events", eid[(g["event_date"].shift().notna()) & (pe["event_date"] < g["event_date"].shift())], "events not chronological")
    C.add("L02", "ERROR", "prospect_events", eid[(typ == "LOST") != pe["reason_code"].notna()], "reason_code iff LOST")
    C.add("L02", "ERROR", "prospect_events", eid[(typ == "CONVERTED") != pe["customer_id"].notna()], "customer_id iff CONVERTED")
    C.add("D01", "ERROR", "prospect_events", eid[pe["event_date"] > data_end], "prospect event after data end")

    t = pe[term].set_index("prospect_id")
    pid = pr["prospect_id"]
    exp_status = t["event_type"].reindex(pid).fillna("OPEN").to_numpy()
    C.add("A08", "ERROR", "prospects", pid[pr["status"].to_numpy() != exp_status], "status != terminal event")
    sent = pd.Timestamp("1900-01-01")
    C.add("A08", "ERROR", "prospects", pid[pr["closed_date"].fillna(sent).to_numpy() != t["event_date"].reindex(pid).fillna(sent).to_numpy()], "closed_date != terminal event date")
    C.add("A08", "ERROR", "prospects", pid[pr["converted_customer_id"].fillna("").to_numpy() != t["customer_id"].reindex(pid).fillna("").to_numpy()], "converted_customer_id != CONVERTED event customer")
    C.add("A08", "ERROR", "prospects", pid[pr["lost_reason"].fillna("").to_numpy() != t["reason_code"].reindex(pid).fillna("").to_numpy()], "lost_reason != LOST event reason")
    first = pe[typ == "CREATED"].set_index("prospect_id")["event_date"].reindex(pid).to_numpy()
    C.add("A08", "ERROR", "prospects", pid[pr["created_date"].to_numpy() != first], "created_date != CREATED event date")
    conv = pr[pr["converted_customer_id"].notna()]
    C.add("A08", "ERROR", "prospects", conv["prospect_id"][conv["converted_customer_id"].duplicated(keep=False)], "customer converted from more than one prospect")
    c2 = conv[conv["converted_customer_id"].isin(cu.index)]
    k = cu.reindex(c2["converted_customer_id"])
    bad = (k["acquisition_channel"].to_numpy() != c2["source_channel"].to_numpy()) | (k["segment"].to_numpy() != c2["segment"].to_numpy()) | \
          (k["region"].to_numpy() != c2["region"].to_numpy()) | (k["marketing_consent"].to_numpy() != c2["marketing_consent"].to_numpy()) | \
          (k["signup_date"].to_numpy() != c2["closed_date"].to_numpy())
    C.add("A08", "ERROR", "prospects", c2["prospect_id"][bad], "converted prospect disagrees with its customer (channel/segment/region/consent/signup date)")
    ws = pd.Timestamp(cfg["window_start"])
    acquired = cu[cu["signup_date"] >= ws].index
    C.add("A08", "ERROR", "customers", pd.Series(acquired.difference(pd.Index(conv["converted_customer_id"]))), "customer acquired in the window has no converted prospect")
    legacy = cu[cu["signup_date"] < ws].index
    C.add("A08", "ERROR", "customers", pd.Series(legacy.intersection(pd.Index(conv["converted_customer_id"]))), "pre-window customer must not have a prospect")


# ---- campaigns --------------------------------------------------------------------------------------------------------
def check_campaigns(tb, cfg, C: Collector):
    C.ran("C03", "campaign integrity: contacts inside the campaign window and segment, one campaign per customer, both arms present")
    cp = tb["campaigns"]
    cc = tb["campaign_contacts"]
    cid = cc["contact_id"]
    C.add("C03", "ERROR", "campaigns", cp["campaign_id"][cp["end_date"] < cp["start_date"]], "campaign ends before it starts")
    k = cp.set_index("campaign_id").reindex(cc["campaign_id"])
    known = k["start_date"].notna().to_numpy()                       # unknown campaign ids are reported by the FK check
    cd = cc["contact_date"].to_numpy()
    outside = known & ((cd < k["start_date"].to_numpy()) | (cd > k["end_date"].to_numpy()))
    C.add("C03", "ERROR", "campaign_contacts", cid[outside], "contact dated outside its campaign window")
    seg = tb["customers"].set_index("customer_id")["segment"].reindex(cc["customer_id"]).to_numpy()
    tgt = k["target_segment"].to_numpy()
    C.add("C03", "ERROR", "campaign_contacts", cid[known & (tgt != "ALL") & (tgt != seg)], "customer is not in the campaign's target segment")
    many = cc.groupby("customer_id")["campaign_id"].transform("nunique") > 1
    C.add("C03", "ERROR", "campaign_contacts", cid[many], "customer contacted by more than one campaign")
    arms = cc.groupby("campaign_id")["randomization_group"].agg(lambda s: {"TREATMENT", "CONTROL"} <= set(s))
    C.add("C03", "ERROR", "campaigns", pd.Series(cp["campaign_id"][~cp["campaign_id"].map(arms).fillna(False).astype(bool)].to_numpy()),
          "campaign lacks a TREATMENT or a CONTROL arm")


# ---- admin audit log ----------------------------------------------------------------------------------------------
def check_audit(tb, cfg, C: Collector):
    C.ran("S04", "audit-log polymorphic reference resolves to an existing row")
    C.ran("C02", "every manual eligibility override has an audit record by the same role, before the contact")
    C.ran("D02", "reference data was published before its effective date")
    a = tb["admin_audit_log"]
    keys = {"plans": "plan_id", "eligibility_rules": "rule_id", "offers": "offer_id", "campaign_contacts": "contact_id"}
    for tname, col in keys.items():
        sel = a[a["entity_table"] == tname]
        C.add("S04", "ERROR", "admin_audit_log", sel["audit_id"][~sel["entity_id"].isin(set(tb[tname][col]))], f"entity_id not found in {tname}")
    cc = tb["campaign_contacts"]
    ov = cc[cc["contact_source"] == "MANUAL_OVERRIDE"]
    ao = a[a["action"] == "ELIGIBILITY_OVERRIDE"].drop_duplicates("entity_id").set_index("entity_id")
    role = ao["actor_role"].reindex(ov["contact_id"]).to_numpy()
    when = ao["event_time"].reindex(ov["contact_id"]).to_numpy()
    bad = pd.isna(role) | (role != ov["launched_by_role"].to_numpy()) | (pd.to_datetime(when) >= ov["contact_date"].to_numpy())
    C.add("C02", "ERROR", "campaign_contacts", ov["contact_id"][bad], "manual override without a matching earlier audit record")
    ext = a[a["action"] == "ELIGIBILITY_OVERRIDE"]
    C.add("C02", "ERROR", "admin_audit_log", ext["audit_id"][~ext["entity_id"].isin(set(ov["contact_id"]))], "audit override for a contact that is not an override")
    eff = {"PRICE_VERSION_PUBLISHED": ("plans", "plan_id", "effective_from"), "RULE_ACTIVATED": ("eligibility_rules", "rule_id", "effective_from"),
           "OFFER_PUBLISHED": ("offers", "offer_id", "valid_from")}
    for act, (tname, col, dcol) in eff.items():
        x = a[a["action"] == act]
        d = tb[tname].set_index(col)[dcol].reindex(x["entity_id"]).to_numpy()
        C.add("D02", "ERROR", "admin_audit_log", x["audit_id"][pd.to_datetime(x["event_time"]).to_numpy() >= d], f"{act} not before {dcol}")
    for tname, col in (("plans", "plan_id"), ("eligibility_rules", "rule_id"), ("offers", "offer_id")):
        pub = set(a.loc[a["entity_table"] == tname, "entity_id"])
        C.add("D02", "ERROR", tname, tb[tname][col][~tb[tname][col].isin(pub)], "reference row has no publication audit record")


# ---- SQL seed verification ------------------------------------------------------------------------------------
def check_sql(data_dir_parent: Path, tb, C: Collector):
    C.ran("Q02", "SQL schema+seed loads and has no FK violations; row counts equal CSV")
    sql_dir = Path(data_dir_parent) / "sql"
    if not (sql_dir / "seed.sql").exists():
        return {"skipped": True}
    con = sqlite3.connect(":memory:")
    con.executescript((sql_dir / "schema.sql").read_text(encoding="utf-8").replace("PRAGMA foreign_keys = ON;", "PRAGMA foreign_keys = OFF;"))
    con.executescript((sql_dir / "seed.sql").read_text(encoding="utf-8"))
    fk = con.execute("PRAGMA foreign_key_check").fetchall()
    counts = {n: con.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0] for n in SCHEMA}
    bad = [n for n, c in counts.items() if c != len(tb[n])]
    C.add("Q02", "ERROR", "sql", pd.Series(bad + [f"fk:{x[0]}" for x in fk[:20]]), "SQL load / row-count / FK problem")
    con.close()
    return {"skipped": False, "fk_violations": len(fk), "row_counts": counts}


# ---- coverage / acceptance criteria ---------------------------------------------------------------------------
def coverage(tb, cfg) -> dict:
    pred = pd.Timestamp(cfg["prediction_date"])
    prim = tb["subscriptions"][tb["subscriptions"]["is_primary"] == 1]
    ever = (prim["status"] != "ACTIVE").mean()
    co = tb["churn_outcomes"]
    co_ok = co[co["churn_event_date"].isna() | (co["churn_event_date"] >= pred)]
    ev = tb["subscription_events"]
    cc = tb["campaign_contacts"]
    r = tb["retention_outcomes"]
    treat = r[r["randomization_group"] == "TREATMENT"]
    out = {
        "customers": int(len(tb["customers"])),
        "primary_subscriptions": int(len(prim)),
        "ever_churn_rate_primary": float(ever),
        "horizon_churn_rate_scored": float(co_ok["churned_in_horizon"].mean()),
        "voluntary_churn_events": int((ev["event_type"] == "CANCELLED").sum() - (tb["subscriptions"]["product_type"].eq("ADDON") & tb["subscriptions"]["status"].eq("CANCELLED")).sum()),
        "involuntary_churn_events": int((ev["event_type"] == "TERMINATED_NONPAYMENT").sum()),
        "plan_upgrades": int((ev["event_type"] == "PLAN_UPGRADE").sum()),
        "plan_downgrades": int((ev["event_type"] == "PLAN_DOWNGRADE").sum()),
        "price_change_events": int((ev["event_type"] == "PRICE_CHANGE").sum()),
        "failed_payment_events": int((tb["billing_events"]["event_type"] == "PAYMENT_FAILED").sum()),
        "campaign_contacts": int(len(cc)),
        "treatment_share_of_contacts": float((cc["randomization_group"] == "TREATMENT").mean()),
        "treated_not_viewed_share": float((treat["offer_viewed"] == 0).mean()),
        "treated_viewed_not_accepted_share": float(((treat["offer_viewed"] == 1) & (treat["offer_accepted"] == 0)).mean()),
        "treated_accepted_share": float((treat["offer_accepted"] == 1).mean()),
        "total_offer_cost": float(r["offer_cost"].sum()),
    }
    pr = tb["prospects"]
    closed = pr[pr["status"] != "OPEN"]
    out["prospect_funnel"] = {"prospects": int(len(pr)), "converted": int((pr["status"] == "CONVERTED").sum()),
                              "lost": int((pr["status"] == "LOST").sum()), "open_at_data_end": int((pr["status"] == "OPEN").sum()),
                              "conversion_rate_of_closed": float((closed["status"] == "CONVERTED").mean()) if len(closed) else None}
    out["acceptance"] = {
        "churn_rate_between_5_and_20_pct": bool(0.05 <= ever <= 0.20),
        "has_voluntary_and_involuntary": bool(out["voluntary_churn_events"] > 0 and out["involuntary_churn_events"] > 0),
        "has_plan_changes": bool(out["plan_upgrades"] > 0 and out["plan_downgrades"] > 0),
        "has_offer_non_response": bool(out["treated_not_viewed_share"] > 0 and out["treated_viewed_not_accepted_share"] > 0),
        "customers_at_least_1_subscription": bool(len(tb["customers"]) == prim["customer_id"].nunique()),
        "prospect_funnel_has_converted_lost_open": bool(out["prospect_funnel"]["converted"] > 0 and out["prospect_funnel"]["lost"] > 0
                                                       and out["prospect_funnel"]["open_at_data_end"] > 0),
    }
    return out


def balance_table(tb) -> list:
    """Randomisation balance (standardised mean difference) on pre-treatment covariates for clean contacts."""
    cc = tb["campaign_contacts"]
    cc = cc[cc["contact_source"] == "AUTO_ELIGIBLE"].sort_values("contact_id").drop_duplicates(["customer_id"], keep="first")
    cu = tb["customers"].set_index("customer_id")
    ev = tb["eligibility_evaluations"].drop_duplicates("customer_id").set_index("customer_id")
    d = cc.merge(ev[["tenure_months", "plan_code", "failed_payments_window"]], left_on="customer_id", right_index=True)
    d["consent"] = 1
    d["smb"] = (cu["segment"].reindex(d["customer_id"]).to_numpy() == "SMB").astype(int)
    d["premium"] = (d["plan_code"] == "PREMIUM").astype(int)
    d["basic"] = (d["plan_code"] == "BASIC").astype(int)
    t = d["randomization_group"] == "TREATMENT"
    rows = []
    for col in ("tenure_months", "smb", "premium", "basic", "failed_payments_window"):
        a, b_ = d.loc[t, col].astype(float), d.loc[~t, col].astype(float)
        sd = np.sqrt((a.var() + b_.var()) / 2) or 1.0
        rows.append({"covariate": col, "treatment_mean": float(a.mean()), "control_mean": float(b_.mean()), "std_mean_diff": float((a.mean() - b_.mean()) / sd)})
    return rows


# ---- ground-truth reconciliation ----------------------------------------------------------------------------------
def reconcile_with_ground_truth(viol: pd.DataFrame, gt: pd.DataFrame) -> dict:
    res = {"per_issue_type": {}}
    gt_ids = set(gt["entity_id"])
    for issue, (check, decision) in ISSUE_TYPES.items():
        g = gt[gt["issue_type"] == issue]
        hit = viol[(viol["check_id"] == check)]["entity_id"]
        detected = g["entity_id"].isin(set(hit))
        res["per_issue_type"][issue] = {"injected": int(len(g)), "detected": int(detected.sum()), "expected_check": check,
                                         "recall": float(detected.mean()) if len(g) else None}
    rule = viol[viol["severity"] == "RULE"]
    unexplained = rule[~rule["entity_id"].isin(gt_ids)]
    res["unexplained_rule_violations"] = int(len(unexplained))
    res["unexplained_examples"] = unexplained.head(10).to_dict("records")
    err = viol[viol["severity"] == "ERROR"]
    res["error_violations"] = int(len(err))
    res["error_examples"] = err.head(10).to_dict("records")
    res["all_injected_detected"] = all(v["recall"] in (None, 1.0) for v in res["per_issue_type"].values())
    res["passed"] = bool(res["all_injected_detected"] and res["unexplained_rule_violations"] == 0 and res["error_violations"] == 0)
    return res


def _safe(fn, default):
    try:
        return fn()
    except Exception:  # summary statistics must not mask the violations that were found
        return default


def run_validation(out_dir, check_sql_load: bool = True) -> dict:
    out = Path(out_dir)
    t0 = time.time()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    cfg = manifest["config"]
    tb = load_tables(out / "data")
    C = Collector()
    C.ran("V00", "every check group completed (a crash on corrupt input is reported, not raised)")
    for fn in (check_structure, check_dates_lifecycle, check_arithmetic, check_business, check_audit, check_prospects, check_campaigns):
        try:
            fn(tb, C) if fn is check_structure else fn(tb, cfg, C)
        except Exception as exc:  # corrupt input must be reported as a validation failure
            C.add("V00", "ERROR", "validator", [fn.__name__], f"check group aborted: {type(exc).__name__}: {exc}")
    sql_info = check_sql(out, tb, C) if check_sql_load else {"skipped": True}
    viol = C.frame()
    gt = pd.read_csv(out / "ground_truth" / "ground_truth.csv")
    rec = reconcile_with_ground_truth(viol, gt)
    cov = _safe(lambda: coverage(tb, cfg), {"acceptance": {"coverage_computable": False}})
    dist = _safe(lambda: distribution_report(tb, cfg, out), {})
    bnd = _safe(lambda: boundary_report(tb, cfg, out), {"cases": [], "all_required_covered": False, "missing_required": ["report failed"]})
    cov["acceptance"].update(distribution_acceptance(dist) if dist else {"distribution_report_available": False})
    cov["acceptance"]["boundary_failure_exception_cases_covered"] = bool(bnd["all_required_covered"])
    summary = {
        "dataset": str(out),
        "seed": manifest["seed"],
        "row_counts": {k: int(len(v)) for k, v in tb.items()},
        "checks": C.checks_run,
        "total_error_violations": int((viol["severity"] == "ERROR").sum()) if len(viol) else 0,
        "total_rule_violations": int((viol["severity"] == "RULE").sum()) if len(viol) else 0,
        "ground_truth_reconciliation": rec,
        "coverage": cov,
        "distributions": dist, "boundary_coverage": bnd,
        "randomisation_balance": _safe(lambda: balance_table(tb), []),
        "sql": sql_info,
        "elapsed_seconds": round(time.time() - t0, 1),
        "passed": bool(rec["passed"] and all(cov["acceptance"].values())),
    }
    vdir = out / "validation"
    vdir.mkdir(exist_ok=True)
    viol.to_csv(vdir / "violations.csv", index=False, lineterminator="\n")
    (vdir / "validation_summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    (vdir / "validation_summary.md").write_text(summary_md(summary), encoding="utf-8")
    if dist:
        (vdir / "distribution_report.md").write_text(distribution_md(dist), encoding="utf-8")
    (vdir / "boundary_coverage.md").write_text(boundary_md(bnd), encoding="utf-8")
    return summary


def summary_md(s: dict) -> str:
    L = ["# Validation summary", "", f"- dataset: `{s['dataset']}`  |  seed: {s['seed']}  |  elapsed: {s['elapsed_seconds']}s",
         f"- **overall: {'PASS' if s['passed'] else 'FAIL'}**",
         f"- structural/arithmetic ERROR violations: **{s['total_error_violations']}** (must be 0)",
         f"- business-rule violations (RULE): **{s['total_rule_violations']}** (all must map to injected, labelled anomalies)", "",
         "## Checks", "", "| check | what it verifies | violations |", "|---|---|---|"]
    for k, v in sorted(s["checks"].items()):
        L.append(f"| {k} | {v['description']} | {v['violations']} |")
    rec = s["ground_truth_reconciliation"]
    L += ["", "## Injected anomalies vs detection (ground truth used only here)", "",
          "| issue_type | injected | detected | expected check | recall |", "|---|---|---|---|---|"]
    for k, v in rec["per_issue_type"].items():
        L.append(f"| {k} | {v['injected']} | {v['detected']} | {v['expected_check']} | {v['recall']} |")
    L += ["", f"- unexplained RULE violations (not in ground truth): **{rec['unexplained_rule_violations']}**",
          f"- ERROR violations: **{rec['error_violations']}**", "", "## Row counts", "", "| table | rows |", "|---|---|"]
    for k, v in s["row_counts"].items():
        L.append(f"| {k} | {v:,} |")
    L += ["", "## Coverage / acceptance criteria", ""]
    for k, v in s["coverage"].items():
        if k != "acceptance":
            L.append(f"- {k}: {v:.4f}" if isinstance(v, float) else f"- {k}: {v}")
    L.append("")
    for k, v in s["coverage"]["acceptance"].items():
        L.append(f"- [{'x' if v else ' '}] {k}")
    L += ["", "Detailed evidence: `distribution_report.md` (distributions, churn-by-month, seasonal users) and `boundary_coverage.md` "
          "(normal / boundary / failure / exception cases).", "", "## Randomisation balance (standardised mean difference, |SMD| < 0.1 is balanced)", "",
          "| covariate | treatment | control | SMD |", "|---|---|---|---|"]
    for r in s["randomisation_balance"]:
        L.append(f"| {r['covariate']} | {r['treatment_mean']:.3f} | {r['control_mean']:.3f} | {r['std_mean_diff']:.3f} |")
    L.append("")
    return "\n".join(L)
