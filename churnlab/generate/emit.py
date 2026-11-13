"""Step 2c: emit child/event tables (events, usage, billing, support) from the simulated state.

Subscription rows, customer status, outcomes etc. are *derived* from these events in derive.py (step 6).
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from .. import ids
from ..config import Config
from .master import PLAN_CODES, plan_id_for

REASON_PRICE_USAGE_SERVICE = ["PRICE", "LOW_USAGE", "SERVICE_QUALITY"]
PLAN_MULT = np.array([0.6, 1.0, 1.5, 0.35])
SESSION_MIN = np.array([18.0, 22.0, 28.0, 10.0])


def _month_labels(cfg: Config, H):
    ms = H.month_starts[:-1].astype("datetime64[M]")
    years = ms.astype("datetime64[Y]").astype(int) + 1970
    months = (ms.astype(int) % 12) + 1
    return years, months


def build_sub_arrays(cfg: Config, P, H, C) -> SimpleNamespace:
    """Unified sub-level arrays: rows 0..N-1 are primaries (-01), then add-ons (-02)."""
    N, T = P.N, P.T
    end_m, end_d, end_t = C.end_month.copy(), C.end_day.copy(), C.end_type.copy()

    # add-ons exist only while the primary is alive at their start
    has = P.has_addon.copy()
    prim_end_key = np.where(end_m >= 0, end_m * 100 + end_d, 10**9)
    a_start_key = P.a_start_month * 100 + P.a_start_day
    has &= prim_end_key > a_start_key
    aidx = np.nonzero(has)[0]
    A = len(aidx)

    a_own_key = np.where(H.a_cancel_month[aidx] >= 0, H.a_cancel_month[aidx] * 100 + H.a_cancel_day[aidx], 10**9)
    a_prim_key = prim_end_key[aidx]
    a_end_key = np.minimum(a_own_key, a_prim_key)
    a_end_m = np.where(a_end_key < 10**9, a_end_key // 100, -1)
    a_end_d = np.where(a_end_key < 10**9, a_end_key % 100, 0)
    a_end_t = np.where(a_end_key >= 10**9, 0, np.where(a_own_key < a_prim_key, 3, 4))  # 3 removed, 4 primary ended

    cust = np.concatenate([np.arange(N), aidx])
    S = N + A
    s = SimpleNamespace(
        S=S, N=N, A=A, cust=cust, is_primary=np.concatenate([np.ones(N, bool), np.zeros(A, bool)]),
        k=np.concatenate([np.ones(N, int), np.full(A, 2)]),
        start=np.concatenate([P.start, P.a_start[aidx]]),
        start_month=np.concatenate([P.start_month, P.a_start_month[aidx]]),
        start_day=np.concatenate([P.start_day, P.a_start_day[aidx]]),
        first_bill=np.concatenate([P.first_bill, P.a_first_bill[aidx]]),
        end_month=np.concatenate([end_m, a_end_m]), end_day=np.concatenate([end_d, a_end_d]),
        end_type=np.concatenate([end_t, a_end_t]),
        plan=np.vstack([H.plan, np.full((A, T), 3, dtype=np.int64)]),
        outcome=np.vstack([H.outcome, np.zeros((A, T), dtype=np.int64)]),
        credit=np.vstack([C.credit_obs, np.zeros((A, T), dtype=np.int64)]),
        offer=np.vstack([C.offer_obs, np.full((A, T), -1, dtype=np.int64)]),
        initial_plan=np.concatenate([P.plan0, np.full(A, 3)]),
    )
    s.last = np.where(s.end_month >= 0, s.end_month, T - 1)
    s.sub_ids = np.array([ids.sub(P.cust_ids[c], k) for c, k in zip(s.cust, s.k)], dtype=object)
    return s


def emit_subscription_events(cfg: Config, P, H, s, streams) -> pd.DataFrame:
    r = streams.get("events")
    T = P.T
    ms = H.month_starts
    blocks = []

    # ACTIVATED
    plan_id = plan_id_for(s.initial_plan, s.start, cfg)
    blocks.append(pd.DataFrame({"s": np.arange(s.S), "date": s.start, "rank": 0, "event_type": "ACTIVATED",
                                "from_plan": None, "to_plan": s.initial_plan, "plan_id": plan_id, "reason_code": None}))

    # plan changes (primary only)
    chg = H.chg[: s.N]
    ii, mm = np.nonzero(chg != 0)
    keep = mm <= s.last[ii]
    ii, mm = ii[keep], mm[keep]
    if len(ii):
        d = ms[mm]
        to = H.plan[ii, mm]
        blocks.append(pd.DataFrame({
            "s": ii, "date": d, "rank": 1,
            "event_type": np.where(chg[ii, mm] > 0, "PLAN_UPGRADE", "PLAN_DOWNGRADE"),
            "from_plan": H.plan[ii, mm - 1], "to_plan": to, "plan_id": plan_id_for(to, d, cfg), "reason_code": None}))

    # price change (STANDARD price rise)
    pim = H.pim
    sel = np.nonzero((H.plan[: s.N, pim - 1] == 1) & (H.plan[: s.N, pim] == 1) & (P.start_month < pim) & (s.last[: s.N] >= pim))[0]
    if len(sel):
        d = np.full(len(sel), ms[pim])
        blocks.append(pd.DataFrame({"s": sel, "date": d, "rank": 2, "event_type": "PRICE_CHANGE", "from_plan": 1, "to_plan": 1,
                                    "plan_id": plan_id_for(np.ones(len(sel), int), d, cfg), "reason_code": None}))

    # terminal events
    ch = np.nonzero(s.end_month >= 0)[0]
    em, ed, et = s.end_month[ch], s.end_day[ch], s.end_type[ch]
    date = ms[em] + (ed - 1).astype("timedelta64[D]")
    reason = np.empty(len(ch), dtype=object)
    etype = np.empty(len(ch), dtype=object)
    prim = ch < s.N
    # voluntary primary: reason from the dominant behavioural driver at the churn month
    vol = prim & (et == 1)
    iv = ch[vol]
    contrib = np.stack([H.c_price[iv, em[vol]], H.c_usage[iv, em[vol]], H.c_service[iv, em[vol]]], axis=1)
    top = contrib.argmax(1)
    other = np.where(r.random(len(iv)) < 0.5, "COMPETITOR", "OTHER")
    reason[vol] = np.where(contrib.max(1) > 0.35, np.array(REASON_PRICE_USAGE_SERVICE, dtype=object)[top], other)
    etype[vol] = "CANCELLED"
    inv = prim & (et == 2)
    reason[inv] = "NONPAYMENT"
    etype[inv] = "TERMINATED_NONPAYMENT"
    reason[~prim & (et == 3)] = "ADDON_REMOVED"
    reason[~prim & (et == 4)] = "PRIMARY_ENDED"
    etype[~prim] = "CANCELLED"
    to = s.plan[ch, em]
    blocks.append(pd.DataFrame({"s": ch, "date": date, "rank": 3, "event_type": etype, "from_plan": None, "to_plan": to,
                                "plan_id": plan_id_for(to, date, cfg), "reason_code": reason}))

    ev = pd.concat(blocks, ignore_index=True)
    ev = ev.sort_values(["s", "date", "rank"], kind="stable").reset_index(drop=True)
    ev["event_seq"] = ev.groupby("s").cumcount() + 1
    ev["subscription_id"] = s.sub_ids[ev["s"].to_numpy()]
    ev["subscription_event_id"] = [f"SEV-{sid}-{n:02d}" for sid, n in zip(ev["subscription_id"], ev["event_seq"])]
    codes = np.array(PLAN_CODES + [None], dtype=object)
    ev["from_plan_code"] = codes[ev["from_plan"].fillna(4).astype(int).to_numpy()]
    ev["to_plan_code"] = codes[ev["to_plan"].astype(int).to_numpy()]
    ev["event_date"] = ev["date"]
    return ev


def emit_usage(cfg: Config, P, H, s, streams) -> pd.DataFrame:
    r = streams.get("usage")
    T = P.T
    m = np.arange(T)[None, :]
    mask = (m >= np.maximum(s.start_month, 0)[:, None]) & (m <= s.last[:, None])
    ii, mm = np.nonzero(mask)
    cu = s.cust[ii]
    dim = H.dim[mm]
    d_from = np.where(mm == s.start_month[ii], s.start_day[ii], 1)
    d_to = np.where(mm == s.end_month[ii], s.end_day[ii], dim)
    dps = np.maximum(d_to - d_from + 1, 1)
    plan = s.plan[ii, mm]
    season = 1 + P.amp[cu] * np.cos(2 * np.pi * (H.cal[mm] - P.peak[cu]) / 12)
    depth = H.depth[cu, mm]
    lam = 22 * P.eng[cu] * PLAN_MULT[plan] * season * np.exp(-depth) * (dps / dim)
    sessions = r.poisson(np.maximum(lam, 0))
    exp_days = dps * (1 - np.exp(-sessions / np.maximum(dps, 1)))
    ad = r.binomial(dps, np.clip(exp_days / np.maximum(dps, 1), 0, 1))
    active = np.where(sessions > 0, np.clip(ad, 1, np.minimum(dps, np.maximum(sessions, 1))), 0)
    avg = np.clip(SESSION_MIN[plan] * P.min_factor[cu] * (1 - 0.15 * np.minimum(depth, 1.5)) * r.lognormal(0, 0.1, len(ii)), 3, 120)
    avg = np.where(sessions > 0, np.round(avg, 2), 0.0)
    hours = np.round(sessions * avg / 60.0, 2)
    p_feat = np.clip(0.20 + 0.18 * np.minimum(plan, 2) + 0.15 * np.exp(-depth), 0.05, 0.95)
    feats = r.binomial(10, p_feat)
    years, months = _month_labels(cfg, H)
    sub = s.sub_ids[ii]
    return pd.DataFrame({
        "snapshot_id": [f"SNAP-{a}-{years[b]}-{months[b]:02d}" for a, b in zip(sub, mm)],
        "subscription_id": sub, "snapshot_month": H.month_starts[mm], "plan_code": np.array(PLAN_CODES, dtype=object)[plan],
        "days_in_service": dps, "sessions": sessions, "active_days": active, "avg_session_minutes": avg,
        "usage_hours": hours, "features_used": feats,
    })


BILL_RANK = {"INVOICE": 0, "CREDIT": 1, "PAYMENT_FAILED": 2, "PAYMENT": 3, "WRITE_OFF": 4}


def emit_billing(cfg: Config, P, H, s, streams) -> pd.DataFrame:
    r = streams.get("billing")
    T = P.T
    m = np.arange(T)[None, :]
    mask = (m >= s.first_bill[:, None]) & (m <= s.last[:, None])
    ii, mm = np.nonzero(mask)
    n = len(ii)
    plan = s.plan[ii, mm]
    price = H.price[plan, mm]
    cost = H.cost[plan, mm]
    credit = s.credit[ii, mm]
    off = s.offer[ii, mm]
    net = price - credit
    out = s.outcome[ii, mm]
    end_day = np.where(mm == s.end_month[ii], s.end_day[ii], 99)
    rid = np.arange(n)
    zeros = np.zeros(n, dtype=np.int64)

    def blk(sel, typ, day, amount, **kw):
        d = pd.DataFrame({"row": rid[sel], "s": ii[sel], "m": mm[sel], "event_type": typ, "day": day[sel] if hasattr(day, "__len__") else day,
                          "amount_c": amount[sel]})
        for k, v in kw.items():
            d[k] = v[sel] if hasattr(v, "__len__") else v
        return d

    allr = np.ones(n, dtype=bool)
    pay = net > 0
    blocks = [
        blk(allr, "INVOICE", np.ones(n, int), price, service_cost_c=cost),
        blk(credit > 0, "CREDIT", np.ones(n, int), credit, offer_idx=off),
        blk(pay & (out == 0), "PAYMENT", np.ones(n, int), net),
        blk(pay & (out >= 1), "PAYMENT_FAILED", np.ones(n, int), net),
        blk(pay & (out == 1), "PAYMENT", np.full(n, 8), net),
        blk(pay & (out >= 2), "PAYMENT_FAILED", np.full(n, 8), net),
        blk(pay & (out == 2), "PAYMENT", np.full(n, 15), net),
        blk(pay & (out == 3), "PAYMENT_FAILED", np.full(n, 15), net),
        blk(pay & (out == 3), "WRITE_OFF", np.full(n, 22), net),
    ]
    ev = pd.concat(blocks, ignore_index=True)
    ev = ev[ev["day"] <= end_day[ev["row"].to_numpy()]]
    # unresolved invoice in the month the subscription ended -> written off on the end date
    resolved = np.zeros(n, dtype=bool)
    rs = ev[ev["event_type"].isin(["PAYMENT", "WRITE_OFF"])]["row"].to_numpy()
    resolved[rs] = True
    unresolved = (end_day < 99) & pay & ~resolved
    wo = pd.DataFrame({"row": rid[unresolved], "s": ii[unresolved], "m": mm[unresolved], "event_type": "WRITE_OFF",
                       "day": end_day[unresolved], "amount_c": net[unresolved]})
    ev = pd.concat([ev, wo], ignore_index=True)
    ev["rank"] = ev["event_type"].map(BILL_RANK)
    ev = ev.sort_values(["s", "m", "day", "rank"], kind="stable").reset_index(drop=True)
    ev["nn"] = ev.groupby(["s", "m"]).cumcount() + 1
    years, months = _month_labels(cfg, H)
    sid = s.sub_ids[ev["s"].to_numpy()]
    ym = [f"{years[a]}{months[a]:02d}" for a in ev["m"]]
    ev["subscription_id"] = sid
    ev["billing_event_id"] = [f"BILL-{a}-{b}-{c:02d}" for a, b, c in zip(sid, ym, ev["nn"])]
    ev["invoice_id"] = [f"BILL-{a}-{b}-01" for a, b in zip(sid, ym)]
    ev.loc[ev["event_type"] == "INVOICE", "invoice_id"] = None
    ev["billing_period"] = [f"{years[a]}-{months[a]:02d}" for a in ev["m"]]
    ev["event_date"] = H.month_starts[ev["m"].to_numpy()] + (ev["day"].to_numpy() - 1).astype("timedelta64[D]")
    ev["amount"] = ev["amount_c"] / 100.0
    ev["currency"] = "USD"
    ev["service_cost"] = ev["service_cost_c"] / 100.0
    oi = ev["offer_idx"].fillna(-1).astype(int).to_numpy()
    ev["offer_id"] = [ids.offer(k + 1) if k >= 0 else None for k in oi]
    # failure reasons by payment method
    meth = P.method[s.cust[ev["s"].to_numpy()]]
    u = r.random(len(ev))
    reason = np.where(meth == 0, np.where(u < 0.6, "CARD_DECLINED", "INSUFFICIENT_FUNDS"),
                      np.where(meth == 1, np.where(u < 0.5, "BANK_REJECTED", "INSUFFICIENT_FUNDS"), "WALLET_ERROR"))
    ev["failure_reason"] = np.where(ev["event_type"] == "PAYMENT_FAILED", reason, None)
    return ev


def emit_cases(cfg: Config, P, H, s, streams) -> pd.DataFrame:
    r = streams.get("cases")
    cs = H.cases
    end_date_prim = np.where(s.end_month[: s.N] >= 0,
                             H.month_starts[np.maximum(s.end_month[: s.N], 0)] + (s.end_day[: s.N] - 1).astype("timedelta64[D]"),
                             np.datetime64("2100-01-01"))
    opened_date = H.month_starts[cs.month] + (cs.day - 1).astype("timedelta64[D]")
    ci = cs.cust
    keep = (opened_date >= s.start[ci]) & (opened_date < end_date_prim[ci])
    base = pd.DataFrame({
        "cust": ci[keep], "date": opened_date[keep], "minute": cs.minute[keep], "cat": cs.cat[keep], "prio": cs.prio[keep],
        "res_h": cs.res_h[keep], "fr_h": cs.fr_h[keep], "esc": cs.esc[keep], "chan": cs.chan[keep], "agent": cs.agent[keep],
        "csat_resp": cs.csat_resp[keep], "csat_u": cs.csat_u[keep]})

    # cancellation enquiries shortly before a voluntary cancellation (precede the churn event)
    vol = np.nonzero(s.end_type[: s.N] == 1)[0]
    inj = vol[r.random(len(vol)) < 0.30]
    lead = r.integers(2, 26, len(inj))
    d = end_date_prim[inj] - lead.astype("timedelta64[D]")
    ok = d >= (s.start[inj] + 1)
    inj, d = inj[ok], d[ok]
    n = len(inj)
    extra = pd.DataFrame({
        "cust": inj, "date": d, "minute": r.integers(480, 1200, n), "cat": 4, "prio": 1,
        "res_h": r.lognormal(np.log(10), 0.6, n), "fr_h": r.lognormal(np.log(1.5), 0.5, n),
        "esc": r.random(n) < 0.05, "chan": r.choice(3, n, p=[0.35, 0.40, 0.25]), "agent": r.integers(1, 41, n),
        "csat_resp": r.random(n) < 0.6, "csat_u": r.random(n)})
    extra["fr_h"] = np.minimum(extra["fr_h"], 0.8 * extra["res_h"])
    df = pd.concat([base, extra], ignore_index=True)
    df = df.sort_values(["cust", "date", "minute"], kind="stable").reset_index(drop=True)
    df["nn"] = df.groupby("cust").cumcount() + 1

    data_end_dt = np.datetime64(f"{cfg.data_end.isoformat()}T23:59:59")
    opened = df["date"].to_numpy().astype("datetime64[m]") + df["minute"].to_numpy().astype("timedelta64[m]")
    mins = lambda h: np.round(np.minimum(h, 1e5) * 60).astype("int64").astype("timedelta64[m]")
    res_t = opened + mins(df["res_h"].to_numpy())
    fr_t = opened + mins(np.maximum(df["fr_h"].to_numpy(), 1 / 60))
    esc_t = opened + mins(np.maximum(0.5 * np.minimum(df["res_h"].to_numpy(), 48), 1 / 60))
    resolved = (df["res_h"].to_numpy() < 1e5) & (res_t <= data_end_dt)
    fr_ok = fr_t <= data_end_dt
    esc_ok = df["esc"].to_numpy() & (esc_t <= data_end_dt)
    res_hours = np.round((res_t - opened).astype("timedelta64[m]").astype(float) / 60.0, 2)
    mean = 4.3 - 0.45 * np.log1p(df["res_h"].to_numpy().clip(0, 2000) / 24)
    score = np.clip(np.round(mean + (df["csat_u"].to_numpy() - 0.5) * 3.0), 1, 5).astype(int)
    status = np.where(resolved, "RESOLVED", np.where(esc_ok, "ESCALATED", "OPEN"))
    fmt = lambda a: np.char.replace(a.astype("datetime64[s]").astype(str), "T", " ")
    cust_ids = P.cust_ids[df["cust"].to_numpy()]
    out = pd.DataFrame({
        "case_id": [f"CASE-{c}-{n:02d}" for c, n in zip(cust_ids, df["nn"])],
        "customer_id": cust_ids,
        "subscription_id": [f"SUB-{c}-01" for c in cust_ids],
        "opened_at": fmt(opened),
        "first_response_at": np.where(fr_ok & (fr_t <= np.where(resolved, res_t, data_end_dt)), fmt(fr_t), None),
        "escalated_at": np.where(esc_ok & (~resolved | (esc_t <= res_t)), fmt(esc_t), None),
        "resolved_at": np.where(resolved, fmt(res_t), None),
        "status": status,
        "category": np.array(["TECHNICAL", "BILLING", "ACCOUNT", "FEEDBACK", "CANCELLATION_QUERY"], dtype=object)[df["cat"].to_numpy()],
        "priority": np.array(["LOW", "MEDIUM", "HIGH"], dtype=object)[df["prio"].to_numpy()],
        "channel": np.array(["PHONE", "CHAT", "EMAIL"], dtype=object)[df["chan"].to_numpy()],
        "assigned_agent_id": [ids.agent(a) for a in df["agent"]],
        "csat_score": pd.array(np.where(resolved & df["csat_resp"].to_numpy(), score, -1), dtype="Int64"),
        "resolution_hours": np.where(resolved, res_hours, np.nan),
    })
    out["csat_score"] = out["csat_score"].where(out["csat_score"] > 0, pd.NA)
    return out
