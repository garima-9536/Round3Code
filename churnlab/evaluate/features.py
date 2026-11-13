"""Leakage-safe feature builder: every input record is filtered to timestamps strictly before `cutoff`.

Labels are built separately from events at/after the cutoff. A guard returns the latest timestamp used per table so
the report can prove max(feature timestamp) < prediction date.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..validate.eligibility import plan_asof

CATS = {
    "segment": ["CONSUMER", "SMB"],
    "region": ["NORTH", "SOUTH", "EAST", "WEST"],
    "acquisition_channel": ["ORGANIC", "PAID", "REFERRAL", "PARTNER"],
    "payment_method": ["CARD", "BANK_DEBIT", "WALLET"],
    "plan_code": ["BASIC", "STANDARD", "PREMIUM"],
}


def _nanmean(a):
    with np.errstate(all="ignore"):
        return np.nanmean(a, axis=1)


def population(tb: dict, cutoff: pd.Timestamp) -> pd.DataFrame:
    subs = tb["subscriptions"]
    prim = subs[subs["is_primary"] == 1]
    keep = (prim["start_date"] < cutoff) & (prim["end_date"].isna() | (prim["end_date"] >= cutoff))
    return prim[keep]


def build_features(tb: dict, cutoff: pd.Timestamp):
    assert cutoff.day == 1, "cutoffs are month starts"
    pop = population(tb, cutoff)
    sid = pop["subscription_id"]
    cust_ids = pop["customer_id"].to_numpy()
    guard = {}

    cu = tb["customers"].set_index("customer_id")
    X = pd.DataFrame(index=pd.Index(cust_ids, name="customer_id"))
    X["tenure_months"] = ((cutoff - pop["start_date"]).dt.days / 30.4375).to_numpy()
    X["marketing_consent"] = cu["marketing_consent"].reindex(cust_ids).astype(float).to_numpy()
    for c in ("segment", "region", "acquisition_channel"):
        X[c] = cu[c].reindex(cust_ids).to_numpy()
    X["payment_method"] = pop["payment_method"].to_numpy()
    ev = tb["subscription_events"]
    ev_before = ev[ev["event_date"] < cutoff]
    guard["subscription_events"] = ev_before["event_date"].max()
    X["plan_code"] = plan_asof(ev, tb["subscriptions"], cutoff)["plan_code"].reindex(sid).to_numpy()
    subs = tb["subscriptions"]
    addon = subs[(subs["is_primary"] == 0) & (subs["start_date"] < cutoff) & (subs["end_date"].isna() | (subs["end_date"] >= cutoff))]
    X["n_addons"] = addon.groupby("customer_id").size().reindex(cust_ids).fillna(0).to_numpy()

    # ---- usage (monthly snapshots strictly before the cutoff month) ---------------------------------
    u = tb["usage_snapshots"]
    u = u[u["subscription_id"].isin(set(sid)) & (u["snapshot_month"] < cutoff)].copy()
    guard["usage_snapshots"] = u["snapshot_month"].max()
    u["mb"] = (cutoff.year - u["snapshot_month"].dt.year) * 12 + cutoff.month - u["snapshot_month"].dt.month
    cols = list(range(1, 13))

    def piv(col):
        p = u[u["mb"].between(1, 12)].pivot_table(index="subscription_id", columns="mb", values=col, aggfunc="mean")
        return p.reindex(index=sid, columns=cols).to_numpy(dtype=float)

    S = piv("sessions")
    X["sessions_m1"] = S[:, 0]
    X["sessions_3m"] = _nanmean(S[:, 0:3])
    X["sessions_prev3m"] = _nanmean(S[:, 3:6])
    X["usage_ratio_3m_vs_prev3m"] = (X["sessions_3m"] + 1) / (X["sessions_prev3m"] + 1)
    X["usage_ratio_m1_vs_3m"] = (X["sessions_m1"] + 1) / (X["sessions_3m"] + 1)
    X["sessions_12m_mean"] = _nanmean(S)
    with np.errstate(all="ignore"):
        X["sessions_cv"] = np.nanstd(S, axis=1) / np.nanmean(S, axis=1)
    mask = ~np.isnan(S)
    xs = -np.arange(1, 13, dtype=float)[None, :]
    n = mask.sum(1)
    with np.errstate(all="ignore"):
        xbar = (xs * mask).sum(1) / n
        ybar = np.nansum(S, axis=1) / n
        cov = (mask * (xs - xbar[:, None]) * np.nan_to_num(S - ybar[:, None])).sum(1)
        var = (mask * (xs - xbar[:, None]) ** 2).sum(1)
        X["sessions_slope_rel"] = np.where(n >= 3, cov / var / ybar, np.nan)
    X["n_usage_months"] = n
    X["hours_3m"] = _nanmean(piv("usage_hours")[:, 0:3])
    X["active_days_3m"] = _nanmean(piv("active_days")[:, 0:3])
    X["features_used_3m"] = _nanmean(piv("features_used")[:, 0:3])

    # ---- billing ------------------------------------------------------------------------------------------
    b = tb["billing_events"]
    b = b[b["subscription_id"].isin(set(sid)) & (b["event_date"] < cutoff)]
    guard["billing_events"] = b["event_date"].max()
    f = b[b["event_type"] == "PAYMENT_FAILED"]
    X["failed_payments_30d"] = f[f["event_date"] >= cutoff - pd.Timedelta(days=30)].groupby("subscription_id").size().reindex(sid).fillna(0).to_numpy()
    X["failed_payments_90d"] = f[f["event_date"] >= cutoff - pd.Timedelta(days=90)].groupby("subscription_id").size().reindex(sid).fillna(0).to_numpy()
    X["failed_payments_total"] = f.groupby("subscription_id").size().reindex(sid).fillna(0).to_numpy()
    invs = b[b["event_type"] == "INVOICE"].sort_values("event_date")
    X["last_invoice_amount"] = invs.groupby("subscription_id")["amount"].last().reindex(sid).to_numpy()
    for typ, name in (("PRICE_CHANGE", "price_change_120d"),):
        e = ev_before[(ev_before["event_type"] == typ) & (ev_before["event_date"] >= cutoff - pd.Timedelta(days=120))]
        X[name] = e.groupby("subscription_id").size().reindex(sid).fillna(0).clip(upper=1).to_numpy()
    win = ev_before[ev_before["event_date"] >= cutoff - pd.Timedelta(days=180)]
    X["upgrades_180d"] = win[win["event_type"] == "PLAN_UPGRADE"].groupby("subscription_id").size().reindex(sid).fillna(0).to_numpy()
    X["downgrades_180d"] = win[win["event_type"] == "PLAN_DOWNGRADE"].groupby("subscription_id").size().reindex(sid).fillna(0).to_numpy()

    # ---- support ---------------------------------------------------------------------------------------------
    c = tb["support_cases"]
    c = c[c["customer_id"].isin(set(cust_ids)) & (c["opened_at"] < cutoff)].copy()
    guard["support_cases"] = c["opened_at"].max()
    res_before = c["resolved_at"].notna() & (c["resolved_at"] < cutoff)
    c["open_at_cutoff"] = ~res_before
    c["age_h"] = (cutoff - c["opened_at"]).dt.total_seconds() / 3600
    c["res_h_known"] = np.where(res_before, (c["resolved_at"] - c["opened_at"]).dt.total_seconds() / 3600, np.nan)
    c["slow"] = ((c["res_h_known"] > 72) | (c["open_at_cutoff"] & (c["age_h"] > 72))).astype(int)
    c["csat_known"] = np.where(res_before, c["csat_score"].astype(float), np.nan)
    g = c.groupby("customer_id")

    def cnt(mask):
        return c[mask].groupby("customer_id").size().reindex(cust_ids).fillna(0).to_numpy()

    d30, d90 = c["age_h"] <= 30 * 24, c["age_h"] <= 90 * 24
    X["cases_30d"], X["cases_90d"] = cnt(d30), cnt(d90)
    X["cases_total"] = cnt(c["age_h"] >= 0)
    X["billing_cases_90d"] = cnt(d90 & (c["category"] == "BILLING"))
    X["cancel_query_90d"] = cnt(d90 & (c["category"] == "CANCELLATION_QUERY"))
    X["open_cases_at_cutoff"] = cnt(c["open_at_cutoff"])
    X["slow_cases_90d"] = cnt(d90 & (c["slow"] == 1))
    X["escalated_90d"] = cnt(d90 & c["escalated_at"].notna() & (c["escalated_at"] < cutoff))
    X["mean_resolution_h_90d"] = c[d90].groupby("customer_id")["res_h_known"].mean().reindex(cust_ids).to_numpy()
    X["mean_csat_90d"] = c[d90].groupby("customer_id")["csat_known"].mean().reindex(cust_ids).to_numpy()

    guard_out = {k: (None if pd.isna(v) else str(pd.Timestamp(v).date())) for k, v in guard.items()}
    assert all(v is None or pd.Timestamp(v) < cutoff for v in guard_out.values()), f"feature leakage at {cutoff}: {guard_out}"
    return X, guard_out


def build_labels(tb: dict, cutoff: pd.Timestamp, horizon_months: int) -> pd.DataFrame:
    """label = primary subscription ends in [cutoff, cutoff + horizon). Built from lifecycle events only."""
    pop = population(tb, cutoff)
    hend = cutoff + pd.DateOffset(months=horizon_months)
    ev = tb["subscription_events"]
    term = ev[ev["event_type"].isin(["CANCELLED", "TERMINATED_NONPAYMENT"])].set_index("subscription_id")
    d = term["event_date"].reindex(pop["subscription_id"]).to_numpy()
    t = term["event_type"].reindex(pop["subscription_id"]).to_numpy()
    y = (pd.notna(d) & (d >= cutoff) & (d < hend)).astype(int)
    out = pd.DataFrame({"churn": y, "churn_type": np.where(y == 1, np.where(t == "CANCELLED", "VOLUNTARY", "INVOLUNTARY"), None)},
                       index=pd.Index(pop["customer_id"].to_numpy(), name="customer_id"))
    return out


def encode(X: pd.DataFrame) -> pd.DataFrame:
    X = X.copy()
    for c, cats in CATS.items():
        X[c] = pd.Categorical(X[c], categories=cats)
    return pd.get_dummies(X, columns=list(CATS), dtype=float)
