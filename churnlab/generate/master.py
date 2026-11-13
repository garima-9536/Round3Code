"""Step 2a: reference/master data - plans, offers, eligibility rules, customer & subscription cohorts."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import numpy as np
import pandas as pd

from .. import ids
from ..config import Config, add_months, month_start

PLAN_CODES = ["BASIC", "STANDARD", "PREMIUM", "ADDON"]
BASE_PRICE_C = {"BASIC": 999, "STANDARD": 1499, "PREMIUM": 2499, "ADDON": 499}
STD_V2_PRICE_C = 1599
UNIT_COST_C = {"BASIC": 550, "STANDARD": 750, "PREMIUM": 1100, "ADDON": 120}
PLAN_ABBR = {"BASIC": "BAS", "STANDARD": "STD", "PREMIUM": "PRE", "ADDON": "ADD"}
SEGMENTS = ["CONSUMER", "SMB"]
REGIONS = ["NORTH", "SOUTH", "EAST", "WEST"]
CHANNELS = ["ORGANIC", "PAID", "REFERRAL", "PARTNER"]
METHODS = ["CARD", "BANK_DEBIT", "WALLET"]


def price_matrices(cfg: Config):
    """price[plan, month] / cost[plan, month] in integer cents."""
    T = cfg.n_months
    price = np.zeros((4, T), dtype=np.int64)
    cost = np.zeros((4, T), dtype=np.int64)
    pim = (cfg.price_increase_date.year - cfg.window_start.year) * 12 + (cfg.price_increase_date.month - cfg.window_start.month)
    for p, code in enumerate(PLAN_CODES):
        price[p, :] = BASE_PRICE_C[code]
        cost[p, :] = UNIT_COST_C[code]
    price[1, pim:] = STD_V2_PRICE_C
    return price, cost, pim


def build_plans(cfg: Config) -> pd.DataFrame:
    old = dt.date(2020, 1, 1)
    rows = [
        ("PLN-BAS-V1", "BASIC", "CORE", 1, 9.99, 5.50, old, None, "ACTIVE"),
        ("PLN-STD-V1", "STANDARD", "CORE", 1, 14.99, 7.50, old, cfg.price_increase_date - dt.timedelta(days=1), "SUPERSEDED"),
        ("PLN-STD-V2", "STANDARD", "CORE", 2, 15.99, 7.50, cfg.price_increase_date, None, "ACTIVE"),
        ("PLN-PRE-V1", "PREMIUM", "CORE", 1, 24.99, 11.00, old, None, "ACTIVE"),
        ("PLN-ADD-V1", "ADDON", "ADDON", 1, 4.99, 1.20, old, None, "ACTIVE"),
    ]
    return pd.DataFrame(rows, columns=["plan_id", "plan_code", "product_type", "version", "monthly_price", "unit_cost",
                                       "effective_from", "effective_to", "status"])


def plan_id_for(plan_code_idx: np.ndarray, dates: np.ndarray, cfg: Config) -> np.ndarray:
    """plan_id in force on `dates` (datetime64[D]) for plan indexes."""
    inc = np.datetime64(cfg.price_increase_date)
    abbr = np.array([PLAN_ABBR[c] for c in PLAN_CODES])[plan_code_idx]
    ver = np.where((plan_code_idx == 1) & (dates >= inc), 2, 1)
    return np.array([f"PLN-{a}-V{v}" for a, v in zip(abbr, ver)], dtype=object)


# ---- offers & rules ---------------------------------------------------------------------
OFFER_DEFS = [
    # name, type, pct, fixed_credit, duration, true effect strength (log-odds), reference only
    ("15% off for 3 months", "PCT_DISCOUNT", 15.0, None, 3),
    ("30% off for 3 months", "PCT_DISCOUNT", 30.0, None, 3),
    ("1 free month", "FREE_MONTHS", 100.0, None, 1),
    ("$10 bill credit", "FIXED_CREDIT", None, 10.00, 1),
]
OFFER_BETA = np.array([1.40, 2.30, 2.00, 1.20])  # latent causal strength per offer (ground truth only)


def campaign_id_array(cfg: Config, seg: np.ndarray) -> np.ndarray:
    """Campaign of each customer: the single campaign, or (n_campaigns=2) one campaign per segment."""
    if cfg.n_campaigns == 1:
        return np.full(len(seg), cfg.campaign_id, dtype=object)
    return np.array([f"{cfg.campaign_id}-{s}" for s in SEGMENTS], dtype=object)[seg]


def build_campaigns(cfg: Config) -> pd.DataFrame:
    if cfg.n_campaigns not in (1, 2):
        raise ValueError("n_campaigns must be 1 or 2")
    multi = cfg.n_campaigns == 2
    rows = []
    for k in range(cfg.n_campaigns):
        seg = SEGMENTS[k] if multi else "ALL"
        rows.append((f"{cfg.campaign_id}-{seg}" if multi else cfg.campaign_id,
                     f"Q3 2026 retention offer{' - ' + seg.lower() if multi else ''}", "reduce churn in the horizon with a bill-credit offer",
                     seg, cfg.prediction_date, cfg.horizon_end - dt.timedelta(days=1), cfg.treat_share, "MARKETING_OPS", "COMPLETED"))
    return pd.DataFrame(rows, columns=["campaign_id", "campaign_name", "objective", "target_segment", "start_date", "end_date",
                                       "planned_treat_share", "launched_by_role", "status"])


def build_offers(cfg: Config) -> pd.DataFrame:
    rows = []
    for k, (name, typ, pct, fixed, dur) in enumerate(OFFER_DEFS, start=1):
        rows.append((ids.offer(k), name, typ, pct, fixed, dur, dt.date(2026, 1, 1), dt.date(2026, 12, 31), "ACTIVE"))
    return pd.DataFrame(rows, columns=["offer_id", "offer_name", "offer_type", "discount_pct", "fixed_credit_amount",
                                       "duration_months", "valid_from", "valid_to", "status"])


def build_rules(cfg: Config):
    eff = dt.date(2026, 1, 1)
    rows = [
        (ids.rule(1), "MIN_TENURE_MONTHS", "Customer tenure at least N months", ">=", float(cfg.min_tenure_months), eff, None, "ACTIVE", None),
        (ids.rule(2), "MARKETING_CONSENT", "Customer has opted in to marketing", "==", 1.0, eff, None, "ACTIVE", None),
        (ids.rule(3), "MAX_FAILED_PAYMENTS_WINDOW", f"No failed payment in last {cfg.recent_failure_window_days} days", "<=", 0.0, eff, None, "ACTIVE", None),
        (ids.rule(4), "MARGIN_CAP_PCT", "Offer cost <= N% of margin over the margin horizon", "<=", float(cfg.margin_cap_pct), eff, None, "ACTIVE", None),
        (ids.rule(5), "MIN_TENURE_MONTHS", "Loyalty offer: tenure at least 12 months", ">=", float(cfg.loyalty_tenure_months), eff, None, "ACTIVE", None),
        (ids.rule(6), "MARGIN_CAP_PCT", "Superseded 2025 margin cap (80%)", "<=", 80.0, dt.date(2025, 1, 1), dt.date(2025, 12, 31), "RETIRED", ids.rule(4)),
    ]
    rules = pd.DataFrame(rows, columns=["rule_id", "rule_code", "description", "operator", "threshold_value",
                                        "effective_from", "effective_to", "status", "superseded_by_rule_id"])
    bridge_rows = []
    for k in range(1, 5):
        for r in (1, 2, 3, 4):
            bridge_rows.append((ids.offer(k), ids.rule(r), eff, None))
    bridge_rows.append((ids.offer(3), ids.rule(5), eff, None))  # free month needs 12m tenure
    bridge = pd.DataFrame(bridge_rows, columns=["offer_id", "rule_id", "effective_from", "effective_to"])
    return rules, bridge


# ---- customers ---------------------------------------------------------------------------
def build_population(cfg: Config, streams) -> SimpleNamespace:
    r = streams.get("master")
    N = cfg.n_customers
    T = cfg.n_months
    ws = np.datetime64(cfg.window_start, "D")
    total_days = int((np.datetime64(cfg.data_end, "D") - ws).astype(int)) + 1

    seg = (r.random(N) < 0.20).astype(np.int64)
    region = r.choice(4, N, p=[0.30, 0.25, 0.25, 0.20])
    chan = r.choice(4, N, p=[0.35, 0.30, 0.20, 0.15])
    consent = r.random(N) < np.where(seg == 1, 0.75, 0.84)
    method = r.choice(3, N, p=[0.60, 0.25, 0.15])
    plan0 = np.where(
        seg == 0,
        r.choice(3, N, p=[0.38, 0.46, 0.16]),
        r.choice(3, N, p=[0.12, 0.43, 0.45]),
    )

    is_new = r.random(N) < cfg.new_customer_share
    tenure_days = np.clip(r.gamma(1.6, 330, N), 30, 1800).astype(np.int64)
    new_off = r.integers(0, total_days - 45, N)
    start = np.where(is_new, ws + new_off, ws - tenure_days).astype("datetime64[D]")
    sm = start.astype("datetime64[M]")
    ws_m = ws.astype("datetime64[M]")
    start_month = (sm - ws_m).astype(np.int64)                      # <0 for pre-window customers
    start_day = (start - sm.astype("datetime64[D]")).astype(np.int64) + 1
    first_bill = np.where(start_month < 0, 0, start_month + (start_day > 1))
    first_haz = np.where(start_month < 0, 0, start_month + 1)

    # latent (ground-truth-only) traits
    risk0 = r.normal(size=N)
    seasonal = r.random(N) < 0.18
    peak = r.integers(0, 12, N)
    amp = np.where(seasonal, r.uniform(0.35, 0.65, N), 0.04)
    price_sens = r.uniform(0.3, 1.5, N)
    eng = r.lognormal(0.0, 0.35, N)
    min_factor = r.lognormal(0.0, 0.25, N)
    backlash = r.random(N) < 0.06

    # add-on subscription
    has_addon = r.random(N) < cfg.addon_share
    gap = r.integers(30, 300, N)
    a_start = (np.maximum(start, ws) + gap).astype("datetime64[D]")
    a_ok = a_start <= (np.datetime64(cfg.data_end, "D") - 30)
    has_addon &= a_ok
    a_sm = a_start.astype("datetime64[M]")
    a_start_month = (a_sm - ws_m).astype(np.int64)
    a_start_day = (a_start - a_sm.astype("datetime64[D]")).astype(np.int64) + 1
    a_first_bill = a_start_month + (a_start_day > 1)

    return SimpleNamespace(
        N=N, T=T, seg=seg, region=region, chan=chan, consent=consent, method=method, plan0=plan0,
        is_new=is_new, start=start, start_month=start_month, start_day=start_day, first_bill=first_bill,
        first_haz=first_haz, risk0=risk0, seasonal=seasonal, peak=peak, amp=amp, price_sens=price_sens, eng=eng,
        min_factor=min_factor, backlash=backlash, has_addon=has_addon, a_start=a_start, a_start_month=a_start_month,
        a_start_day=a_start_day, a_first_bill=a_first_bill,
        cust_ids=ids.cus_arr(np.arange(N)),
    )
