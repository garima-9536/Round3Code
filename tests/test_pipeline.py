"""End-to-end tests on a small dataset (same generator as the full 20,000-customer run)."""
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from churnlab.config import Config
from churnlab.evaluate.features import build_features
from churnlab.export import export
from churnlab.generate.pipeline import generate
from churnlab.validate.checks import load_tables, run_validation

N = 900


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    cfg = Config(n_customers=N)
    g = generate(cfg)
    out = tmp_path_factory.mktemp("ds")
    export(g, out, "pytest", sql=True)
    return g, out


def test_generation_is_deterministic():
    a, b = generate(Config(n_customers=300)), generate(Config(n_customers=300))
    for k in a.tables:
        assert a.tables[k].equals(b.tables[k]), k
    assert a.ground_truth.equals(b.ground_truth)


def test_different_seed_differs():
    a, b = generate(Config(n_customers=300)), generate(Config(n_customers=300, seed=1))
    assert not a.tables["usage_snapshots"].equals(b.tables["usage_snapshots"])


def test_validation_passes_and_detects_every_injected_anomaly(built):
    _, out = built
    s = run_validation(out)
    assert s["total_error_violations"] == 0
    rec = s["ground_truth_reconciliation"]
    assert rec["unexplained_rule_violations"] == 0
    for issue, v in rec["per_issue_type"].items():
        assert v["injected"] > 0 and v["recall"] == 1.0, issue
    assert s["passed"]


def test_ids_follow_conventions(built):
    g, _ = built
    t = g.tables
    assert t["customers"]["customer_id"].iloc[0] == "CUS-000001"
    assert t["subscriptions"]["subscription_id"].iloc[0] == "SUB-CUS-000001-01"
    assert t["usage_snapshots"]["snapshot_id"].str.match(r"^SNAP-SUB-CUS-\d{6}-\d{2}-\d{4}-\d{2}$").all()
    assert t["offers"]["offer_id"].tolist()[0] == "OFF-2026-000001"
    assert t["churn_outcomes"]["churn_outcome_id"].str.match(r"^CHURN-CUS-\d{6}-2026$").all()


def test_churn_rate_in_documented_band(built):
    g, _ = built
    p = g.tables["subscriptions"].query("is_primary == 1")
    assert 0.05 <= (p["status"] != "ACTIVE").mean() <= 0.20
    ev = g.tables["subscription_events"]["event_type"]
    assert {"CANCELLED", "TERMINATED_NONPAYMENT", "PLAN_UPGRADE", "PLAN_DOWNGRADE"} <= set(ev)


def test_ground_truth_is_separate_from_inputs(built):
    g, out = built
    leaked = {"seasonal_user", "latent_risk", "true_individual_effect", "would_accept_offer", "price_sensitivity", "issue_type", "backlash_trait"}
    for name, df in g.tables.items():
        assert not (leaked & set(df.columns)), name
    assert (out / "ground_truth" / "ground_truth.csv").exists()
    assert not any("ground_truth" in str(p) for p in (out / "data").iterdir())


def test_features_use_only_data_before_prediction_date(built):
    _, out = built
    tb = load_tables(out / "data")
    cutoff = pd.Timestamp("2026-07-01")
    full, guard = build_features(tb, cutoff)
    assert all(pd.Timestamp(v) < cutoff for v in guard.values() if v)

    # drop every record dated on/after the cutoff: features must not change
    t2 = {k: v.copy() for k, v in tb.items()}
    t2["subscription_events"] = tb["subscription_events"].query("event_date < @cutoff")
    t2["billing_events"] = tb["billing_events"].query("event_date < @cutoff")
    t2["usage_snapshots"] = tb["usage_snapshots"].query("snapshot_month < @cutoff")
    cases = tb["support_cases"].query("opened_at < @cutoff").copy()
    for c in ("first_response_at", "escalated_at", "resolved_at"):
        cases.loc[cases[c] >= cutoff, c] = pd.NaT
    t2["support_cases"] = cases
    subs = tb["subscriptions"].copy()
    subs.loc[subs["end_date"] >= cutoff, "end_date"] = pd.NaT
    t2["subscriptions"] = subs
    trunc, _ = build_features(t2, cutoff)
    pd.testing.assert_frame_equal(full.sort_index(), trunc.sort_index(), check_dtype=False)


def _corrupt_and_validate(out, tmp_path, mutate):
    d = tmp_path / "bad"
    shutil.copytree(out, d)
    mutate(d / "data")
    return run_validation(d, check_sql_load=False)


def test_validator_flags_structural_corruption(built, tmp_path):
    _, out = built

    def dup_pk(data):
        df = pd.read_csv(data / "customers.csv", dtype=str)
        df.loc[1, "customer_id"] = df.loc[0, "customer_id"]
        df.to_csv(data / "customers.csv", index=False)

    def break_fk(data):
        df = pd.read_csv(data / "billing_events.csv", dtype=str)
        df.loc[5, "subscription_id"] = "SUB-CUS-999999-01"
        df.to_csv(data / "billing_events.csv", index=False)

    def bad_amount(data):
        df = pd.read_csv(data / "billing_events.csv", dtype=str)
        i = df.index[df["event_type"] == "PAYMENT"][3]
        df.loc[i, "amount"] = "999.99"
        df.to_csv(data / "billing_events.csv", index=False)

    def bad_enum(data):
        df = pd.read_csv(data / "customers.csv", dtype=str)
        df.loc[3, "segment"] = "VIP"
        df.to_csv(data / "customers.csv", index=False)

    def date_order(data):
        df = pd.read_csv(data / "subscriptions.csv", dtype=str)
        i = df.index[df["end_date"].notna()][0]
        df.loc[i, "end_date"] = "2001-01-01"
        df.to_csv(data / "subscriptions.csv", index=False)

    for mutate, check in ((dup_pk, "S01"), (break_fk, "S02"), (bad_amount, "A02"), (bad_enum, "S03"), (date_order, "D01")):
        s = _corrupt_and_validate(out, tmp_path, mutate)
        assert not s["passed"], check
        assert s["checks"][check]["violations"] > 0, check
        shutil.rmtree(tmp_path / "bad")


def test_campaign_rules(built):
    g, _ = built
    cc, r = g.tables["campaign_contacts"], g.tables["retention_outcomes"]
    ctrl = cc[cc["randomization_group"] == "CONTROL"]
    assert ctrl["offer_id"].isna().all() and (ctrl["contact_status"] == "HOLDOUT").all()
    assert (cc["contact_date"] == "2026-07-01").all()
    assert len(cc) == len(r)
    share = (cc[cc["contact_source"] == "AUTO_ELIGIBLE"]["randomization_group"] == "TREATMENT").mean()
    assert 0.6 < share < 0.8


def test_admin_audit_log_covers_overrides_and_reference_data(built):
    g, out = built
    a, cc = g.tables["admin_audit_log"], g.tables["campaign_contacts"]
    assert {"SYSTEM_ADMIN", "MARKETING_OPS", "SALES_OPS"} <= set(a["actor_role"])
    overrides = set(cc.loc[cc["contact_source"] == "MANUAL_OVERRIDE", "contact_id"])
    assert overrides and overrides == set(a.loc[a["action"] == "ELIGIBILITY_OVERRIDE", "entity_id"])
    assert a["audit_id"].is_monotonic_increasing and a["event_time"].is_monotonic_increasing
    assert set(g.tables["plans"]["plan_id"]) <= set(a["entity_id"])


def test_every_table_is_exported_as_json_or_jsonl(built):
    g, out = built
    for name in g.tables:
        assert (out / "data" / f"{name}.json").exists() or (out / "data" / f"{name}.jsonl").exists(), name


def test_distribution_and_boundary_reports(tmp_path_factory):
    cfg = Config(n_customers=6000)
    out = tmp_path_factory.mktemp("big")
    export(generate(cfg), out, "pytest", sql=False)
    s = run_validation(out, check_sql_load=False)
    acc = s["coverage"]["acceptance"]
    assert acc["seasonality_visible_in_usage"] and acc["seasonal_dips_are_hard_negatives"]
    assert (out / "validation" / "distribution_report.md").exists() and (out / "validation" / "boundary_coverage.md").exists()
    cases = s["boundary_coverage"]["cases"]
    assert len(cases) >= 30
    common = [c for c in cases if c["category"] in ("normal", "boundary") and c["required"]]
    assert all(c["covered"] for c in common), [c["case"] for c in common if not c["covered"]]


def test_prospect_funnel_links_to_customers(built):
    g, _ = built
    pr, pe, cu = g.tables["prospects"], g.tables["prospect_events"], g.tables["customers"]
    assert pr["prospect_id"].iloc[0] == "PRS-000001" and pe["prospect_event_id"].str.match(r"^PEV-PRS-\d{6}-\d{2}$").all()
    assert set(pr["status"]) == {"OPEN", "CONVERTED", "LOST"}
    conv = pr[pr["status"] == "CONVERTED"]
    acquired = cu[cu["signup_date"] >= "2025-07-01"]
    assert set(conv["converted_customer_id"]) == set(acquired["customer_id"])      # every window customer has exactly one prospect
    assert conv["converted_customer_id"].is_unique
    merged = conv.merge(cu, left_on="converted_customer_id", right_on="customer_id")
    assert (merged["closed_date"] == merged["signup_date"]).all()
    assert (merged["source_channel"] == merged["acquisition_channel"]).all()
    legacy = cu[cu["signup_date"] < "2025-07-01"]["customer_id"]
    assert not legacy.isin(pr["converted_customer_id"]).any()                       # optional 1:0..1 link


def test_prospects_do_not_change_existing_tables():
    # prospects use their own random stream: customers' churn/offer data must not depend on them
    a = generate(Config(n_customers=300))
    assert a.tables["customers"]["signup_date"].notna().all()
    assert len(a.tables["prospects"]) > len(a.tables["customers"][a.tables["customers"]["signup_date"] >= "2025-07-01"])


def test_validator_flags_broken_funnel(built, tmp_path):
    _, out = built

    def break_funnel(data):
        df = pd.read_csv(data / "prospect_events.csv", dtype=str)
        i = df.index[df["event_type"] == "CONVERTED"][0]
        df.loc[i, "event_type"] = "LOST"
        df.to_csv(data / "prospect_events.csv", index=False)

    s = _corrupt_and_validate(out, tmp_path, break_funnel)
    assert not s["passed"]
    assert s["checks"]["L02"]["violations"] > 0 or s["checks"]["A08"]["violations"] > 0


# ---- optional extensions: multi-campaign and hidden override flag ---------------------------------------------------
@pytest.fixture(scope="module")
def multi(tmp_path_factory):
    g = generate(Config(n_customers=N, n_campaigns=2))
    out = tmp_path_factory.mktemp("multi")
    export(g, out, "pytest", sql=True)
    return g, out


@pytest.fixture(scope="module")
def hidden(tmp_path_factory):
    g = generate(Config(n_customers=N, expose_override_flag=False))
    out = tmp_path_factory.mktemp("hidden")
    export(g, out, "pytest", sql=True)
    return g, out


def test_default_has_one_campaign(built):
    g, _ = built
    assert g.tables["campaigns"]["campaign_id"].tolist() == ["CMP-2026-RETENTION-Q3"]
    assert set(g.tables["campaign_contacts"]["campaign_id"]) == {"CMP-2026-RETENTION-Q3"}


def test_multi_campaign_is_valid_and_segmented(multi):
    g, out = multi
    cp, cc, cu = g.tables["campaigns"], g.tables["campaign_contacts"], g.tables["customers"].set_index("customer_id")
    assert len(cp) == 2 and set(cc["campaign_id"]) == set(cp["campaign_id"])
    seg = cu["segment"].reindex(cc["customer_id"]).to_numpy()
    assert (cc["campaign_id"].str.rsplit("-", n=1).str[-1].to_numpy() == seg).all()
    assert cc.groupby("customer_id")["campaign_id"].nunique().max() == 1
    s = run_validation(out)
    assert s["passed"] and s["total_error_violations"] == 0 and s["checks"]["C03"]["violations"] == 0
    assert all(v["recall"] == 1.0 for v in s["ground_truth_reconciliation"]["per_issue_type"].values())


def test_multi_campaign_validator_flags_wrong_campaign(multi, tmp_path):
    _, out = multi

    def swap(data):
        df = pd.read_csv(data / "campaign_contacts.csv", dtype=str)
        other = sorted(df["campaign_id"].unique())
        df.loc[0, "campaign_id"] = other[0] if df.loc[0, "campaign_id"] != other[0] else other[1]
        df.to_csv(data / "campaign_contacts.csv", index=False)

    s = _corrupt_and_validate(out, tmp_path, swap)
    assert not s["passed"] and s["checks"]["C03"]["violations"] > 0


def test_hidden_override_flag_leaves_no_marker_but_is_still_detected(hidden):
    g, out = hidden
    cc, a = g.tables["campaign_contacts"], g.tables["admin_audit_log"]
    assert set(cc["contact_source"]) == {"AUTO_ELIGIBLE"} and set(cc["launched_by_role"]) <= {"SYSTEM"}
    assert "ELIGIBILITY_OVERRIDE" not in set(a["action"])
    s = run_validation(out)
    inel = s["ground_truth_reconciliation"]["per_issue_type"]["INELIGIBLE_OFFER_SENT"]
    assert inel["injected"] > 0 and inel["recall"] == 1.0
    assert s["passed"] and s["ground_truth_reconciliation"]["unexplained_rule_violations"] == 0


def test_hiding_flag_changes_nothing_else(built, hidden):
    a, b = built[0].tables, hidden[0].tables
    for k in a:
        if k in ("campaign_contacts", "admin_audit_log"):
            continue
        assert a[k].equals(b[k]), k
    keep = [c for c in a["campaign_contacts"].columns if c not in ("contact_source", "launched_by_role", "eligibility_evaluation_id")]
    assert a["campaign_contacts"][keep].equals(b["campaign_contacts"][keep])
