"""Step 2b/3: behavioural state simulation and the documented churn mechanism.

Mechanism (all rule based, nothing is an independent random label):
  * a latent dissatisfaction `risk0` drives (a) onset of *disengagement* (usage decay), (b) support
    contacts, (c) payment failures;
  * voluntary churn hazard = sigmoid(period intercept + 1.1*disengagement depth + 0.7*price shock
    + support load + unresolved/slow cases + recent downgrade + tenure/plan/segment/channel terms);
  * involuntary churn = dunning rule: first payment fails, two retries fail -> terminated on day 22;
  * seasonal users have usage dips that are NOT driven by disengagement (hard negatives).
State evolves for every customer ("shadow world"); records are only emitted while a subscription is
alive, so churn can be resolved afterwards for two potential-outcome worlds (no offer / offer accepted).
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from ..config import Config, month_start
from .master import price_matrices

DUNNING_TERMINATION_DAY = 22


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def roll_prev(x: np.ndarray, k: int) -> np.ndarray:
    """sum of x over the previous k months (excluding the current one)."""
    N, T = x.shape
    cs = np.concatenate([np.zeros((N, 1)), np.cumsum(x.astype(float), axis=1)], axis=1)
    out = np.zeros((N, T))
    for m in range(T):
        out[:, m] = cs[:, m] - cs[:, max(0, m - k)]
    return out


def month_arrays(cfg: Config):
    T = cfg.n_months
    starts = np.array([np.datetime64(month_start(cfg, m), "D") for m in range(T + 1)])
    dim = (starts[1:] - starts[:-1]).astype(int)
    cal = np.array([(cfg.window_start.month - 1 + m) % 12 for m in range(T)])
    return starts, dim, cal


def simulate_history(cfg: Config, P: SimpleNamespace, streams) -> SimpleNamespace:
    r = streams.get("state")
    N, T = P.N, P.T
    price, cost, pim = price_matrices(cfg)
    starts, dim, cal = month_arrays(cfg)

    plan = np.zeros((N, T), dtype=np.int64)
    chg = np.zeros((N, T), dtype=np.int64)
    depth = np.zeros((N, T))
    shock = np.zeros((N, T))
    cur = P.plan0.copy()
    dep = np.zeros(N)
    dis = np.zeros(N, dtype=bool)
    rate = r.uniform(0.15, 0.45, N)
    decay = {0: 1.0, 1: 1.0, 2: 0.7, 3: 0.4, 4: 0.2}

    for m in range(T):
        dprev = depth[:, m - 1] if m > 0 else np.zeros(N)
        u1, u2, u3, u4 = r.random(N), r.random(N), r.random(N), r.random(N)
        can = (P.start_month < m) & (m >= 1)
        p_chg = 0.008 + 0.012 * (dprev > 0.5)
        down = u2 < (0.35 + 0.5 * (dprev > 0.5))
        new = cur + np.where(down, -1, 1)
        ok = can & (u1 < p_chg) & (new >= 0) & (new <= 2)
        chg[:, m] = np.where(ok, new - cur, 0)
        cur = np.where(ok, new, cur)
        plan[:, m] = cur
        k = m - pim
        shock[:, m] = np.where(cur == 1, P.price_sens * decay.get(k, 0.0), 0.0) if k >= 0 else 0.0
        p_on = np.clip(0.012 * np.exp(0.7 * P.risk0 + 0.6 * shock[:, m]), 0, 0.4)
        onset = (~dis) & (u3 < p_on) & (P.start_month <= m)
        recov = dis & (u4 < 0.04)
        dis = (dis | onset) & ~recov
        dep = np.where(recov, 0.0, dep)
        dep = np.where(dis, np.minimum(dep + rate + r.normal(0, 0.05, N), 2.5), dep)
        depth[:, m] = np.maximum(dep, 0)

    # ---- payments / dunning outcome per invoice month ---------------------------------------
    pf_base = np.array([0.013, 0.005, 0.012])[P.method][:, None]
    pf = np.clip(pf_base * np.exp(0.3 * P.risk0[:, None] + 0.25 * depth), 0, 0.4)
    f1 = r.random((N, T)) < pf
    q = cfg.dunning_retry_success
    rec1 = r.random((N, T)) < q
    rec2 = r.random((N, T)) < q
    outcome = np.where(~f1, 0, np.where(rec1, 1, np.where(rec2, 2, 3)))  # 0 paid d1,1 paid d8,2 paid d15,3 terminated d22

    # ---- support cases ----------------------------------------------------------------------
    lam = 0.07 * np.exp(0.45 * P.risk0[:, None] + 0.8 * depth + 0.5 * (shock > 0.3) + 0.6 * f1)
    n_cases = np.minimum(r.poisson(lam), 4)
    n_cases = np.where(np.arange(T)[None, :] >= P.start_month[:, None], n_cases, 0)  # no cases before the subscription exists
    ii, mm = np.nonzero(n_cases)
    rep = n_cases[ii, mm]
    ci, cm = np.repeat(ii, rep), np.repeat(mm, rep)
    nc = len(ci)
    cdepth, cf1, cshock = depth[ci, cm], f1[ci, cm], shock[ci, cm]
    base_p = np.array([0.40, 0.22, 0.18, 0.17, 0.03])
    pc = np.tile(base_p, (nc, 1))
    pc[:, 1] += 0.30 * cf1 + 0.15 * (cshock > 0.3)
    pc /= pc.sum(1, keepdims=True)
    cat = (r.random(nc)[:, None] > np.cumsum(pc, axis=1)).sum(1)
    prio = r.choice(3, nc, p=[0.55, 0.33, 0.12])
    res_h = r.lognormal(np.log(20) + 0.25 * cdepth, 1.0) * np.array([1.0, 1.0, 0.6])[prio]
    res_h = np.where(r.random(nc) < 0.03, 1e6, res_h)           # abandoned / never resolved
    cases = SimpleNamespace(
        cust=ci, month=cm, day=r.integers(1, dim[cm] + 1), minute=r.integers(480, 1200, nc),
        cat=cat, prio=prio, res_h=res_h, fr_h=np.minimum(r.lognormal(np.log(3.0), 0.8, nc), 0.8 * res_h),
        esc=r.random(nc) < (0.08 + 0.10 * (res_h > 72)), chan=r.choice(3, nc, p=[0.35, 0.40, 0.25]),
        agent=r.integers(1, 41, nc), csat_resp=r.random(nc) < 0.6, csat_u=r.random(nc),
        cancel_query_injected=np.zeros(nc, dtype=bool),
    )
    n_slow = np.zeros((N, T))
    np.add.at(n_slow, (ci, cm), (res_h > 72).astype(float))

    # ---- hazard building blocks ----------------------------------------------------------------
    cases3 = np.minimum(roll_prev(n_cases, 3), 3)
    slow2 = np.minimum(roll_prev(n_slow, 2), 2)
    dg = (roll_prev((chg == -1), 3) > 0).astype(float)
    ten = (starts[:T][None, :] - P.start[:, None]).astype(float) / 30.4375
    ten_term = 0.55 * (ten < 6) + 0.25 * ((ten >= 6) & (ten < 12)) - 0.20 * (ten >= 36)
    plan_term = np.where(plan == 0, 0.25, np.where(plan == 2, -0.15, 0.0))
    method_term = np.where(P.method == 1, -0.2, 0.0)[:, None]
    seg_term = np.where(P.seg == 1, -0.3, 0.0)[:, None]
    chan_term = np.where(P.chan == 1, 0.3, np.where(P.chan == 3, -0.1, 0.0))[:, None]
    c_price = 0.7 * shock
    c_usage = 1.1 * depth
    c_service = 0.40 * cases3 + 0.45 * slow2
    z_base = (c_price + c_usage + c_service + 0.30 * P.risk0[:, None] + 0.35 * dg + ten_term + plan_term
              + method_term + seg_term + chan_term)

    # ---- add-on cancellation (independent small hazard) ---------------------------------------
    a_cancel_month = np.full(N, -1)
    a_cancel_day = np.zeros(N, dtype=np.int64)
    ra = streams.get("addon")
    ua = ra.random((N, T))
    hit = (ua < 0.012) & (np.arange(T)[None, :] > P.a_start_month[:, None]) & P.has_addon[:, None]
    has_hit = hit.any(1)
    a_cancel_month = np.where(has_hit, hit.argmax(1), -1)
    a_cancel_day = ra.integers(2, 29, N)

    return SimpleNamespace(
        plan=plan, chg=chg, depth=depth, shock=shock, f1=f1, outcome=outcome, n_cases=n_cases, cases=cases,
        z_base=z_base, c_price=c_price, c_usage=c_usage, c_service=c_service,
        u_vol=r.random((N, T)), d_vol=r.integers(2, 29, (N, T)), price=price, cost=cost, pim=pim,
        month_starts=starts, dim=dim, cal=cal, a_cancel_month=a_cancel_month, a_cancel_day=a_cancel_day,
    )


def intercept_vector(cfg: Config, intercepts=None) -> np.ndarray:
    a_pre, a_wave, a_post = intercepts or (cfg.intercept_pre, cfg.intercept_wave, cfg.intercept_post)
    pm = cfg.pred_month_idx
    he = pm + cfg.horizon_months
    t = np.arange(cfg.n_months)
    return np.where(t < pm, a_pre, np.where(t < he, a_wave, a_post))


def resolve(cfg: Config, P, H, shift=None, skip=None, intercepts=None) -> SimpleNamespace:
    """First churn event per customer for one potential-outcome world."""
    N, T = P.N, P.T
    z = H.z_base + intercept_vector(cfg, intercepts)[None, :]
    if shift is not None:
        z = z + shift
    h = sigmoid(z)
    m = np.arange(T)[None, :]
    vol = (H.u_vol < h) & (m >= P.first_haz[:, None])
    term = (H.outcome == 3) & (m >= P.first_bill[:, None])
    if skip is not None:
        term = term & ~skip
    vol_day = np.where(vol, H.d_vol, 99)
    term_day = np.where(term, DUNNING_TERMINATION_DAY, 99)
    ev = vol | term
    any_ev = ev.any(1)
    end_m = np.where(any_ev, ev.argmax(1), -1)
    idx = np.arange(N)
    em = np.maximum(end_m, 0)
    is_term = (term_day[idx, em] <= vol_day[idx, em]) & any_ev
    day = np.where(any_ev, np.minimum(vol_day[idx, em], term_day[idx, em]), 0)
    etype = np.where(~any_ev, 0, np.where(is_term, 2, 1))  # 0 none, 1 voluntary, 2 involuntary
    return SimpleNamespace(end_month=end_m, end_day=day, end_type=etype, h=h)


def calibration_stats(cfg: Config, P, H, intercepts) -> dict:
    R = resolve(cfg, P, H, intercepts=intercepts)
    pm = cfg.pred_month_idx
    he = pm + cfg.horizon_months
    started = P.start < np.datetime64(cfg.prediction_date, "D")
    pre = started & (R.end_month >= 0) & (R.end_month < pm)
    alive = started & ~pre
    wave = alive & (R.end_month >= pm) & (R.end_month < he)
    alive_post = alive & ~wave & ~((R.end_month >= 0) & (R.end_month < pm))
    post = alive_post & (R.end_month >= he)
    ever = (R.end_month >= 0)
    return {
        "pre_rate": pre.sum() / max(started.sum(), 1),
        "wave_rate": wave.sum() / max(alive.sum(), 1),
        "post_rate": post.sum() / max(alive_post.sum(), 1),
        "ever_churn_rate": ever.sum() / P.N,
        "involuntary_share": (R.end_type == 2).sum() / max(ever.sum(), 1),
    }
