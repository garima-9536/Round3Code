"""Evaluation: temporal churn model, randomised offer test (incremental lift vs correlation), cost/ROI, uplift targeting.

The generator's ground truth (true effects) is read only at the end to *score the estimators*; it is never a feature.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ..validate.checks import load_tables
from .features import build_features, build_labels, encode

warnings.filterwarnings("ignore")
VALUE_MONTHS = 6          # assumed value of a retained customer = 6 months of margin (documented assumption)
N_BOOT = 300


# ------------------------------------------------------------------------------------------------------------
def rank_metrics(y, score, name):
    y = np.asarray(y)
    order = np.argsort(-score, kind="stable")
    ys = y[order]
    n = len(y)
    base = y.mean()
    out = {"model": name, "roc_auc": float(roc_auc_score(y, score)), "pr_auc": float(average_precision_score(y, score)), "base_rate": float(base)}
    for q in (0.05, 0.10, 0.20):
        k = max(1, int(round(q * n)))
        out[f"precision_at_top_{int(q*100)}pct"] = float(ys[:k].mean())
        out[f"lift_at_top_{int(q*100)}pct"] = float(ys[:k].mean() / base) if base > 0 else None
        out[f"recall_at_top_{int(q*100)}pct"] = float(ys[:k].sum() / max(y.sum(), 1))
    return out


def decile_table(y, p):
    d = pd.DataFrame({"y": y, "p": p})
    d["decile"] = pd.qcut(d["p"].rank(method="first", ascending=False), 10, labels=range(1, 11))
    t = d.groupby("decile", observed=True).agg(customers=("y", "size"), churn_rate=("y", "mean"), mean_score=("p", "mean")).reset_index()
    return t.round(4).to_dict("records")


def churn_model_eval(tb, cfg):
    pred = pd.Timestamp(cfg["prediction_date"])
    hm = int(cfg["horizon_months"])
    train_cutoffs = [pd.Timestamp(x) for x in ("2025-10-01", "2026-01-01", "2026-04-01")]
    assert all(c + pd.DateOffset(months=hm) <= pred for c in train_cutoffs), "training label windows must end before the test cutoff"
    frames, guards = [], {}
    for c in train_cutoffs:
        X, g = build_features(tb, c)
        y = build_labels(tb, c, hm)["churn"].reindex(X.index)
        X["_cutoff"] = c
        frames.append((X, y))
        guards[str(c.date())] = g
    Xtr = pd.concat([f[0] for f in frames])
    ytr = pd.concat([f[1] for f in frames]).to_numpy()
    Xte, gte = build_features(tb, pred)
    guards[str(pred.date())] = gte
    lab = build_labels(tb, pred, hm)
    yte = lab["churn"].reindex(Xte.index).to_numpy()

    co = tb["churn_outcomes"].set_index("customer_id")
    ok = co[co["churn_event_date"].isna() | (co["churn_event_date"] >= pred)]
    common = ok.index.intersection(Xte.index)
    agree = float((ok.loc[common, "churned_in_horizon"].to_numpy() == lab.loc[common, "churn"].to_numpy()).mean())

    A = encode(Xtr.drop(columns="_cutoff"))
    B = encode(Xte).reindex(columns=A.columns, fill_value=0.0)
    results = []
    heur = -np.nan_to_num(B["usage_ratio_3m_vs_prev3m"].to_numpy(), nan=1.0)
    results.append(rank_metrics(yte, heur, "heuristic: usage drop (3m vs prior 3m)"))
    lr = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(max_iter=500, C=0.5))
    lr.fit(A, ytr)
    p_lr = lr.predict_proba(B)[:, 1]
    results.append(rank_metrics(yte, p_lr, "logistic regression"))
    gb = HistGradientBoostingClassifier(max_depth=4, learning_rate=0.06, max_iter=250, l2_regularization=1.0, random_state=int(cfg["seed"] % 2**31))
    gb.fit(A, ytr)
    p_gb = gb.predict_proba(B)[:, 1]
    results.append(rank_metrics(yte, p_gb, "gradient boosting"))
    return {
        "design": "temporal: train on cutoffs 2025-10-01, 2026-01-01, 2026-04-01 (label windows end <= test cutoff); test at the prediction date",
        "churn_definition": "primary subscription ends (cancelled or terminated for non-payment) in [cutoff, cutoff+3 calendar months)",
        "train_rows": int(len(ytr)), "train_positive_rate": float(ytr.mean()), "test_rows": int(len(yte)), "test_positive_rate": float(yte.mean()),
        "mean_predicted_test_gb": float(p_gb.mean()),
        "note": "base rate shifts upward in the test window (churn wave), so ranking metrics (AUC, lift) are the fair comparison; calibration is not.",
        "label_agreement_with_ChurnOutcome_table": agree,
        "leakage_guard_latest_feature_timestamp": guards,
        "models": results, "gb_test_decile_table": decile_table(yte, p_gb),
    }, p_gb, Xte.index, gb, A.columns


# ------------------------------------------------------------------------------------------------------------
def diff_ci(yt, yc):
    pt, pc = yt.mean(), yc.mean()
    se = np.sqrt(pt * (1 - pt) / len(yt) + pc * (1 - pc) / len(yc))
    d = pc - pt                                   # churn reduction (positive = offer helps)
    p = 2 * (1 - norm.cdf(abs(d) / se)) if se > 0 else None
    return {"churn_treated": float(pt), "churn_control": float(pc), "n_treated": int(len(yt)), "n_control": int(len(yc)),
            "churn_reduction_abs": float(d), "ci95": [float(d - 1.96 * se), float(d + 1.96 * se)], "p_value": None if p is None else float(p),
            "relative_reduction": float(d / pc) if pc > 0 else None}


def stratified(d, strat_col, treat_mask):
    """post-stratified difference in churn rates (control - treated)."""
    est, var, w_tot = 0.0, 0.0, 0
    for _, g in d.groupby(strat_col):
        t, c = g[treat_mask.loc[g.index]], g[~treat_mask.loc[g.index]]
        if len(t) < 1 or len(c) < 1:
            continue
        w = len(g)
        pt, pc = t["y"].mean(), c["y"].mean()
        est += w * (pc - pt)
        var += w ** 2 * (pt * (1 - pt) / len(t) + pc * (1 - pc) / len(c))
        w_tot += w
    se = np.sqrt(var) / w_tot
    return float(est / w_tot), float(se)


def offer_eval(tb, cfg, out):
    vio = pd.read_csv(out / "validation" / "violations.csv") if (out / "validation" / "violations.csv").exists() else pd.DataFrame(columns=["severity", "customer_id"])
    excluded = set(vio.loc[vio["severity"] == "RULE", "customer_id"].dropna())
    cc = tb["campaign_contacts"]
    cc = cc[(cc["contact_source"] == "AUTO_ELIGIBLE") & ~cc["customer_id"].isin(excluded)]
    assert cc["customer_id"].is_unique, "evaluation population must have one contact per customer"
    r = tb["retention_outcomes"].set_index("contact_id")
    co = tb["churn_outcomes"].set_index("customer_id")
    ev = tb["eligibility_evaluations"]
    d = cc.set_index("customer_id")[["contact_id", "randomization_group", "offer_id", "randomization_stratum", "campaign_id"]].copy()
    d["y"] = co["churned_in_horizon"].reindex(d.index).astype(int)
    d["treated"] = d["randomization_group"] == "TREATMENT"
    d["accepted"] = r["offer_accepted"].reindex(d["contact_id"]).to_numpy().astype(int)
    d["viewed"] = r["offer_viewed"].reindex(d["contact_id"]).to_numpy().astype(int)
    d["offer_cost"] = r["offer_cost"].reindex(d["contact_id"]).to_numpy()
    d["net_margin"] = r["net_margin_horizon"].reindex(d["contact_id"]).to_numpy()
    sets = ev[ev["decision"] == "ELIGIBLE"].groupby("customer_id")["offer_id"].apply(lambda s: "|".join(sorted(s)))
    d["eligible_set"] = sets.reindex(d.index).fillna("")
    margin = ev.drop_duplicates("customer_id").set_index("customer_id")["monthly_margin"]
    d["monthly_margin"] = margin.reindex(d.index).to_numpy()
    t, c = d[d["treated"]], d[~d["treated"]]

    res = {"population": {"customers": int(len(d)), "treated": int(len(t)), "control": int(len(c)),
                          "excluded_customers_flagged_by_validation": int(len(excluded)),
                          "acceptance_rate_treated": float(t["accepted"].mean()), "viewed_rate_treated": float(t["viewed"].mean())}}
    itt = diff_ci(t["y"].to_numpy(), c["y"].to_numpy())
    est, se = stratified(d, "randomization_stratum", d["treated"])
    itt["stratified_estimate"] = est
    itt["stratified_ci95"] = [est - 1.96 * se, est + 1.96 * se]
    res["incremental_lift_ITT"] = itt
    if d["campaign_id"].nunique() > 1:
        res["by_campaign"] = {c: {"customers": int(len(g)), **diff_ci(g.loc[g["treated"], "y"].to_numpy(), g.loc[~g["treated"], "y"].to_numpy())}
                              for c, g in d.groupby("campaign_id")}

    acc, non = t[t["accepted"] == 1], t[t["accepted"] == 0]
    res["naive_correlational_estimates"] = {
        "accepters_vs_non_accepters_churn_reduction": float(non["y"].mean() - acc["y"].mean()),
        "accepters_vs_control_churn_reduction": float(c["y"].mean() - acc["y"].mean()),
        "churn_rate_accepters": float(acc["y"].mean()), "churn_rate_non_accepters": float(non["y"].mean()), "churn_rate_control": float(c["y"].mean()),
        "explanation": "Customers who accept offers differ systematically (selection into acceptance); comparing them with non-accepters or "
                       "controls is correlation. Only the randomised ITT (and CACE via randomisation as an instrument) is incremental lift.",
    }
    rng = np.random.default_rng(int(cfg["seed"]) % 2**31)
    comp = float(t["accepted"].mean())
    boots = []
    yt, yc, at = t["y"].to_numpy(), c["y"].to_numpy(), t["accepted"].to_numpy()
    for _ in range(N_BOOT):
        it, ic = rng.integers(0, len(yt), len(yt)), rng.integers(0, len(yc), len(yc))
        boots.append((yc[ic].mean() - yt[it].mean()) / max(at[it].mean(), 1e-9))
    cace = (c["y"].mean() - t["y"].mean()) / comp
    res["effect_on_accepters_CACE"] = {"estimate": float(cace), "ci95_bootstrap": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
                                       "definition": "ITT / acceptance rate; effect among customers who accept when offered (control cannot access offers)"}

    per_offer = {}
    for oid in sorted(t["offer_id"].dropna().unique()):
        sub = d[(d["eligible_set"].str.contains(oid)) & ((d["offer_id"] == oid) | ~d["treated"])]
        tr = sub["treated"]
        e, s = stratified(sub, "eligible_set", tr)
        tt, cc_ = sub[tr], sub[~tr]
        cost = float(tt["offer_cost"].sum())
        inc = e * len(tt)
        per_offer[oid] = {"n_treated": int(len(tt)), "n_control_eligible": int(len(cc_)), "acceptance_rate": float(tt["accepted"].mean()),
                          "churn_reduction_abs": e, "ci95": [e - 1.96 * s, e + 1.96 * s], "total_cost": cost,
                          "incremental_retained": float(inc), "cost_per_incremental_retained": float(cost / inc) if inc > 0 else None}
    res["per_offer"] = per_offer
    byplan = {}
    for plan, g in d.groupby(d["randomization_stratum"].str.split("|").str[0]):
        if g["treated"].sum() > 20 and (~g["treated"]).sum() > 20:
            byplan[plan] = diff_ci(g.loc[g["treated"], "y"].to_numpy(), g.loc[~g["treated"], "y"].to_numpy())
    res["by_plan"] = byplan

    # ---- cost and value ---------------------------------------------------------------------------------
    total_cost = float(t["offer_cost"].sum())
    inc_retained = itt["churn_reduction_abs"] * len(t)
    mean_margin = float(t["monthly_margin"].mean())
    value = inc_retained * mean_margin * VALUE_MONTHS
    nm = diff_ci_means(t["net_margin"].to_numpy(), c["net_margin"].to_numpy())
    res["cost_and_value"] = {
        "total_offer_cost": total_cost, "cost_per_treated": total_cost / len(t), "cost_per_acceptor": float(total_cost / max(t["accepted"].sum(), 1)),
        "incremental_retained_customers": float(inc_retained),
        "cost_per_incremental_retained": float(total_cost / inc_retained) if inc_retained > 0 else None,
        "assumption": f"retained customer worth {VALUE_MONTHS} months of margin at the treated group's mean monthly margin ({mean_margin:.2f})",
        "incremental_margin_value": float(value), "net_benefit": float(value - total_cost),
        "horizon_net_margin_per_customer_treated_minus_control": nm,
    }

    # ---- ground-truth scoring of the estimators (ONLY place the truth is read) -----------------------------
    truth_path = out / "ground_truth" / "true_effects.json"
    lat_path = out / "ground_truth" / "latent_truth.csv"
    if truth_path.exists() and lat_path.exists():
        lat = pd.read_csv(lat_path).set_index("customer_id")
        lt = lat.reindex(t.index.intersection(lat.index))
        true_itt = float(lt["true_individual_effect"].mean())
        accl = lt[lt["would_accept_offer"] == 1]
        true_cace = float(accl["true_individual_effect"].mean())
        # waste: accepters who would have stayed anyway got the discount for nothing
        la = lat.reindex(acc.index.intersection(lat.index))
        stay = la["churn_in_horizon_if_not_offered"] == 0
        waste_cost = float(acc.loc[la.index[stay], "offer_cost"].sum())
        lo, hi = res["incremental_lift_ITT"]["ci95"]
        res["scored_against_ground_truth"] = {
            "true_ITT_treated_arm": true_itt, "estimated_ITT": itt["churn_reduction_abs"], "ITT_ci_contains_truth": bool(lo <= true_itt <= hi),
            "true_effect_on_accepters": true_cace, "estimated_CACE": float(cace),
            "CACE_ci_contains_truth": bool(res["effect_on_accepters_CACE"]["ci95_bootstrap"][0] <= true_cace <= res["effect_on_accepters_CACE"]["ci95_bootstrap"][1]),
            "naive_accepter_vs_non_accepter_estimate": res["naive_correlational_estimates"]["accepters_vs_non_accepters_churn_reduction"],
            "naive_bias_vs_truth": float(res["naive_correlational_estimates"]["accepters_vs_non_accepters_churn_reduction"] - true_cace),
            "share_of_accepters_who_would_not_have_churned": float(stay.mean()),
            "offer_cost_spent_on_accepters_who_would_not_have_churned": waste_cost,
            "share_of_total_offer_cost_wasted": float(waste_cost / max(total_cost, 1e-9)),
            "per_offer_true_ITT": json.loads(truth_path.read_text())["per_offer_true_itt"],
        }
    return res, d


def diff_ci_means(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = a.mean() - b.mean()
    se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    return {"difference": float(d), "ci95": [float(d - 1.96 * se), float(d + 1.96 * se)]}


# ------------------------------------------------------------------------------------------------------------
def qini_table(y_churn, treated, score, margin_value, cost_per_treated):
    """cumulative incremental retained customers when targeting the top-q share by `score` (randomised holdout)."""
    d = pd.DataFrame({"ret": 1 - np.asarray(y_churn), "t": np.asarray(treated), "s": np.asarray(score)}).sort_values("s", ascending=False).reset_index(drop=True)
    n = len(d)
    rows = []
    for q in (0.1, 0.2, 0.3, 0.5, 0.7, 1.0):
        k = int(round(q * n))
        g = d.iloc[:k]
        t, c = g[g["t"] == 1], g[g["t"] == 0]
        if len(t) < 5 or len(c) < 5:
            continue
        lift = t["ret"].mean() - c["ret"].mean()
        se = np.sqrt(t["ret"].var() / len(t) + c["ret"].var() / len(c))
        inc = lift * k
        cost = cost_per_treated * k
        rows.append({"targeted_share": q, "n_targeted": k, "uplift_per_customer": float(lift), "se": float(se), "incremental_retained": float(inc),
                     "approx_cost": float(cost), "net_benefit": float(inc * margin_value - cost)})
    return rows


def uplift_eval(tb, cfg, d, p_risk_series):
    pred = pd.Timestamp(cfg["prediction_date"])
    X, _ = build_features(tb, pred)
    X = X.reindex(d.index)
    E = encode(X)
    rng = np.random.default_rng(int(cfg["seed"]) % 2**31 + 7)
    split = rng.random(len(d)) < 0.5
    tr, te = d[split], d[~split]
    Etr, Ete = E[split], E[~split]
    mk = lambda: HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=120, l2_regularization=2.0, random_state=1)
    mt, mc = mk(), mk()
    mt.fit(Etr[tr["treated"].to_numpy()], tr.loc[tr["treated"], "y"])
    mc.fit(Etr[~tr["treated"].to_numpy()], tr.loc[~tr["treated"], "y"])
    pt, pc = mt.predict_proba(Ete)[:, 1], mc.predict_proba(Ete)[:, 1]
    uplift = pc - pt
    risk = p_risk_series.reindex(te.index).fillna(0).to_numpy()
    t_cost = float(d.loc[d["treated"], "offer_cost"].mean())
    margin_value = float(d["monthly_margin"].mean() * VALUE_MONTHS)
    rnd = np.random.default_rng(3).random(len(te))
    out = {"design": "T-learner (separate churn models for treated/control) trained on a random 50% of the randomised campaign; "
                     "all numbers are estimated on the other 50% (valid because assignment was randomised)",
           "holdout_customers": int(len(te)), "cost_per_treated_assumed": t_cost, "value_per_retained_customer": margin_value,
           "policies": {
               "by_uplift_score": qini_table(te["y"], te["treated"], uplift, margin_value, t_cost),
               "by_churn_risk_score": qini_table(te["y"], te["treated"], risk, margin_value, t_cost),
               "random": qini_table(te["y"], te["treated"], rnd, margin_value, t_cost)},
           "note": "holdout controls are few, so per-bucket estimates are noisy (see se); compare policies on the same targeted shares."}
    return out


# ------------------------------------------------------------------------------------------------------------
def run_evaluation(out_dir) -> dict:
    out = Path(out_dir)
    cfg = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["config"]
    tb = load_tables(out / "data")
    churn, p_gb, idx, gb, cols = churn_model_eval(tb, cfg)
    p_risk = pd.Series(p_gb, index=idx)
    offer, d = offer_eval(tb, cfg, out)
    uplift = uplift_eval(tb, cfg, d, p_risk)
    report = {"dataset": str(out), "prediction_date": cfg["prediction_date"], "horizon_months": cfg["horizon_months"],
              "churn_prediction": churn, "offer_experiment": offer, "uplift_targeting": uplift}
    edir = out / "evaluation"
    edir.mkdir(exist_ok=True)
    (edir / "evaluation_report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    (edir / "evaluation_report.md").write_text(report_md(report), encoding="utf-8")
    return report


def pct(x, d=2):
    return "n/a" if x is None else f"{100 * x:.{d}f}%"


def report_md(r) -> str:
    cp, oe, up = r["churn_prediction"], r["offer_experiment"], r["uplift_targeting"]
    L = ["# Evaluation report", "", f"Prediction date **{r['prediction_date']}**, horizon **{r['horizon_months']} months**. "
         "Features use only records dated before the prediction date; evaluation is temporal.", "",
         "## 1. Churn prediction (temporal)", "", cp["design"], "", f"- churn definition: {cp['churn_definition']}",
         f"- train rows {cp['train_rows']:,} (positive {pct(cp['train_positive_rate'])}), test rows {cp['test_rows']:,} (positive {pct(cp['test_positive_rate'])})",
         f"- {cp['note']}", f"- label agreement with ChurnOutcome table: {cp['label_agreement_with_ChurnOutcome_table']:.4f}",
         f"- leakage guard (latest timestamp used per table, must be < cutoff): `{json.dumps(cp['leakage_guard_latest_feature_timestamp'][r['prediction_date']])}`", "",
         "| model | ROC-AUC | PR-AUC | lift@top10% | precision@top10% | recall@top20% |", "|---|---|---|---|---|---|"]
    for m in cp["models"]:
        L.append(f"| {m['model']} | {m['roc_auc']:.3f} | {m['pr_auc']:.3f} | {m['lift_at_top_10pct']:.2f}x | {pct(m['precision_at_top_10pct'])} | {pct(m['recall_at_top_20pct'])} |")
    L += ["", "Gradient boosting - test churn rate by predicted-risk decile (1 = highest risk):", "", "| decile | customers | actual churn | mean score |", "|---|---|---|---|"]
    for row in cp["gb_test_decile_table"]:
        L.append(f"| {row['decile']} | {row['customers']} | {pct(row['churn_rate'])} | {pct(row['mean_score'])} |")
    p = oe["population"]
    i = oe["incremental_lift_ITT"]
    L += ["", "## 2. Randomised offer test - incremental lift vs correlation", "",
          f"Campaign population (after excluding {p['excluded_customers_flagged_by_validation']} customers flagged by validation): "
          f"{p['customers']:,} customers; treatment {p['treated']:,}, control {p['control']:,}; offers viewed by {pct(p['viewed_rate_treated'])}, accepted by {pct(p['acceptance_rate_treated'])} of treated.", "",
          f"- churn in horizon: control **{pct(i['churn_control'])}**, treatment **{pct(i['churn_treated'])}**",
          f"- **incremental lift (ITT)**: churn reduced by **{pct(i['churn_reduction_abs'])}** points (95% CI {pct(i['ci95'][0])} to {pct(i['ci95'][1])}, p={i['p_value']:.4f}); "
          f"relative reduction {pct(i['relative_reduction'], 1)}; stratified estimate {pct(i['stratified_estimate'])}",
          f"- effect among accepters (CACE): {pct(oe['effect_on_accepters_CACE']['estimate'])} (95% CI {pct(oe['effect_on_accepters_CACE']['ci95_bootstrap'][0])} to {pct(oe['effect_on_accepters_CACE']['ci95_bootstrap'][1])})", "",
          "**Correlation, not causation:**", "",
          f"- accepters churned {pct(oe['naive_correlational_estimates']['churn_rate_accepters'])} vs non-accepters {pct(oe['naive_correlational_estimates']['churn_rate_non_accepters'])} "
          f"vs control {pct(oe['naive_correlational_estimates']['churn_rate_control'])}",
          f"- naive 'accepters vs non-accepters' effect: {pct(oe['naive_correlational_estimates']['accepters_vs_non_accepters_churn_reduction'])} "
          f"(sign/size distorted by selection into acceptance)", "", "Per offer (post-stratified by eligible offer set):", "",
          "| offer | treated | acceptance | churn reduction | 95% CI | cost | incr. retained | cost / incr. retained |", "|---|---|---|---|---|---|---|---|"]
    for k, v in oe["per_offer"].items():
        cpi = "n/a" if v["cost_per_incremental_retained"] is None else f"{v['cost_per_incremental_retained']:.2f}"
        L.append(f"| {k} | {v['n_treated']} | {pct(v['acceptance_rate'])} | {pct(v['churn_reduction_abs'])} | {pct(v['ci95'][0])} to {pct(v['ci95'][1])} | {v['total_cost']:.2f} | {v['incremental_retained']:.1f} | {cpi} |")
    cv = oe["cost_and_value"]
    L += ["", "### Cost and value", "", f"- total offer cost {cv['total_offer_cost']:.2f}; per treated {cv['cost_per_treated']:.2f}; per acceptor {cv['cost_per_acceptor']:.2f}",
          f"- incremental retained customers (ITT x treated): {cv['incremental_retained_customers']:.1f}; cost per incremental retained: "
          f"{'n/a' if cv['cost_per_incremental_retained'] is None else format(cv['cost_per_incremental_retained'], '.2f')}",
          f"- assumption: {cv['assumption']}", f"- incremental margin value {cv['incremental_margin_value']:.2f}; **net benefit {cv['net_benefit']:.2f}**",
          f"- horizon net margin per customer, treated minus control (already net of offer credits): {cv['horizon_net_margin_per_customer_treated_minus_control']['difference']:.3f} "
          f"(95% CI {cv['horizon_net_margin_per_customer_treated_minus_control']['ci95'][0]:.3f} to {cv['horizon_net_margin_per_customer_treated_minus_control']['ci95'][1]:.3f})"]
    if "scored_against_ground_truth" in oe:
        g = oe["scored_against_ground_truth"]
        L += ["", "### Estimators scored against the simulator's ground truth", "",
              f"- true ITT {pct(g['true_ITT_treated_arm'])} vs estimated {pct(g['estimated_ITT'])} (CI contains truth: {g['ITT_ci_contains_truth']})",
              f"- true effect on accepters {pct(g['true_effect_on_accepters'])} vs CACE {pct(g['estimated_CACE'])} (CI contains truth: {g['CACE_ci_contains_truth']})",
              f"- naive accepters-vs-non-accepters estimate {pct(g['naive_accepter_vs_non_accepter_estimate'])}: bias vs truth {pct(g['naive_bias_vs_truth'])}",
              f"- {pct(g['share_of_accepters_who_would_not_have_churned'], 1)} of accepters would not have churned anyway; "
              f"{g['offer_cost_spent_on_accepters_who_would_not_have_churned']:.2f} ({pct(g['share_of_total_offer_cost_wasted'], 1)}) of offer cost subsidised them"]
    L += ["", "## 3. Targeting policy (uplift vs risk vs random)", "", up["design"], "",
          f"Holdout customers {up['holdout_customers']:,}; assumed cost per treated {up['cost_per_treated_assumed']:.2f}; value per retained {up['value_per_retained_customer']:.2f}.", ""]
    for name, rows in up["policies"].items():
        L += [f"**{name}**", "", "| targeted share | uplift/customer | se | incr. retained | approx cost | net benefit |", "|---|---|---|---|---|---|"]
        for r_ in rows:
            L.append(f"| {r_['targeted_share']:.0%} | {pct(r_['uplift_per_customer'])} | {pct(r_['se'])} | {r_['incremental_retained']:.1f} | {r_['approx_cost']:.0f} | {r_['net_benefit']:.0f} |")
        L.append("")
    L.append(up["note"])
    return "\n".join(L) + "\n"
