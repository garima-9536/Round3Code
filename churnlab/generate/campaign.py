"""Step 3: offer eligibility, margin limits, randomised treatment/control and offer response.

Everything here only uses information dated strictly before `prediction_date`, except the (random)
response to the offer which is the experiment outcome. Offer effect is causal: accepting an offer shifts
the voluntary-churn log-odds for `wave_offer_effect_months` months; acceptance itself is correlated with
churn risk (selection), so naive accepter-vs-non-accepter comparisons are biased - by design.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from .. import ids
from ..config import Config
from .master import OFFER_BETA, OFFER_DEFS, PLAN_CODES, campaign_id_array
from .simulate import resolve, sigmoid


def _cmp(op: str, a, b):
    return {">=": a >= b, "==": a == b, "<=": a <= b}[op]


def monthly_credit_cents(offer_idx: np.ndarray, price_c: np.ndarray) -> np.ndarray:
    """Frozen per-invoice credit at the plan price in force when the offer was evaluated."""
    out = np.zeros(len(offer_idx), dtype=np.int64)
    for k, (_, typ, pct, fixed, dur) in enumerate(OFFER_DEFS):
        m = offer_idx == k
        if typ == "PCT_DISCOUNT":
            out[m] = (price_c[m] * int(pct) + 50) // 100
        elif typ == "FREE_MONTHS":
            out[m] = price_c[m]
        else:
            out[m] = np.minimum(int(round(fixed * 100)), price_c[m])
    return out


def run_campaign(cfg: Config, P, H, R0, offers: pd.DataFrame, rules: pd.DataFrame, bridge: pd.DataFrame, streams) -> SimpleNamespace:
    r = streams.get("campaign")
    N, T = P.N, P.T
    pm = cfg.pred_month_idx
    he = pm + cfg.horizon_months
    pred = np.datetime64(cfg.prediction_date, "D")
    started = P.start < pred
    alive = started & ~((R0.end_month >= 0) & (R0.end_month < pm))
    inscope = alive

    # ---- facts known before the prediction date ---------------------------------------------
    plan_c = H.plan[:, pm - 1]
    price_c = H.price[plan_c, pm - 1]
    cost_c = H.cost[plan_c, pm - 1]
    margin_c = price_c - cost_c
    tenure = np.floor((pred - P.start).astype(float) / 30.4375).astype(np.int64)
    win0 = pred - np.timedelta64(cfg.recent_failure_window_days, "D")
    nfail = np.zeros(N, dtype=np.int64)
    for m in (pm - 2, pm - 1):
        if m < 0:
            continue
        bill = m >= P.first_bill
        for day, need in ((1, 1), (8, 2), (15, 3)):
            d = H.month_starts[m] + np.timedelta64(day - 1, "D")
            hit = bill & (H.outcome[:, m] >= need) & (d >= win0) & (d < pred)
            nfail += hit

    # ---- eligibility: rules effective on the evaluation date, linked to offers via bridge --------
    def effective(df):
        e = (df["effective_from"] <= cfg.prediction_date) & (df["effective_to"].isna() | (df["effective_to"] >= cfg.prediction_date))
        return e

    rules_eff = rules[effective(rules) & (rules["status"] == "ACTIVE")].set_index("rule_id")
    bridge_eff = bridge[effective(bridge)]
    offer_ids = list(offers["offer_id"])
    n_off = len(offer_ids)
    planned_c = np.zeros((N, n_off), dtype=np.int64)
    credit_c = np.zeros((N, n_off), dtype=np.int64)
    for k in range(n_off):
        credit_c[:, k] = monthly_credit_cents(np.full(N, k), price_c)
        planned_c[:, k] = credit_c[:, k] * OFFER_DEFS[k][4]

    elig = np.zeros((N, n_off), dtype=bool)
    fail_codes = [[[] for _ in range(n_off)] for _ in range(N)]  # filled only for in-scope rows
    idx_scope = np.nonzero(inscope)[0]
    passed = {}
    for k, oid in enumerate(offer_ids):
        ok = np.ones(N, dtype=bool)
        for rid in bridge_eff.loc[bridge_eff["offer_id"] == oid, "rule_id"]:
            if rid not in rules_eff.index:
                continue
            rr = rules_eff.loc[rid]
            code, op, thr = rr["rule_code"], rr["operator"], float(rr["threshold_value"])
            if code == "MIN_TENURE_MONTHS":
                res = _cmp(op, tenure, thr)
            elif code == "MARKETING_CONSENT":
                res = _cmp(op, P.consent.astype(int), thr)
            elif code == "MAX_FAILED_PAYMENTS_WINDOW":
                res = _cmp(op, nfail, thr)
            elif code == "MARGIN_CAP_PCT":
                res = planned_c[:, k] * 100 <= int(thr) * margin_c * cfg.margin_horizon_months
            else:
                raise ValueError(code)
            passed[(k, rid)] = (res, code)
            ok &= res
        elig[:, k] = ok & inscope

    # decision log rows
    ev_rows = []
    n_ev = 0
    ev_id = {}
    for i in idx_scope:
        for k in range(n_off):
            n_ev += 1
            fails = [code for (kk, rid), (res, code) in passed.items() if kk == k and not res[i]]
            ev_id[(i, k)] = ids.evaluation(n_ev)
            ev_rows.append((
                ev_id[(i, k)], P.cust_ids[i], f"SUB-{P.cust_ids[i]}-01", offer_ids[k], cfg.prediction_date, int(tenure[i]),
                PLAN_CODES[plan_c[i]], int(P.consent[i]), int(nfail[i]), margin_c[i] / 100, planned_c[i, k] / 100,
                int(cfg.margin_cap_pct) * margin_c[i] * cfg.margin_horizon_months / 10000,
                ";".join(fails) if fails else None, "ELIGIBLE" if elig[i, k] else "INELIGIBLE"))
    evals = pd.DataFrame(ev_rows, columns=[
        "evaluation_id", "customer_id", "subscription_id", "offer_id", "evaluated_on", "tenure_months", "plan_code",
        "marketing_consent", "failed_payments_window", "monthly_margin", "offer_cost", "margin_cap_amount",
        "failed_rules", "decision"])

    # ---- randomisation within strata (plan x tenure band) ----------------------------------------
    eligible_any = elig.any(1)
    multi = cfg.n_campaigns > 1
    stratum = plan_c * 2 + (tenure >= cfg.loyalty_tenure_months) + (6 * P.seg if multi else 0)  # each campaign randomised on its own
    cmp_ids = campaign_id_array(cfg, P.seg)
    group = np.zeros(N, dtype=np.int64)  # 0 none, 1 treatment, 2 control
    for s in np.unique(stratum[eligible_any]):
        idx = np.nonzero(eligible_any & (stratum == s))[0]
        perm = r.permutation(idx)
        nt = int(round(cfg.treat_share * len(perm)))
        group[perm[:nt]] = 1
        group[perm[nt:]] = 2
    n_anom = max(3, int(round(cfg.anomaly_rate * N)))
    pool = np.nonzero(inscope & ~eligible_any)[0]
    override = np.zeros(N, dtype=bool)
    if len(pool):
        override[r.choice(pool, size=min(n_anom, len(pool)), replace=False)] = True
        group[override] = 1

    sc = np.where(elig, r.random((N, n_off)), -1.0)
    choice = np.where(override, r.integers(0, n_off, N), sc.argmax(1))
    channel = r.choice(3, N, p=[0.50, 0.25, 0.25])
    bounced = r.random(N) < 0.03
    viewed_p = np.array([0.55, 0.70, 0.80])[channel]
    viewed = (~bounced) & (r.random(N) < viewed_p)
    p_acc = sigmoid(-0.95 + 1.1 * P.risk0 + 1.2 * H.depth[:, pm - 1] + 0.6 * H.shock[:, pm - 1] + 0.5 * (P.price_sens - 0.9))
    would_accept = viewed & (r.random(N) < p_acc)
    contact_lag = r.integers(0, 4, N) + r.integers(0, 5, N)
    accepted_at = pred + contact_lag.astype("timedelta64[D]")

    in_exp = (group > 0)  # treated/control/override are all part of the randomised population
    would_accept &= in_exp
    treated_obs = (group == 1)
    acc_obs = would_accept & treated_obs

    # ---- causal effect of accepting the offer ------------------------------------------------------
    resp = (0.3 + 0.8 * P.price_sens) * np.where(P.seg == 1, 0.7, 1.0)
    delta = np.where(P.backlash, 0.25, -OFFER_BETA[choice] * resp)
    shift = np.zeros((N, T))
    for m in range(pm, min(T, pm + cfg.wave_offer_effect_months)):
        shift[:, m] = np.where(would_accept, delta, 0.0)

    # billing credits (frozen amounts) for would-accept customers in the hypothetical world
    credit_mat_h = np.zeros((N, T), dtype=np.int64)
    offer_mat_h = np.full((N, T), -1, dtype=np.int64)
    cfrozen = credit_c[np.arange(N), choice]
    dur = np.array([d[4] for d in OFFER_DEFS])[choice]
    price_nt = H.price[H.plan, np.arange(T)[None, :]]
    for m in range(pm + 1, T):
        k = m - (pm + 1)
        on = would_accept & (k < dur)
        credit_mat_h[:, m] = np.where(on, np.minimum(cfrozen, price_nt[:, m]), 0)
        offer_mat_h[:, m] = np.where(on, choice, -1)
    skip_h = (credit_mat_h > 0) & (credit_mat_h >= price_nt)

    R1 = resolve(cfg, P, H, shift=shift, skip=skip_h)
    use_w1 = acc_obs
    end_month = np.where(use_w1, R1.end_month, R0.end_month)
    end_day = np.where(use_w1, R1.end_day, R0.end_day)
    end_type = np.where(use_w1, R1.end_type, R0.end_type)
    credit_obs = np.where(use_w1[:, None], credit_mat_h, 0)
    offer_obs = np.where(use_w1[:, None], offer_mat_h, -1)

    y0 = inscope & (R0.end_month >= pm) & (R0.end_month < he)
    y1 = inscope & (R1.end_month >= pm) & (R1.end_month < he)

    # ---- contacts (baseline, valid) ------------------------------------------------------------------
    cidx = np.nonzero(group > 0)[0]
    rows = []
    seg_pre = ["CONSUMER|", "SMB|"] if multi else ["", ""]
    stratum_lbl = {i: f"{seg_pre[P.seg[i]]}{PLAN_CODES[plan_c[i]]}|TENURE_{'12P' if tenure[i] >= cfg.loyalty_tenure_months else 'LT12'}" for i in cidx}
    ch_names = ["EMAIL", "SMS", "IN_APP"]
    for n, i in enumerate(cidx, start=1):
        grp = "TREATMENT" if group[i] == 1 else "CONTROL"
        if grp == "CONTROL":
            rows.append((ids.contact(n), cmp_ids[i], P.cust_ids[i], f"SUB-{P.cust_ids[i]}-01", None, grp, stratum_lbl[i],
                         cfg.prediction_date, None, "HOLDOUT", "AUTO_ELIGIBLE", "SYSTEM", None, None))
        elif override[i]:
            role = "MARKETING_OPS" if r.random() < 0.5 else "SALES_OPS"
            rows.append((ids.contact(n), cmp_ids[i], P.cust_ids[i], f"SUB-{P.cust_ids[i]}-01", offer_ids[choice[i]], grp,
                         stratum_lbl[i], cfg.prediction_date, ch_names[channel[i]], "BOUNCED" if bounced[i] else "DELIVERED", "MANUAL_OVERRIDE",
                         role, None, None))
        else:
            rows.append((ids.contact(n), cmp_ids[i], P.cust_ids[i], f"SUB-{P.cust_ids[i]}-01", offer_ids[choice[i]], grp,
                         stratum_lbl[i], cfg.prediction_date, ch_names[channel[i]], "BOUNCED" if bounced[i] else "DELIVERED",
                         "AUTO_ELIGIBLE", "SYSTEM", ev_id[(i, choice[i])], None))
    contacts = pd.DataFrame(rows, columns=[
        "contact_id", "campaign_id", "customer_id", "subscription_id", "offer_id", "randomization_group", "randomization_stratum",
        "contact_date", "channel", "contact_status", "contact_source", "launched_by_role", "eligibility_evaluation_id",
        "override_reason"])

    return SimpleNamespace(
        inscope=inscope, elig=elig, evals=evals, contacts=contacts, cidx=cidx, group=group, override=override, choice=choice,
        viewed=viewed & treated_obs, accepted=acc_obs, accepted_at=accepted_at, would_accept=would_accept, delta=delta,
        tenure=tenure, plan_c=plan_c, price_c=price_c, end_month=end_month, end_day=end_day, end_type=end_type,
        credit_obs=credit_obs, offer_obs=offer_obs, y0=y0, y1=y1, R0=R0, R1=R1, nfail=nfail, n_anom=n_anom,
        offer_ids=offer_ids,
    )
