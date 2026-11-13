# churnlab - churn prediction and retention-offer testing on synthetic data

A reproducible synthetic-data generator, validator and evaluator for the workflow
*"identify likely churn from behavioural changes, then test retention offers with eligibility, cost and outcome tracking"*.

- **20,000 customers / 21,449 subscriptions over 18 months** (2025-07 .. 2026-12), 14% churn (voluntary + involuntary), plan changes, a price-increase shock, seasonal users, offer non-response.
- 18 linked tables with explicit PK/FK, including a pre-customer prospect funnel, effective-dated rules, event history, a randomised treatment/control campaign, and a **separate ground truth**.
- One generator for starter (1,500 customers) and full (20,000) scale; fixed seed `20261022`.
- Validation (PK/FK/enums/dates/arithmetic/lifecycle/duplicates/eligibility/leakage), a temporal churn model, and an experiment analysis that separates **incremental lift from correlation**.

## The result in 60 seconds (full run, 20,000 customers)

- **Behaviour predicts churn.** A model trained only on earlier months reaches AUC 0.73-0.74 on the next quarter, against 0.64 for a simple "usage dropped" rule.
- **A naive analysis is misleading.** Comparing customers who accepted an offer with those who did not shows about 0 effect. The randomised holdout shows **1.35 points lower churn** (95% CI 0.33 to 2.37, p = 0.009). The true effect, known because the data is synthetic, is 2.1 points.
- **Treating everyone loses money.** 87% of offer cost went to accepters who would have stayed anyway. Targeting a small top share is positive, though noisy.
- **The data can be trusted.** 28 automated checks, 0 structural errors, all 200 injected edge cases detected, and regenerating twice gives identical files.

See it interactively: `python -m churnlab demo`, then open `output/demo/report.html`. Where each requirement of the brief is met: [docs/TRACEABILITY.md](docs/TRACEABILITY.md).

## Quick start

**New here? Follow [docs/SETUP_AND_VERIFY.md](docs/SETUP_AND_VERIFY.md)**: install, run, and a checklist with the expected results.

```bash
pip install -r requirements-lock.txt       # exact versions (or requirements.txt); Python 3.10+, tested on 3.14

python -m churnlab demo                    # everything + interactive report.html (~10 s)   -> output/demo
python -m churnlab report --out output/full   # interactive report for an existing run
python -m churnlab all --scale starter     # generate + validate + evaluate   (~10 s)  -> output/starter
python -m churnlab all --scale full        # 20,000 customers                 (~1 min) -> output/full

python -m churnlab generate --scale full   # step by step
python -m churnlab validate --out output/full
python -m churnlab evaluate --out output/full
python -m churnlab repro --scale full      # regenerate twice, compare row counts + SHA-256  -> docs/repro_check_full.md
python -m churnlab docs                    # data dictionary + ER diagram -> docs/
python -m pytest tests -q                  # 21 tests
python scripts/calibrate.py                # how the churn intercepts were chosen
```

Generator command used for the shipped full dataset: `python -m churnlab generate --scale full --seed 20261022`.

## What is in `output/<scale>/`

| path | content |
|---|---|
| `data/*.csv` + `.json` (tables <= 100k rows) or `.jsonl` (larger tables) | the 17 tables |
| `sql/schema.sql`, `sql/seed.sql` | DDL with PK/FK and INSERT seed (load-tested into SQLite by the validator) |
| `ground_truth/ground_truth.csv/.json` | one row per injected anomaly (issue_type, entity, expected decision, expected detecting check) |
| `ground_truth/latent_truth.csv`, `true_effects.json` | potential outcomes with/without offer and latent traits - used **only** to score estimators |
| `docs/data_dictionary.md`, `docs/er_diagram.md` | generated from `churnlab/schema.py` |
| `manifest.json` | generator command, seed, full config, per-file row counts and SHA-256, external-data statement, library versions |
| `validation/` | `validation_summary.md/json`, `violations.csv`, `distribution_report.md` (distributions, churn by month, seasonal users), `boundary_coverage.md` (normal / boundary / failure / exception cases) |
| `evaluation/` | `evaluation_report.md/json` |

Reproducibility evidence for the shipped runs is in `docs/repro_check_starter.md` and `docs/repro_check_full.md`.

## Design

### Timeline and definitions
- Window 2025-07-01 .. 2026-12-31. **Prediction date 2026-07-01**; features use records dated strictly before it.
- **Churn event** = the customer's primary subscription ends: `CANCELLED` (voluntary) or `TERMINATED_NONPAYMENT` (involuntary).
- **Label** = churn event with `prediction_date <= end < prediction_date + 3 calendar months` (2026-10-01, exclusive). Churn after the horizon is kept as `churned_after_horizon` (censoring information), not as a positive.
- The scored population (`churn_outcomes`) is the primary subscriptions alive on the prediction date.

### Why churn is not random (documented mechanism, `generate/simulate.py`)
A latent dissatisfaction trait drives *disengagement* (usage decays month over month), support contacts and payment failures.
Voluntary-churn hazard = `sigmoid(period intercept + 1.1 x disengagement depth + 0.7 x price shock + support load + slow/unresolved cases + recent downgrade + tenure/plan/segment/channel terms)`.
Involuntary churn is a **rule**: first payment fails -> retries on day 8 and 15 -> terminated on day 22 if all fail.
Seasonal users (18%) have usage dips that are *not* followed by churn (hard negatives). The 2026-03 STANDARD price rise raises hazard for price-sensitive customers. Intercepts are calibrated (`scripts/calibrate.py`) so a churn wave of ~9% hits the 3-month horizon.
Events are generated chronologically and every status/date/total in the other tables is *derived* from events (`generate/derive.py`).

### Offers, eligibility, cost
- 4 offers (15% / 30% for 3 months, 1 free month, $10 credit). All are bill credits recorded as `CREDIT` events carrying the `offer_id`, so cost = sum of credits.
- Rules are versioned and effective-dated (`eligibility_rules`) and linked to offers through the N:M bridge `offer_eligibility_rules`: tenure >= 3 months, marketing consent, no failed payment in 45 days, **margin cap** (offer cost <= 60% of 3 months of margin; the free month also needs 12 months tenure). A superseded 2025 margin rule (80%) is kept as `RETIRED`.
- Every customer x offer decision at the campaign date is stored in `eligibility_evaluations` with the failing rules (decision log). The validator recomputes it independently from the exported tables.
- Randomisation: eligible customers are randomised 70/30 treatment/control **within plan x tenure strata**; treated customers get one eligible offer chosen at random. Balance table is in the validation summary (all |SMD| < 0.05 at full scale).
- Response: delivery, view and acceptance are modelled; **acceptance is correlated with churn risk** (selection) while the *causal* effect is a log-odds reduction of voluntary churn for accepters (strength differs by offer and customer price sensitivity; ~6% of customers have a small backlash effect). Hence naive accepter-vs-non-accepter comparisons are biased by construction.

### Optional extensions (off by default - the default dataset is unchanged)
- `--campaigns 2`: one independently randomised campaign per segment (`CMP-2026-RETENTION-Q3-CONSUMER` / `-SMB`, strata include the segment). The `campaigns` table (always present, one row by default) is the parent of `campaign_contacts.campaign_id`. Validator check **C03** (contact inside campaign window and target segment, one campaign per customer, both arms present); `evaluation_report.json` gains `offer_experiment.by_campaign`.
- `--hide-override-flag`: manual overrides are exported as `AUTO_ELIGIBLE` / `SYSTEM` with no audit entry, so they cannot be filtered by a flag. They are still found by the independent eligibility recomputation (**B01**), and the truth stays in `ground_truth/`. Evaluation excludes them through `violations.csv`, as an analyst would.
- Both: `python -m churnlab all --scale starter --campaigns 2 --hide-override-flag --out output/demo`.

### Prospects (pre-customer leads)
- `prospects` (`PRS-000001`) and the append-only `prospect_events` (`PEV-PRS-000001-NN`): `CREATED -> CONTACTED* / TRIAL_STARTED? -> CONVERTED | LOST`; a lead with no terminal event at data end is `OPEN`. Status, closing date, converted customer and lost reason are **derived from the events**.
- Link to customers: `prospects.converted_customer_id -> customers` (1:0..1, optional). Customers acquired inside the window (about 22%) each come from exactly one CONVERTED prospect whose conversion date is the customer's activation date (`signup_date`) and whose channel/segment/region/consent match the customer. Customers who pre-date the window (legacy) have no prospect. (A `customers.prospect_id` column was deliberately not added: together with the link above it would create a circular foreign key.)
- Conversion is rule driven (documented in `generate/prospects.py`): channel (referral best, paid/partner weakest), segment, number of contacts and trial use; lost/converted funnel behaviour is drawn consistently with that rule. About 15,000 leads at full scale: 4,497 converted, 9,846 lost, 647 still open (31% conversion of closed leads).
- Prospects are generated from their own random stream *after* the customer simulation, so every pre-existing table is byte-identical to the version without prospects (verified by SHA-256).
- Validation: lifecycle (L02), derived-field/customer agreement and completeness (A08), date ordering (D01); funnel statistics are in `validation/distribution_report.md` and the funnel edge cases in `boundary_coverage.md`. Prospect features are **not** used by the churn model: the churn mechanism does not depend on lead behaviour, so they would carry no signal.

### Entities and keys
See `output/<scale>/docs/data_dictionary.md` (every field: type, required, allowed values, unit, uniqueness, validation rule) and `er_diagram.md` (cardinalities, optional links, lifecycle states).
Added beyond the ten named entities: `plans` (price versions), `subscription_events` (append-only state history), `offer_eligibility_rules` (bridge), `eligibility_evaluations` (decision log), `admin_audit_log` (who published prices/rules/offers and who performed each manual eligibility override - covers the system-administrator and ops actors; support agents appear as `assigned_agent_id`), `prospects` + `prospect_events` (pre-customer lead funnel, see below).

IDs: `CUS-000001`, `SUB-CUS-000001-01` (the `-02` subscription is an optional add-on), `SNAP-<subscription-id>-2026-01`, `OFF-2026-000001`, `CHURN-CUS-000001-2026`; also `BILL-<sub>-YYYYMM-NN`, `CASE-<customer>-NN`, `SEV-<sub>-NN`, `CNT-2026-NNNNNN`, `RET-2026-NNNNNN` (same number as its contact), `ELR-NNNNNN`, `EVAL-2026-NNNNNN`.

### Injected edge cases (all labelled in `ground_truth`, 50 each at full scale)
| issue_type | how it is injected | detecting check |
|---|---|---|
| `CHURN_LABEL_BEFORE_PREDICTION` | a label row for a customer who already churned before the prediction date | T01 |
| `INELIGIBLE_OFFER_SENT` | `MANUAL_OVERRIDE` contact to a customer failing eligibility (no documented reason); it then behaves like any treated customer | B01 |
| `TREATMENT_CONTROL_LEAKAGE` | a control customer also gets a treatment contact | X01 |
| `MULTI_OFFER_ATTRIBUTION` | a retained, attributed customer is attributed to a second offer | X03 |

Anomalies only add rows (or clearly identified override rows); unrelated rows are never silently corrupted. The evaluator excludes customers flagged by validation, **not** by reading ground truth.

## Validation (`validate/checks.py`)
ERROR checks must be zero: PK uniqueness (S01), FK integrity (S02), required/enum/range/id-pattern (S03), date ordering (D01), lifecycle transitions (L01), arm/offer consistency (C01), usage hours (A01), invoice reconciliation `invoice = credits + payments + write-offs` (A02), price-list match (A03), subscription/customer/churn/retention fields derived from events (A04-A06), resolution hours (A07), usage plan (A09), eligibility log reproducible (B02), actual cost <= planned cost (B03), audit-log references/override records/publication-before-effective-date (S04, C02, D02), SQL loads with no FK violations and row counts equal CSV (Q02), a crashed check group is reported (V00).
RULE checks (B01, X01-X03, T01) are business exceptions; the reconciliation step requires that *every* injected anomaly is detected and that *no* RULE violation exists outside the ground truth. Full-scale result: 0 errors, 300 rule violations (all explained), recall 1.0 for all four types. Mutation tests (`tests/`) corrupt PKs, FKs, amounts, enums and dates and confirm they are caught.

**Realism evidence** (`validation/distribution_report.md`): usage/tenure/invoice/support distributions, the post-2026-07 churn wave, and seasonal users - their usage varies about 2x more than other users' (median CV 0.43 vs 0.22) and a usage drop means little for them (11% churn) compared with other users (24%), so seasonal dips are genuine hard negatives. **Edge-path evidence** (`validation/boundary_coverage.md`): 32 normal/boundary/failure/exception cases, e.g. tenure exactly at the threshold, offer cost just under/over the margin cap, a fully credited invoice, retry-1/retry-2/write-off payment paths, bounced delivery, non-response, add-on cascade.

## Evaluation (`evaluate/`)
- **Temporal churn model**: train on cutoffs 2025-10-01, 2026-01-01, 2026-04-01 (label windows end before the test cutoff), test at 2026-07-01. A guard asserts the latest feature timestamp is < cutoff and a test proves that deleting all later data leaves the features unchanged.
- **Experiment**: ITT with CI and stratified estimate, CACE (randomisation as instrument, bootstrap CI), per-offer and per-plan effects, naive correlational estimates for contrast, cost per acceptor / per incremental retained customer, net benefit under a stated value assumption (6 months of margin).
- **Targeting**: T-learner uplift vs churn-risk vs random on a randomised holdout.
- Estimators are finally scored against `true_effects.json`.

Full-scale headline (see `output/full/evaluation/evaluation_report.md`): gradient boosting / logistic regression ROC-AUC ~0.74 vs 0.64 for a usage-drop heuristic, top-decile lift ~4.3x; offers reduce horizon churn from 8.9% to 7.5% (ITT 1.35 points, p~0.01, CI contains the simulator's true effect), while the naive accepter-vs-non-accepter comparison shows ~0 (true effect on accepters ~9 points). About 83% of accepters would not have churned anyway, so an untargeted campaign has negative net benefit - uplift-based targeting of the top ~20% is where the offer pays off.

## Provenance and lawful use
No external or public data is used, downloaded or redistributed; every record is synthetic. Public subscription/telecom churn schemas were consulted for schema inspiration only (no data, files or field values copied). `manifest.json` records this (`external_data.used = false`); retrieval date/licence/attribution are therefore not applicable. No personal information is generated: customer attributes are coarse categories.

## Assumptions and limitations
- "20,000 subscribers" is interpreted as 20,000 customers (each with a primary subscription; 7% also have an add-on).
- One campaign, run on the prediction date; control customers are held out (no placebo contact). Offers affect voluntary churn through acceptance; involuntary churn is affected only when a free month removes the payment attempt.
- Prospects exist only for customers acquired inside the window plus simulated lost/open leads; legacy customers have no lead history. Retention value uses the primary subscription only. Marketing consent is static (no opt-out history).
- Intercepts were calibrated at 20,000 customers; other scales keep the same hazard so rates stay in band but vary with sampling noise.
- `seed.sql` is ~150 MB at full scale; use `--no-sql` to skip it. Tables over 100,000 rows are exported as JSON Lines (`.jsonl`) instead of a single `.json` array.
- Model/uplift numbers are illustrative of the data's signal, not benchmarks; holdout control groups are small, so per-bucket uplift estimates are noisy (standard errors are reported).

## Layout
```
churnlab/
  config.py ids.py rng.py schema.py docs.py export.py repro.py cli.py
  generate/   master.py simulate.py campaign.py emit.py derive.py anomalies.py pipeline.py
  validate/   checks.py eligibility.py
  evaluate/   features.py report.py
scripts/calibrate.py     tests/test_pipeline.py     docs/     output/
```
