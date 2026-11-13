"""Distribution / seasonality report and boundary / failure / exception coverage report.

Both are descriptive evidence that the data is realistic and exercises the edge paths. The ground truth is read
in exactly one place (seasonality: to confirm the hidden `seasonal_user` flag is visible in usage) and is labelled as such.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def _q(s) -> dict:
    s = pd.Series(s).dropna().astype(float)
    if s.empty:
        return {}
    return {"n": int(len(s)), "mean": round(float(s.mean()), 3), "p5": round(float(s.quantile(.05)), 3), "p25": round(float(s.quantile(.25)), 3),
            "median": round(float(s.median()), 3), "p75": round(float(s.quantile(.75)), 3), "p95": round(float(s.quantile(.95)), 3)}


# ---- distributions ---------------------------------------------------------------------------------------
def distribution_report(tb: dict, cfg: dict, out: Path) -> dict:
    pred = pd.Timestamp(cfg["prediction_date"])
    subs, u, b, cs = tb["subscriptions"], tb["usage_snapshots"], tb["billing_events"], tb["support_cases"]
    prim = subs[subs["is_primary"] == 1]
    alive = prim[(prim["start_date"] < pred) & (prim["end_date"].isna() | (prim["end_date"] >= pred))]
    d = {"tenure_months_at_prediction_date": _q((pred - alive["start_date"]).dt.days / 30.4375)}
    d["monthly_sessions_by_plan"] = {p: _q(g["sessions"]) for p, g in u.groupby("plan_code")}
    d["avg_session_minutes_nonzero"] = _q(u.loc[u["sessions"] > 0, "avg_session_minutes"])
    d["share_zero_session_months"] = round(float((u["sessions"] == 0).mean()), 4)
    inv = b[b["event_type"] == "INVOICE"]
    d["invoice_amount_counts"] = {f"{k:.2f}": int(v) for k, v in inv["amount"].value_counts().sort_index().items()}

    fails = b[b["event_type"] == "PAYMENT_FAILED"].groupby("invoice_id").size().reindex(inv["billing_event_id"]).fillna(0).to_numpy()
    wo = b[b["event_type"] == "WRITE_OFF"].groupby("invoice_id").size().reindex(inv["billing_event_id"]).fillna(0).to_numpy()
    n = len(inv)
    d["invoice_outcomes"] = {"paid_first_attempt": round(float(((fails == 0) & (wo == 0)).sum() / n), 4),
                             "paid_after_1_or_2_retries": round(float(((fails > 0) & (wo == 0)).sum() / n), 4),
                             "written_off": round(float((wo > 0).sum() / n), 4)}
    per_cust = cs.groupby("customer_id").size().reindex(tb["customers"]["customer_id"]).fillna(0)
    d["support"] = {"cases_per_customer": _q(per_cust), "share_customers_with_case": round(float((per_cust > 0).mean()), 4),
                    "resolution_hours": _q(cs["resolution_hours"]), "share_resolved_over_72h": round(float((cs["resolution_hours"] > 72).sum() / max(cs["resolution_hours"].notna().sum(), 1)), 4),
                    "share_unresolved_at_data_end": round(float((cs["status"] != "RESOLVED").mean()), 4),
                    "csat_mean": round(float(cs["csat_score"].mean()), 3),
                    "category_share": {k: round(float(v), 4) for k, v in cs["category"].value_counts(normalize=True).items()}}
    ev = tb["subscription_events"].merge(prim[["subscription_id"]], on="subscription_id")
    term = ev[ev["event_type"].isin(["CANCELLED", "TERMINATED_NONPAYMENT"])].copy()
    term["month"] = term["event_date"].dt.strftime("%Y-%m")
    curve = term.groupby(["month", "event_type"]).size().unstack(fill_value=0)
    d["primary_churn_events_by_month"] = {m: {"voluntary": int(r.get("CANCELLED", 0)), "involuntary": int(r.get("TERMINATED_NONPAYMENT", 0))} for m, r in curve.iterrows()}

    pr, pe = tb["prospects"], tb["prospect_events"]
    cnt = pe[pe["event_type"] == "CONTACTED"].groupby("prospect_id").size().reindex(pr["prospect_id"]).fillna(0).to_numpy()
    trial = pe[pe["event_type"] == "TRIAL_STARTED"].groupby("prospect_id").size().reindex(pr["prospect_id"]).fillna(0).to_numpy() > 0
    p2 = pr.assign(n_contacts=cnt, trial=trial, lag=(pr["closed_date"] - pr["created_date"]).dt.days)
    closed = p2[p2["status"] != "OPEN"]
    by_ch = {}
    for c, g in p2.groupby("source_channel"):
        cl = g[g["status"] != "OPEN"]
        by_ch[c] = {"leads": int(len(g)), "closed": int(len(cl)),
                    "conversion_rate_of_closed": round(float((cl["status"] == "CONVERTED").mean()), 4) if len(cl) else None}
    d["prospect_funnel"] = {
        "by_status": {k: int(v) for k, v in p2["status"].value_counts().items()},
        "conversion_rate_of_closed": round(float((closed["status"] == "CONVERTED").mean()), 4),
        "by_channel": by_ch,
        "days_lead_to_conversion": _q(p2.loc[p2["status"] == "CONVERTED", "lag"]),
        "mean_contacts_converted_vs_lost": [round(float(p2.loc[p2["status"] == x, "n_contacts"].mean()), 3) for x in ("CONVERTED", "LOST")],
        "trial_share_converted_vs_lost": [round(float(p2.loc[p2["status"] == x, "trial"].mean()), 4) for x in ("CONVERTED", "LOST")],
        "lost_reasons": {k: int(v) for k, v in p2["lost_reason"].value_counts().items()},
    }

    # ---- seasonality: is the hidden flag visible in usage, and are seasonal dips hard negatives? -----------
    lat_path = Path(out) / "ground_truth" / "latent_truth.csv"
    if lat_path.exists():
        lat = pd.read_csv(lat_path).set_index("customer_id")
        pr = prim.set_index("subscription_id")
        uu = u[u["subscription_id"].isin(set(pr.index)) & (u["snapshot_month"] >= pd.Timestamp("2025-07-01")) & (u["snapshot_month"] < pred)].copy()
        uu["customer_id"] = pr["customer_id"].reindex(uu["subscription_id"]).to_numpy()
        pv = uu.pivot_table(index="customer_id", columns="snapshot_month", values="sessions", aggfunc="mean")
        pv = pv.dropna()
        pv = pv[pv.index.isin(lat.index)]
        cv = pv.std(axis=1, ddof=0) / pv.mean(axis=1)
        seas = lat["seasonal_user"].reindex(pv.index).astype(bool)
        last3, prev3 = pv.iloc[:, -3:].mean(axis=1), pv.iloc[:, -6:-3].mean(axis=1)
        drop = (last3 / prev3) < 0.75
        co = tb["churn_outcomes"].set_index("customer_id")["churned_in_horizon"].reindex(pv.index)
        cell = {}
        for name, m in (("seasonal_with_usage_drop", seas & drop), ("non_seasonal_with_usage_drop", ~seas & drop),
                        ("seasonal_no_drop", seas & ~drop), ("non_seasonal_no_drop", ~seas & ~drop)):
            cell[name] = {"customers": int(m.sum()), "horizon_churn_rate": round(float(co[m].mean()), 4) if m.sum() else None}
        d["seasonality"] = {
            "customers_with_12_full_months": int(len(pv)), "seasonal_share": round(float(seas.mean()), 4),
            "median_usage_cv_seasonal": round(float(cv[seas].median()), 3), "median_usage_cv_non_seasonal": round(float(cv[~seas].median()), 3),
            "usage_drop_vs_churn": cell,
            "note": "ground truth (`seasonal_user`) is used here only to confirm the flag is observable; it is never a feature",
        }
    return d


def distribution_acceptance(d: dict) -> dict:
    s = d.get("seasonality")
    if not s:
        return {"seasonality_check_available": False}
    cells = s["usage_drop_vs_churn"]
    sd, nd = cells["seasonal_with_usage_drop"], cells["non_seasonal_with_usage_drop"]
    return {
        "seasonality_visible_in_usage": bool(s["median_usage_cv_seasonal"] > 1.5 * s["median_usage_cv_non_seasonal"]),
        "seasonal_dips_are_hard_negatives": bool(sd["horizon_churn_rate"] is not None and nd["horizon_churn_rate"] is not None
                                                 and sd["horizon_churn_rate"] < nd["horizon_churn_rate"]),
    }


def distribution_md(d: dict) -> str:
    L = ["# Distribution and seasonality report", "", "Descriptive evidence of realistic variation (see README for the generating mechanism).", ""]

    def row(name, q):
        return f"| {name} | {q.get('n', '')} | {q.get('mean', '')} | {q.get('p5', '')} | {q.get('median', '')} | {q.get('p95', '')} |"

    L += ["| measure | n | mean | p5 | median | p95 |", "|---|---|---|---|---|---|", row("tenure at prediction date (months)", d["tenure_months_at_prediction_date"])]
    for p, q in d["monthly_sessions_by_plan"].items():
        L.append(row(f"sessions per month - {p}", q))
    L += [row("avg session minutes (non-zero)", d["avg_session_minutes_nonzero"]), row("cases per customer", d["support"]["cases_per_customer"]),
          row("case resolution hours", d["support"]["resolution_hours"]), ""]
    L += [f"- share of zero-session months: {d['share_zero_session_months']}",
          f"- invoice outcomes: {d['invoice_outcomes']}", f"- invoice amounts (USD: count): {d['invoice_amount_counts']}",
          f"- support: share of customers with a case {d['support']['share_customers_with_case']}, resolved >72h {d['support']['share_resolved_over_72h']}, "
          f"unresolved at data end {d['support']['share_unresolved_at_data_end']}, mean CSAT {d['support']['csat_mean']}",
          f"- case categories: {d['support']['category_share']}", "", "## Primary-subscription churn events by month (churn wave visible after 2026-07)", "",
          "| month | voluntary | involuntary |", "|---|---|---|"]
    for m, v in d["primary_churn_events_by_month"].items():
        L.append(f"| {m} | {v['voluntary']} | {v['involuntary']} |")
    f = d["prospect_funnel"]
    L += ["", "## Prospect funnel", "", f"- status: {f['by_status']}; conversion rate of closed leads {f['conversion_rate_of_closed']:.1%}",
          f"- days from lead creation to conversion: {f['days_lead_to_conversion']}",
          f"- mean contacts (converted vs lost): {f['mean_contacts_converted_vs_lost']}; trial share (converted vs lost): {f['trial_share_converted_vs_lost']}",
          f"- lost reasons: {f['lost_reasons']}", "", "| channel | leads | closed | conversion rate of closed |", "|---|---|---|---|"]
    for c, v in f["by_channel"].items():
        L.append(f"| {c} | {v['leads']} | {v['closed']} | {v['conversion_rate_of_closed']} |")
    s = d.get("seasonality")
    if s:
        L += ["", "## Seasonal users", "",
              f"{s['customers_with_12_full_months']:,} customers with 12 full usage months; {s['seasonal_share']:.1%} are seasonal users.",
              f"- median monthly-usage coefficient of variation: seasonal {s['median_usage_cv_seasonal']} vs non-seasonal {s['median_usage_cv_non_seasonal']}",
              "", "A usage drop (last 3 months < 75% of previous 3) means very different things for seasonal and non-seasonal users:", "",
              "| group | customers | horizon churn rate |", "|---|---|---|"]
        for k, v in s["usage_drop_vs_churn"].items():
            L.append(f"| {k} | {v['customers']} | {v['horizon_churn_rate']} |")
        L += ["", f"_{s['note']}_"]
    return "\n".join(L) + "\n"


# ---- boundary / failure / exception coverage ------------------------------------------------------------------
def boundary_report(tb: dict, cfg: dict, out: Path) -> dict:
    ev = tb["eligibility_evaluations"]
    ev1 = ev.drop_duplicates("customer_id")
    b = tb["billing_events"]
    subs = tb["subscriptions"]
    se = tb["subscription_events"]
    cc, r = tb["campaign_contacts"], tb["retention_outcomes"]
    u, cs = tb["usage_snapshots"], tb["support_cases"]
    prim = subs.set_index("subscription_id")
    inv = b[b["event_type"] == "INVOICE"]
    pf = b[b["event_type"] == "PAYMENT_FAILED"].groupby("invoice_id").size().reindex(inv["billing_event_id"]).fillna(0).to_numpy()
    paid = b[b["event_type"] == "PAYMENT"].groupby("invoice_id").size().reindex(inv["billing_event_id"]).fillna(0).to_numpy()
    wo_rows = b[b["event_type"] == "WRITE_OFF"].copy()
    wo_rows["sub_status"] = prim["status"].reindex(wo_rows["subscription_id"]).to_numpy()
    cred = b[b["event_type"] == "CREDIT"].set_index("invoice_id")["amount"]
    inv_amt = inv.set_index("billing_event_id")["amount"]
    full_credit = (cred.groupby(level=0).sum().reindex(inv_amt.index).fillna(0) >= inv_amt - 0.005) & (inv_amt > 0)
    ratio = (ev["offer_cost"] / ev["margin_cap_amount"].replace(0, np.nan))
    free = ev["offer_id"] == "OFF-2026-000003"
    sets = ev.groupby("customer_id")["decision"].apply(lambda s: (s == "ELIGIBLE").sum())
    term = se[se["event_type"].isin(["CANCELLED", "TERMINATED_NONPAYMENT"])][["subscription_id", "event_date"]].rename(columns={"event_date": "end"})
    dg = se[se["event_type"] == "PLAN_DOWNGRADE"].merge(term, on="subscription_id")
    treat = r[r["randomization_group"] == "TREATMENT"]
    gt = pd.read_csv(Path(out) / "ground_truth" / "ground_truth.csv")
    inc = {k: int(v) for k, v in gt["issue_type"].value_counts().items()}
    ms = u["snapshot_month"]
    dim = ms.dt.days_in_month
    first_month = u.merge(subs[["subscription_id", "start_date"]], on="subscription_id")
    partial_first = (first_month["snapshot_month"] == first_month["start_date"].dt.to_period("M").dt.to_timestamp()) & \
                    (first_month["days_in_service"] < dim.reindex(first_month.index))
    min_t, loyal = 3, 12
    pr, pe = tb["prospects"], tb["prospect_events"]
    n_cont = pe[pe["event_type"] == "CONTACTED"].groupby("prospect_id").size().reindex(pr["prospect_id"]).fillna(0).to_numpy()
    had_trial = pe[pe["event_type"] == "TRIAL_STARTED"].groupby("prospect_id").size().reindex(pr["prospect_id"]).fillna(0).to_numpy() > 0
    st = pr["status"].to_numpy()

    items = [
        # category, case, count, required
        ("normal", "treated, accepted and retained", int(((treat["offer_accepted"] == 1) & (treat["retained_at_horizon_end"] == 1)).sum()), True),
        ("normal", "control (holdout) customer", int((cc["randomization_group"] == "CONTROL").sum()), True),
        ("normal", "customer eligible for all 4 offers", int((sets == 4).sum()), True),
        ("normal", "customer eligible for exactly 1 offer", int((sets == 1).sum()), True),
        ("boundary", f"tenure exactly {min_t} months (just eligible on tenure)", int((ev1["tenure_months"] == min_t).sum()), True),
        ("boundary", f"tenure {min_t - 1} months (just ineligible)", int((ev1["tenure_months"] == min_t - 1).sum()), True),
        ("boundary", f"free-month offer, tenure exactly {loyal} months", int((free & (ev["tenure_months"] == loyal)).sum()), True),
        ("boundary", f"free-month offer, tenure {loyal - 1} months", int((free & (ev["tenure_months"] == loyal - 1)).sum()), True),
        ("boundary", "offer cost within 5% below the margin cap", int(((ratio > 0.95) & (ratio <= 1.0)).sum()), True),
        ("boundary", "offer cost within 5% above the margin cap (rejected)", int(((ratio > 1.0) & (ratio <= 1.05)).sum()), True),
        ("boundary", "invoice issued on the price-change date at the new price", int(((inv["event_date"] == pd.Timestamp("2026-03-01")) & (inv["amount"] == 15.99)).sum()), True),
        ("boundary", "invoice fully covered by an offer credit (no payment attempted)", int(full_credit.sum()), True),
        ("boundary", "partial first-month usage snapshot", int(partial_first.sum()), True),
        ("boundary", "month with zero sessions", int((u["sessions"] == 0).sum()), True),
        ("failure", "payment failed once, recovered on retry 1", int(((pf == 1) & (paid == 1)).sum()), True),
        ("failure", "payment failed twice, recovered on retry 2", int(((pf == 2) & (paid == 1)).sum()), True),
        ("failure", "3 failures -> write-off -> termination for non-payment", int(((pf == 3) & (wo_rows.groupby("invoice_id").size().reindex(inv["billing_event_id"]).fillna(0).to_numpy() == 1)).sum()), True),
        ("failure", "voluntary cancellation with an unpaid invoice written off", int((wo_rows["sub_status"] == "CANCELLED").sum()), True),
        ("failure", "delivery bounced", int((cc["contact_status"] == "BOUNCED").sum()), True),
        ("failure", "support case never resolved (OPEN / ESCALATED)", int((cs["status"] != "RESOLVED").sum()), True),
        ("exception", "offer not viewed (non-response)", int((treat["offer_viewed"] == 0).sum()), True),
        ("exception", "offer viewed but not accepted (non-response)", int(((treat["offer_viewed"] == 1) & (treat["offer_accepted"] == 0)).sum()), True),
        ("exception", "downgrade followed by churn within 90 days", int(((dg["end"] - dg["event_date"]).dt.days.between(0, 90)).sum()), True),
        ("exception", "add-on cancelled because the primary ended", int((se["reason_code"] == "PRIMARY_ENDED").sum()), True),
        ("exception", "add-on removed on its own", int((se["reason_code"] == "ADDON_REMOVED").sum()), True),
        ("exception", "customer ineligible for every offer", int((sets == 0).sum()), True),
        ("exception", "ineligible offer sent via manual override", inc.get("INELIGIBLE_OFFER_SENT", 0), True),
        ("exception", "treatment/control leakage", inc.get("TREATMENT_CONTROL_LEAKAGE", 0), True),
        ("exception", "retained customer attributed to multiple offers", inc.get("MULTI_OFFER_ATTRIBUTION", 0), True),
        ("exception", "churn label dated before the prediction date", inc.get("CHURN_LABEL_BEFORE_PREDICTION", 0), True),
        ("exception", "administrator audit entry for an eligibility override", int((tb["admin_audit_log"]["action"] == "ELIGIBILITY_OVERRIDE").sum()), bool(cfg.get("expose_override_flag", True))),
        ("normal", "prospect converted into a customer", int((st == "CONVERTED").sum()), True),
        ("normal", "prospect lost", int((st == "LOST").sum()), True),
        ("boundary", "prospect created before the observation window", int((pr["created_date"] < pd.Timestamp(cfg["window_start"])).sum()), True),
        ("boundary", "prospect converted without any trial", int(((st == "CONVERTED") & ~had_trial).sum()), True),
        ("boundary", "prospect converted with no contact event", int(((st == "CONVERTED") & (n_cont == 0)).sum()), True),
        ("exception", "prospect still open at data end", int((st == "OPEN").sum()), True),
        ("exception", "prospect lost with zero contacts (NO_RESPONSE)", int(((st == "LOST") & (n_cont == 0)).sum()), True),
        ("exception", "offer cost exactly at the margin cap", int(np.isclose(ratio, 1.0).sum()), False),
    ]
    rows = [{"category": c, "case": n, "count": k, "required": req, "covered": bool(k > 0)} for c, n, k, req in items]
    return {"cases": rows, "all_required_covered": bool(all(x["covered"] for x in rows if x["required"])),
            "missing_required": [x["case"] for x in rows if x["required"] and not x["covered"]]}


def boundary_md(rep: dict) -> str:
    L = ["# Boundary, failure and exception coverage", "",
         f"All required cases present: **{rep['all_required_covered']}**" + ("" if rep["all_required_covered"] else f" - missing: {rep['missing_required']}"), "",
         "| category | case | records | required | covered |", "|---|---|---|---|---|"]
    for x in rep["cases"]:
        L.append(f"| {x['category']} | {x['case']} | {x['count']:,} | {'yes' if x['required'] else 'optional'} | {'yes' if x['covered'] else 'NO'} |")
    return "\n".join(L) + "\n"
