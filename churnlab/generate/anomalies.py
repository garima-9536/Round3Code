"""Step 5: inject *labelled* edge cases after the valid baseline exists.

Each anomaly touches only its own (new or clearly identified) rows and is recorded in ground truth with
an issue_type, so no unrelated rows are silently corrupted.
  CHURN_LABEL_BEFORE_PREDICTION  churn label whose event date precedes the prediction date
  INELIGIBLE_OFFER_SENT          manual override contact for a customer failing eligibility (injected inside the campaign run)
  TREATMENT_CONTROL_LEAKAGE      a control customer also receives a treatment contact
  MULTI_OFFER_ATTRIBUTION        a retained customer attributed to a second offer
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from .. import ids
from ..config import Config
from ..schema import GROUND_TRUTH_COLUMNS, ISSUE_TYPES
from .derive import churn_row_frame


def inject(cfg: Config, camp, contacts, evals, retention, subs, ev, streams) -> SimpleNamespace:
    r = streams.get("anomalies")
    K = camp.n_anom
    gt = []

    def add_gt(issue, table, entity_id, customer_id, related=None, rules=None, desc=""):
        check, decision = ISSUE_TYPES[issue]
        gt.append((None, issue, table, entity_id, customer_id, related, rules, desc, decision, check))

    elig_map = (evals[evals["decision"] == "ELIGIBLE"].groupby("customer_id")["offer_id"].apply(list).to_dict())
    ev_id = {(a, b): c for a, b, c in zip(evals["customer_id"], evals["offer_id"], evals["evaluation_id"])}
    offers_all = sorted(evals["offer_id"].unique())

    # 1) ineligible offers (already part of the baseline contacts as manual overrides)
    ov = contacts[contacts["contact_source"] == "MANUAL_OVERRIDE"]
    fr = {(a, b): c for a, b, c in zip(evals["customer_id"], evals["offer_id"], evals["failed_rules"])}
    for cid, cust, off in zip(ov["contact_id"], ov["customer_id"], ov["offer_id"]):
        add_gt("INELIGIBLE_OFFER_SENT", "campaign_contacts", cid, cust, rules=fr.get((cust, off)),
               desc="Offer sent via MANUAL_OVERRIDE to a customer that fails eligibility; no documented override reason")

    used = set(ov["customer_id"])
    ctrl = contacts[contacts["randomization_group"] == "CONTROL"]
    ctrl_c = sorted(c for c in ctrl["customer_id"] if c not in used and c in elig_map)
    leak = list(r.choice(ctrl_c, size=min(K, len(ctrl_c)), replace=False)) if ctrl_c else []
    used |= set(leak)

    ret_attr = retention[(retention["retention_attributed"] == 1)]
    multi_pool = sorted(c for c in ret_attr["customer_id"] if c not in used and len(elig_map.get(c, [])) >= 2)
    multi = list(r.choice(multi_pool, size=min(K, len(multi_pool)), replace=False)) if multi_pool else []
    used |= set(multi)

    base_by_cust = contacts.set_index("customer_id")
    new_rows, new_obs = [], []
    n = len(contacts)
    ch_names = ["EMAIL", "SMS", "IN_APP"]

    def second_contact(cust, offer, issue, related_cid, desc, viewed):
        nonlocal n
        n += 1
        b = base_by_cust.loc[cust]
        cid = ids.contact(n)
        new_rows.append((cid, b["campaign_id"], cust, b["subscription_id"], offer, "TREATMENT", b["randomization_stratum"],
                         cfg.prediction_date, ch_names[int(r.integers(0, 3))], "DELIVERED", "AUTO_ELIGIBLE", "SYSTEM",
                         ev_id[(cust, offer)], None))
        new_obs.append((cid, viewed, 0, None))
        add_gt(issue, "campaign_contacts", cid, cust, related=related_cid, desc=desc)
        return cid

    for cust in leak:
        offer = r.choice(elig_map[cust])
        second_contact(cust, offer, "TREATMENT_CONTROL_LEAKAGE", base_by_cust.loc[cust, "contact_id"],
                       "Customer randomised to CONTROL also received a TREATMENT contact", 1)
    multi_cids = []
    for cust in multi:
        first = base_by_cust.loc[cust, "offer_id"]
        offer = r.choice([o for o in elig_map[cust] if o != first])
        multi_cids.append(second_contact(cust, offer, "MULTI_OFFER_ATTRIBUTION", base_by_cust.loc[cust, "contact_id"],
                                         "Retained customer is also attributed to a second offer", 0))

    # 4) churn label precedes prediction date: historic churners wrongly scored in the label table
    prim = subs[subs["is_primary"] == 1]
    end = pd.to_datetime(prim["end_date"])
    hist = sorted(prim.loc[end < pd.Timestamp(cfg.prediction_date), "customer_id"])
    pick = list(r.choice(hist, size=min(K, len(hist)), replace=False)) if hist else []
    extra_churn = churn_row_frame(cfg, subs, ev, pick) if pick else pd.DataFrame()
    if len(extra_churn):
        extra_churn["churned_in_horizon"] = 1  # the leaked/mis-dated label
        for cid, cust in zip(extra_churn["churn_outcome_id"], extra_churn["customer_id"]):
            add_gt("CHURN_LABEL_BEFORE_PREDICTION", "churn_outcomes", cid, cust,
                   desc="Churn label dated before the prediction date (customer already churned; label leaks the past)")

    gtdf = pd.DataFrame(gt, columns=GROUND_TRUTH_COLUMNS)
    gtdf = gtdf.sort_values(["issue_type", "entity_id"]).reset_index(drop=True)
    gtdf["anomaly_id"] = [f"ANOM-{i:04d}" for i in range(1, len(gtdf) + 1)]
    new_contacts = pd.DataFrame(new_rows, columns=contacts.columns)
    new_obs_df = pd.DataFrame(new_obs, columns=["contact_id", "viewed", "accepted", "accepted_at"])
    return SimpleNamespace(ground_truth=gtdf, new_contacts=new_contacts, new_obs=new_obs_df, multi_contact_ids=multi_cids,
                           extra_churn=extra_churn)
