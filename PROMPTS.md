# Prompts used to build this project

All 20 prompts, in the order they were given, exactly as written (typos kept). Prompt 1 is the original business brief.
A prompt marked *(reply)* answers a question I had just asked.

| # | Topic |
|---|---|
| 1 | Original brief: read it and plan first |
| 2 | Build the full working project |
| 3 | How to verify it works, and what can be improved |
| 4 | Fix the `pytests` typo |
| 5 | Check compliance with the checklist |
| 6 | Fix the four gaps |
| 7 | Next step: multi-campaign or hiding the override flag |
| 8 | Checklist counts only |
| 9 | Plan the missing item: prospects |
| 10 | Will it affect anything else? |
| 11 | Go ahead with prospects |
| 12 | Original to-do list: done vs not done |
| 13 | Build the two extras without changing anything |
| 14 | Add clear install/run/verify steps (plan first) |
| 15 | Run it, keep code unchanged, make it easy to read |
| 16 | Ideas to make it friendly and impressive |
| 17 | Interactive but not flashy report, no data changes |
| 18 | How will others see report.html |
| 19 | Sample report or published link |
| 20 | Save all prompts in a separate file |

## Prompt 1: Original brief: read it and plan first

```text
This is the business problem read it thorougly and make plan of how this will be excecuted first then we will decide what and how to proceed.Also I am planning to use python in this
but we will decide the techstack latter first lets understand it and plan

<pasted_content id="53ec">
Business Context / Problem
Identify likely churn from behavioral changes and test retention offers with eligibility, cost and outcome tracking.

Objective and Scope
Build a working solution for this end-to-end workflow: Identify likely churn from behavioral changes and test retention offers with eligibility, cost and outcome tracking. The solution should expose key decisions and exceptions, preserve traceability, and produce measurable outputs. Medium complexity means multiple related entities, conditional rules, at least one exception path and meaningful evaluation metrics.

Primary Actors / Systems
Customer/prospect, marketing/sales operations, support agent, analyst and system administrator

Business Workflow and Rules
1. Generate/reference master data first: Customer, Subscription, UsageSnapshot, BillingEvent, SupportCase.
2. Generate dependent transaction/event records using valid parent IDs.
3. Apply business logic: Create subscription/product cohorts; generate monthly usage, billing and support history; define churn event and prediction horizon; build features only before prediction date; define offer eligibility and margin limits; simulate randomized offer/control groups and outcomes.
4. Persist state changes as explicit records/events where relevant; do not overwrite history.
5. Generate outcomes and ground-truth labels from documented rules, not independent random assignment.

Entities and Relationships
Core entities: Customer, Subscription, UsageSnapshot, BillingEvent, SupportCase, Offer, EligibilityRule, CampaignContact, ChurnOutcome, RetentionOutcome. Define a primary key for every entity and foreign keys for every relationship. Document cardinality (1:1, 1:N, N:M), optional relationships, effective dates and lifecycle states. Use bridge tables for many-to-many relationships; retain event history for state changes; validate all joins. For deliberate anomaly cases, keep an issue_type/ground_truth label rather than silently corrupting unrelated rows.

ID / Nomenclature Conventions
CUS-000001; SUB-<customer-id>-01; SNAP-<subscription-id>-2026-01; OFF-2026-000001; CHURN-<customer-id>-2026.

Synthetic Data Generation Instructions (Granular)
Step 1 — Write a data dictionary for: Customer, Subscription, UsageSnapshot, BillingEvent, SupportCase, Offer, EligibilityRule, CampaignContact, ChurnOutcome, RetentionOutcome. For each field specify type, required/optional, allowed values, units, uniqueness and validation rule.
Step 2 — Create parent/master tables first, then child and event tables. Apply this domain-specific generation logic: Create subscription/product cohorts; generate monthly usage, billing and support history; define churn event and prediction horizon; build features only before prediction date; define offer eligibility and margin limits; simulate randomized offer/control groups and outcomes.
Step 3 — Apply deterministic IDs and naming: CUS-000001; SUB-<customer-id>-01; SNAP-<subscription-id>-2026-01; OFF-2026-000001; CHURN-<customer-id>-2026. Keep counters zero-padded, IDs immutable, and referenced IDs exactly consistent across files.
Step 4 — Generate the baseline volume: Generate 20,000 subscribers over 18 months with 5–20% churn. Include voluntary/involuntary churn, plan changes, seasonal users and offer non-response. Use a fixed seed (e.g. 20261022) and parameterize scale so starter and full datasets use the same generator.
Step 5 — Generate valid baseline records first, then inject labelled edge cases: Churn label precedes prediction date; offer sent to ineligible customer; treatment/control leakage; retained customer attributed to multiple offers.
Step 6 — Calculate derived values (totals, balances, scores, statuses and dates) from source records rather than generating them independently.
Step 7 — Produce a separate ground_truth.csv/json for known anomalies, expected decisions or labels; never leak it into input features.
Step 8 — Run validation: primary-key uniqueness, foreign-key integrity, allowed enums, date ordering, arithmetic reconciliation, lifecycle transitions and duplicate checks.
Step 9 — Export CSV/JSON/SQL seed data plus README, schema/data dictionary, generator command, fixed seed, source manifest and validation summary.
Step 10 — Regenerate twice with the same seed and compare row counts/checksums to demonstrate reproducibility.

Suggested Volume and Coverage
Generate 20,000 subscribers over 18 months with 5–20% churn. Include voluntary/involuntary churn, plan changes, seasonal users and offer non-response.

Required Edge Cases / Negative Scenarios
Churn label precedes prediction date; offer sent to ineligible customer; treatment/control leakage; retained customer attributed to multiple offers.

Validation Rules / Acceptance Criteria
Evaluation is temporal; offer eligibility and cost are respected; churn definition is explicit; incremental lift is distinguished from correlation.

Evaluation Focus for Generated Data
Review: (a) realistic distributions and meaningful variation; (b) consistent IDs and valid joins; (c) dependency/lifecycle consistency across entities; (d) correct derived values and reconciliation; (e) normal, boundary, failure and exception coverage; (f) separate ground truth; (g) fixed-seed reproducibility, documentation and lawful provenance.

Public Data Guidance / Lawful Use
External data is optional. If used, record source URL, dataset/version, retrieval date, license/terms, attribution, transformations and fields discarded. Use only data you are legally permitted to access and redistribute; do not bypass access controls or collect confidential/personal information. If licensing or suitability is unclear, use synthetic data and cite public reference data only for schema inspiration.
</pasted_content id="53ec">
```

## Prompt 2: Build the full working project

```text
lets start building this and create full working project
```

## Prompt 3: How to verify it works, and what can be improved

```text
tell me step by step how will i know whether it is working and what else can be done to improve it
```

## Prompt 4: Fix the `pytests` typo

```text
python -m pytests -q

C:\Program Files\Python314\python.exe: No module named pytests
help resolve this
```

## Prompt 5: Check compliance with the checklist

```text
before proceeding help me understand whether we have complyed all the check list requirements
```

## Prompt 6: Fix the four gaps *(reply)*

```text
yes
```

## Prompt 7: Next step: multi-campaign or hiding the override flag

```text
take on something else, such as the multi-campaign extension or hiding the override flag?
```

## Prompt 8: Checklist counts only

```text
just tell how many have we complted from original checklist just give the number
that are done
that can be improved
that is not done
```

## Prompt 9: Plan the missing item: prospects

```text
lets plan and underatnd how to compelte that one that is not done yet i.e Prospects (pre-customer leads)
```

## Prompt 10: Will it affect anything else?

```text
will it affect something else?
```

## Prompt 11: Go ahead with prospects

```text
then we can proceed to complete that
```

## Prompt 12: Original to-do list: done vs not done

```text
now out original to-do list what is completed what is not
```

## Prompt 13: Build the two extras without changing anything

```text
lets do  The multi-campaign extension and hiding the override flag are extras you proposed, not part of your brief. ensure it works properly without doing any changes
also tell the steps to esnure that with extra proposed idea
i can verify
```

## Prompt 14: Add clear install/run/verify steps (plan first)

```text
Ensure to include clear steps so another person can install dependencies,configure the project,run it and verify the behaviour
lets plan before doing any changes and tell me where we will add and what?
```

## Prompt 15: Run it, keep code unchanged, make it easy to read

```text
ensure it is working and code is not affected at all
also ensure that it is easy for other person to read and understand and also locate all the steps properply and concise
```

## Prompt 16: Ideas to make it friendly and impressive

```text
is there anything that we ca do so that is friendly to understand and also impressive to clear this round
```

## Prompt 17: Interactive but not flashy report, no data changes

```text
lets make it interactive but not flashy also do the order that you suggsted and ensure no data chnages and code is properly working
```

## Prompt 18: How will others see report.html

```text
how will the other person be able to see report.html file
```

## Prompt 19: Sample report or published link *(reply)*

```text
yes
```

## Prompt 20: Save all prompts in a separate file

```text
create a separate file in which you include all the prompts seprately
```
