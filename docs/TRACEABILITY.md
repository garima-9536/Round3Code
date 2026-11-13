# Requirements traceability

Each line of the brief, where it is implemented, and how to see the proof.
Paths are relative to the project root. "Run" means `python -m churnlab demo` (about 10 s), which writes everything to `output/demo/`.

## 1. Data design

| Requirement | Where | Proof |
|---|---|---|
| 10 required entities with PK, FK, cardinality, optional links | `churnlab/schema.py` (18 tables, 10 required + 8 supporting) | `docs/data_dictionary.md`, `docs/er_diagram.md` |
| Effective dates, lifecycle states, bridge table, event history | `eligibility_rules` / `offer_eligibility_rules` (bridge); `subscription_events`, `billing_events`, `prospect_events` | Checks `L01`, `L02`, `D01` in `validation/validation_summary.md` |
| ID conventions (`CUS-000001`, `SUB-<cust>-01`, `SNAP-...`, `OFF-2026-000001`, `CHURN-<cust>-2026`) | `churnlab/ids.py` | Test `test_ids_follow_conventions` |
| Data dictionary (type, required, allowed values, units, rules) | `churnlab/schema.py`, `churnlab/docs.py` | `docs/data_dictionary.md` |
| Actors: customer/prospect, marketing/sales ops, support agent, analyst, system admin | `prospects`, `campaign_contacts.launched_by_role`, `support_cases.assigned_agent_id`, `admin_audit_log`, `evaluate/` | Table `admin_audit_log`; `evaluation/evaluation_report.md` |

## 2. Generation

| Requirement | Where | Proof |
|---|---|---|
| Parent tables first, valid parent IDs | `churnlab/generate/pipeline.py` | Check `S02` (foreign keys): 0 violations |
| 20,000 customers, 18 months, 5-20% churn | `churnlab/config.py`, `generate/simulate.py` | Overview tab of the report: "14% ever churned" (full run) |
| Voluntary and involuntary churn, plan changes, seasonal users, offer non-response | `generate/simulate.py` (dunning rule, price shock, seasonal flag), `generate/campaign.py` | Report, "Churn behaviour" tab; `validation/distribution_report.md` |
| Fixed seed, one generator for starter and full scale | `Config.seed = 20261022`, `scaled_config()` | `python -m churnlab repro --scale starter` prints `IDENTICAL` |
| Derived values calculated from source records | `generate/derive.py` | Checks `A01`-`A09` |
| Four labelled edge cases injected after a valid baseline | `generate/anomalies.py` (see note) | Report, "Data quality" tab: 50 of each, recall 1.00 |
| Separate ground truth, never used as a feature | `output/<run>/ground_truth/` | Test `test_ground_truth_is_separate_from_inputs`; `test_features_use_only_data_before_prediction_date` |

Note: the ineligible-offer case is created as a manual override during the campaign run (documented), the other three are added after the baseline.

## 3. Validation and exports

| Requirement | Where | Proof |
|---|---|---|
| PK, FK, enums, dates, arithmetic, lifecycle, duplicates | `churnlab/validate/checks.py` | `validation/validation_summary.md`: 28 checks, 0 structural errors |
| Business rules: eligibility, margin cap, leakage, attribution | checks `B01`-`B03`, `X01`-`X03`, `T01` | Same file; every RULE violation maps to a ground-truth row |
| Validator really detects corruption | `tests/test_pipeline.py` (mutation tests) | `python -m pytest tests -q` |
| CSV, JSON, SQL exports | `churnlab/export.py` | `output/<run>/data/`, `output/<run>/sql/` |
| README, dictionary, generator command, seed, manifest, validation summary | `churnlab/export.py`, `churnlab/docs.py` | `output/<run>/manifest.json`, `output/<run>/docs/` |
| Regenerate twice and compare checksums | `churnlab/repro.py` | `docs/repro_check_starter.md`, `docs/repro_check_full.md` |

## 4. Evaluation focus (a)-(g)

| Focus | Evidence |
|---|---|
| (a) Realistic distributions | `validation/distribution_report.md`; report "Churn behaviour" tab |
| (b) Valid IDs and joins | Checks `S01`, `S02`; SQL load check `Q02` |
| (c) Lifecycle correctness | Checks `L01`, `L02`, `D01` |
| (d) Derived values | Checks `A01`-`A09` |
| (e) Boundary, failure and exception coverage | `validation/boundary_coverage.md`; report "Data quality" tab (all required cases present) |
| (f) Separate ground truth | `ground_truth/` folder and the two tests listed in section 2 |
| (g) Reproducibility | `repro` command and `docs/repro_check_*.md` |

## 5. Business questions

| Question | Answer in the full run | Where |
|---|---|---|
| Can behaviour predict churn without leakage? | Yes. Trained on earlier cutoffs only, tested on 2026-07-01. AUC about 0.73-0.74 vs 0.64 for a usage-drop rule. | `churnlab/evaluate/features.py`; report "Overview" |
| Does the offer cause lower churn, or just correlate? | Randomised holdout: 1.35 pts lower churn (95% CI 0.33 to 2.37, p = 0.009). The naive comparison shows about 0. | report "Overview" and "Offer test" |
| Are eligibility and cost rules respected? | Yes: checks `B02`, `B03`; the only violations are the 50 labelled ineligible offers. | `validation/validation_summary.md` |
| Which customers should get an offer? | Treating everyone loses money; targeting a small top share is positive but noisy. | report "Targeting" |
| Is the churn label explicit and leak-free? | `churn_outcomes.churn_definition`; check `T01`; leakage guard in the evaluation report | `docs/data_dictionary.md` |

## 6. Provenance

No external or public data is used (`manifest.json` has `external_data.used = false`). All records are generated by the code in this repository.
