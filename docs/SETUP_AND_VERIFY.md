# Setup, run and verify

Follow the numbered sections in order. Every command is run from the **project root** (the folder containing `churnlab/`).
Each step says what you should see. If you don't see it, go to [Troubleshooting](#7-troubleshooting).

| Step | Time |
|---|---|
| 1 Prerequisites | 1 min |
| 2 Install | 2 min |
| 3 Run (starter) | 10 s |
| 4 Verify | 2 min |
| 5 Options | - |
| 6 Verify the options | 1 min |

## 1. Prerequisites

- Python **3.10 or newer** (developed and tested on 3.14.5, Windows 11). Check: `python --version`
- Free disk: about 50 MB for starter, about 650 MB for full (`--no-sql` makes both smaller).
- No database, network access or external data is needed. All data is generated.

## 2. Install

Create an isolated environment, then install the libraries.

| Shell | Create and activate |
|---|---|
| PowerShell | `python -m venv .venv` then `.venv\Scripts\Activate.ps1` |
| Git Bash | `python -m venv .venv` then `source .venv/Scripts/activate` |
| macOS / Linux | `python3 -m venv .venv` then `source .venv/bin/activate` |

```
pip install -r requirements-lock.txt     # exact versions: use this to get identical checksums
# or: pip install -r requirements.txt    # newer versions allowed; results may differ slightly
```

**Check:** `python -c "import numpy, pandas, sklearn, scipy; print('ok')"` prints `ok`.

## 3. Run

```
python -m churnlab all --scale starter
```

This generates, validates and evaluates 1,500 customers in about 10 s. Expected output:

```
[generate] 1,500 customers, seed=20261022 -> output\starter
[validate] PASS  errors=0  rule_violations=24  -> output\starter\validation\validation_summary.md
[evaluate] report -> output\starter\evaluation\evaluation_report.md
```

For the full dataset (20,000 customers, about 1 minute, about 650 MB): `python -m churnlab all --scale full`

**Want to see the result first?** Open `docs/sample_report.html` in a browser. It is a saved copy of the full 20,000-customer run, so no installation is needed.

**Interactive report (optional, recommended):** `python -m churnlab demo` does all of the above into `output/demo/` and prints the headline results. Then open **`output/demo/report.html`** in any browser (no internet needed). Five tabs: Overview, Churn behaviour, Offer test, Targeting, Data quality. To build it for an existing run: `python -m churnlab report --out output/starter`.

## 4. Verify

Do these five checks. All must pass.

| # | Command | Expected result |
|---|---|---|
| 1 | `python -m pytest tests -q` | `21 passed` (about 1 min) |
| 2 | Look at the `[validate]` line from step 3 | `PASS  errors=0` |
| 3 | `python -m churnlab repro --scale starter` | `[repro] IDENTICAL` (data regenerated twice, SHA-256 of every file equal) |
| 4 | Open `output/starter/validation/validation_summary.md` | "Injected anomalies" table: 4 types, **recall 1.0**, unexplained RULE violations **0** |
| 5 | Open `output/starter/data/` | 18 tables as `.csv` and `.json`, with these row counts |

Starter row counts (seed 20261022):

| table | rows | table | rows |
|---|---|---|---|
| customers | 1,500 | eligibility_rules | 6 |
| prospects | 1,163 | offer_eligibility_rules | 17 |
| prospect_events | 4,152 | eligibility_evaluations | 5,352 |
| plans | 5 | campaigns | 1 |
| subscriptions | 1,617 | campaign_contacts | 1,044 |
| subscription_events | 2,582 | churn_outcomes | 1,342 |
| usage_snapshots | 24,523 | retention_outcomes | 1,044 |
| billing_events | 48,879 | admin_audit_log | 20 |
| support_cases | 2,528 | offers | 4 |

### What is in the output folder

| Path | Contents |
|---|---|
| `data/` | The 18 tables (CSV and JSON). These are the only files a model or analyst should read. |
| `ground_truth/` | The hidden answers. Used only by the validator and the scoring step. |
| `sql/` | `schema.sql` (tables, keys) and `seed.sql` (data). |
| `validation/` | `validation_summary.md`, `distribution_report.md`, `boundary_coverage.md`, `violations.csv` |
| `evaluation/` | `evaluation_report.md` (churn model, offer lift, cost) |
| `docs/`, `manifest.json` | README, generator command, seed, checksums |

## 5. Options

All options are optional. The defaults reproduce the shipped dataset.

| Option | Default | Meaning |
|---|---|---|
| `--scale starter\|full` | `starter` | 1,500 or 20,000 customers |
| `--customers N` | - | Any customer count (overrides `--scale`) |
| `--seed N` | `20261022` | Random seed. A different seed gives different data and different checksums. |
| `--out DIR` | `output/<scale>` | Where to write |
| `--no-sql` | off | Skip `seed.sql` (faster, smaller) |
| `--campaigns 2` | `1` | One randomised campaign per segment instead of one overall |
| `--hide-override-flag` | off | Manual overrides look like normal automatic contacts |

Individual steps: `python -m churnlab generate | validate --out DIR | evaluate --out DIR | docs`

## 6. Verify the options

Run the two extras into their own folders:

```
python -m churnlab all --scale starter --campaigns 2 --out output/demo_campaigns
python -m churnlab all --scale starter --hide-override-flag --out output/demo_hidden
```

| Option | Expected result |
|---|---|
| `--campaigns 2` | Validation `PASS`; `data/campaigns.csv` has 2 rows; each `campaign_id` ends in the customer's segment (`-CONSUMER` or `-SMB`); `evaluation_report.json` has `offer_experiment.by_campaign`. |
| `--hide-override-flag` | Validation `PASS`; searching `data/` for `MANUAL_OVERRIDE` or `ELIGIBILITY_OVERRIDE` finds nothing; the validation summary still shows INELIGIBLE_OFFER_SENT recall **1.0**. |
| Both | `python -m churnlab repro --scale starter --campaigns 2 --hide-override-flag` prints `IDENTICAL`. |

**Prove the validator works:** open `output/demo_campaigns/data/campaign_contacts.csv`, change the first `campaign_id` to the other campaign, save, then run `python -m churnlab validate --out output/demo_campaigns`. It must print `FAIL`, with check `C03` listed in `validation/validation_summary.md`.

## 7. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `No module named pytests` | Typo. The command is `python -m pytest tests -q` (no "s"). |
| `No module named sklearn` (or numpy, pandas, scipy) | Dependencies are not installed in the active Python. Activate the environment and rerun step 2. |
| `python` is not recognised, or is the wrong version | Use `py -3` (Windows) or `python3`, or give the full path to the interpreter. |
| `validate` fails after you edited a data file | Expected: it detects edits. Regenerate with step 3. |
| Evaluation includes records the validator would exclude | `evaluate` reads `validation/violations.csv`. Run `validate` first (`all` does this for you). |
| Checksums differ from this guide | Library versions differ. Install from `requirements-lock.txt`. |
| File-lock errors, or slow runs | The folder is inside OneDrive. Move the project, or pass `--out` to a folder outside it. |

## 8. Where things are

| Path | What |
|---|---|
| `churnlab/` | Code: `generate/` (data), `validate/` (checks), `evaluate/` (model and experiment), `cli.py` (commands) |
| `tests/` | The 21 tests |
| `docs/data_dictionary.md`, `docs/er_diagram.md` | Every table and field; table relationships |
| `docs/repro_check_*.md` | Saved reproducibility reports |
| `docs/TRACEABILITY.md` | Each requirement of the brief, where it is met, and how to check it |
| `README.md` | Result summary, design, definitions, assumptions and limitations |
| `scripts/calibrate.py` | How the churn rates were tuned (optional) |
