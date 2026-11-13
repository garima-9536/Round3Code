"""Pre-customer funnel: prospects and their append-only event history.

Generated *after* (and independently of) the customer simulation, from its own random stream, so existing customers,
churn and offer results are unchanged. Customers acquired inside the window each come from a CONVERTED prospect whose
conversion date is the customer's activation date; additional leads are LOST or still OPEN at data end.

Documented conversion rule (probability that a lead converts):
    logit p = -1.9 + channel effect (ORGANIC +0.2, PAID -0.35, REFERRAL +0.9, PARTNER -0.1) + SMB -0.2
              + 0.45 x min(contacts, 4) + 0.8 x trial_started
Converted leads' (contacts, trial) are drawn from the prior *conditional on converting* and lost leads' conditional on not
converting (rejection sampling), so the funnel behaviour is consistent with the rule. Lead volume is sized from
`prospect_conversion_rate`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import ids  # noqa: F401  (kept for symmetry with other generators)
from ..config import Config
from .master import REGIONS, SEGMENTS
from .simulate import sigmoid

CHANNELS = ["ORGANIC", "PAID", "REFERRAL", "PARTNER"]
CH_EFFECT = np.array([0.2, -0.35, 0.9, -0.1])
LEAD_MIX = [0.30, 0.35, 0.15, 0.20]
LAG_MEAN_DAYS = np.array([14.0, 21.0, 7.0, 35.0])        # lead -> conversion
LOST_REASONS = ["PRICE", "COMPETITOR", "NOT_A_FIT", "NO_RESPONSE"]
EVENT_RANK = {"CREATED": 0, "CONTACTED": 1, "TRIAL_STARTED": 2, "CONVERTED": 3, "LOST": 3}


def conversion_probability(ch, seg, n_contacts, trial):
    z = -1.9 + CH_EFFECT[ch] + np.where(seg == 1, -0.2, 0.0) + 0.45 * np.minimum(n_contacts, 4) + 0.8 * trial
    return sigmoid(z)


def _funnel_behaviour(r, ch, seg, converts: bool, tries: int = 40):
    m = len(ch)
    n = np.minimum(r.poisson(1.3, (m, tries)), 5)
    trial = (r.random((m, tries)) < 0.35).astype(int)
    p = conversion_probability(ch[:, None], seg[:, None], n, trial)
    ok = r.random((m, tries)) < (p if converts else 1 - p)
    first = np.where(ok.any(1), ok.argmax(1), tries - 1)
    rows = np.arange(m)
    return n[rows, first], trial[rows, first]


def _day(d) -> int:
    return int(np.datetime64(d, "D").astype("int64"))


def build_prospects(cfg: Config, P, streams):
    r = streams.get("prospects")
    ws, data_end = _day(cfg.window_start), _day(cfg.data_end)
    conv = np.nonzero(P.is_new)[0]
    nc = len(conv)

    # ---- converted leads (one per customer acquired inside the window) ----------------------------------
    ch_c, seg_c = P.chan[conv], P.seg[conv]
    n_c, trial_c = _funnel_behaviour(r, ch_c, seg_c, True)
    lag_c = np.clip(1 + np.round(r.gamma(2.0, LAG_MEAN_DAYS[ch_c] / 2)), 1, 120).astype(int)
    end_c = P.start[conv].astype("datetime64[D]").astype("int64")
    created_c = end_c - lag_c

    # ---- leads that did not (yet) convert ------------------------------------------------------------------
    nl = int(round(nc * (1 - cfg.prospect_conversion_rate) / cfg.prospect_conversion_rate))
    ch_l = r.choice(4, nl, p=LEAD_MIX)
    seg_l = (r.random(nl) < 0.20).astype(int)
    reg_l = r.choice(4, nl, p=[0.30, 0.25, 0.25, 0.20])
    cons_l = r.random(nl) < 0.80
    n_l, trial_l = _funnel_behaviour(r, ch_l, seg_l, False)
    created_l = ws - 90 + r.integers(0, (data_end - ws) + 90, nl)
    lag_l = np.clip(1 + np.round(r.gamma(2.0, 20.0, nl)), 1, 120).astype(int)
    end_l = created_l + lag_l

    created = np.concatenate([created_c, created_l])
    end = np.concatenate([end_c, end_l])
    lag = np.concatenate([lag_c, lag_l])
    n_contacts = np.concatenate([n_c, n_l])
    trial = np.concatenate([trial_c, trial_l])
    ch = np.concatenate([ch_c, ch_l])
    seg = np.concatenate([seg_c, seg_l])
    region = np.concatenate([P.region[conv], reg_l])
    consent = np.concatenate([P.consent[conv], cons_l])
    cust = np.concatenate([P.cust_ids[conv], np.full(nl, None, dtype=object)])
    converted = np.concatenate([np.ones(nc, bool), np.zeros(nl, bool)])
    owner = 301 + r.integers(0, 10, len(created))

    # numbering by creation date (stable on source order)
    order = np.lexsort((np.arange(len(created)), created))
    pid = np.empty(len(created), dtype=object)
    pid[order] = [f"PRS-{k:06d}" for k in range(1, len(created) + 1)]

    ev_rows = []
    for k in range(len(created)):
        c0, e0 = int(created[k]), int(end[k])
        ev_rows.append((pid[k], c0, 0, "CREATED", None, None))
        for off in np.sort(r.integers(0, lag[k] + 1, n_contacts[k])):
            if c0 + off <= data_end:
                ev_rows.append((pid[k], c0 + int(off), 1, "CONTACTED", None, None))
        if trial[k]:
            d = c0 + int(r.integers(0, lag[k] + 1))
            if d <= data_end:
                ev_rows.append((pid[k], d, 2, "TRIAL_STARTED", None, None))
        if converted[k]:
            ev_rows.append((pid[k], e0, 3, "CONVERTED", None, cust[k]))
        elif e0 <= data_end:
            reason = "NO_RESPONSE" if n_contacts[k] == 0 else r.choice(LOST_REASONS, p=[0.35, 0.30, 0.15, 0.20])
            ev_rows.append((pid[k], e0, 3, "LOST", reason, None))
    ev = pd.DataFrame(ev_rows, columns=["prospect_id", "day", "rank", "event_type", "reason_code", "customer_id"])
    ev = ev.sort_values(["prospect_id", "day", "rank"], kind="stable").reset_index(drop=True)
    ev["event_seq"] = ev.groupby("prospect_id").cumcount() + 1
    ev["prospect_event_id"] = [f"PEV-{p}-{n:02d}" for p, n in zip(ev["prospect_id"], ev["event_seq"])]
    ev["event_date"] = ev["day"].to_numpy().astype("datetime64[D]")

    # ---- prospects table: status and closing fields derived from the terminal event -----------------------
    term = ev[ev["event_type"].isin(["CONVERTED", "LOST"])].set_index("prospect_id")
    base = pd.DataFrame({
        "prospect_id": pid, "created_date": created.astype("datetime64[D]"), "source_channel": np.array(CHANNELS, dtype=object)[ch],
        "segment": np.array(SEGMENTS, dtype=object)[seg], "region": np.array(REGIONS, dtype=object)[region],
        "marketing_consent": consent.astype(int), "owner_id": [f"USR-{o}" for o in owner]})
    base["status"] = term["event_type"].reindex(base["prospect_id"]).fillna("OPEN").to_numpy()
    base["closed_date"] = term["event_date"].reindex(base["prospect_id"]).to_numpy()
    base["converted_customer_id"] = term["customer_id"].reindex(base["prospect_id"]).to_numpy()
    base["lost_reason"] = term["reason_code"].reindex(base["prospect_id"]).to_numpy()
    return base, ev
