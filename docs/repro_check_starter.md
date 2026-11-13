# Reproducibility check

- generator command: `python -m churnlab repro --customers 1500 --seed 20261022`
- seed: **20261022**, customers: **1,500**
- method: the full generate+export pipeline was run twice in fresh directories; row counts and SHA-256 of every exported file were compared
- a different seed (20261023) produces different data: **True**
- **result: IDENTICAL (reproducible)**

| file | rows run1 | rows run2 | sha256 run1 | sha256 run2 | match |
|---|---|---|---|---|---|
| data/admin_audit_log.csv | 20 | 20 | 7eed5f1aa087a076 | 7eed5f1aa087a076 | OK |
| data/admin_audit_log.json | 20 | 20 | a0d85e6527c8e814 | a0d85e6527c8e814 | OK |
| data/billing_events.csv | 48879 | 48879 | eb3edb94eb29720c | eb3edb94eb29720c | OK |
| data/billing_events.json | 48879 | 48879 | e260c139f4047529 | e260c139f4047529 | OK |
| data/campaign_contacts.csv | 1044 | 1044 | b325e30b41d7ac5b | b325e30b41d7ac5b | OK |
| data/campaign_contacts.json | 1044 | 1044 | 57f534921a552076 | 57f534921a552076 | OK |
| data/churn_outcomes.csv | 1342 | 1342 | f7c6db7cb86bcb66 | f7c6db7cb86bcb66 | OK |
| data/churn_outcomes.json | 1342 | 1342 | d01131b1a029fc61 | d01131b1a029fc61 | OK |
| data/customers.csv | 1500 | 1500 | e07ace354a4e1ef1 | e07ace354a4e1ef1 | OK |
| data/customers.json | 1500 | 1500 | 197d13ba33dc2a9a | 197d13ba33dc2a9a | OK |
| data/eligibility_evaluations.csv | 5352 | 5352 | e41f6671d698cfc0 | e41f6671d698cfc0 | OK |
| data/eligibility_evaluations.json | 5352 | 5352 | ac88b58b570e6d01 | ac88b58b570e6d01 | OK |
| data/eligibility_rules.csv | 6 | 6 | 97af7f2663dd5811 | 97af7f2663dd5811 | OK |
| data/eligibility_rules.json | 6 | 6 | 80d931b47e79111e | 80d931b47e79111e | OK |
| data/offer_eligibility_rules.csv | 17 | 17 | 268857a023af08fb | 268857a023af08fb | OK |
| data/offer_eligibility_rules.json | 17 | 17 | 0b11a2632dc4b853 | 0b11a2632dc4b853 | OK |
| data/offers.csv | 4 | 4 | b56adae464663142 | b56adae464663142 | OK |
| data/offers.json | 4 | 4 | 4a889591cb1a72fa | 4a889591cb1a72fa | OK |
| data/plans.csv | 5 | 5 | f958f2a9cdde8608 | f958f2a9cdde8608 | OK |
| data/plans.json | 5 | 5 | 2bba7aead2ee8720 | 2bba7aead2ee8720 | OK |
| data/prospect_events.csv | 4152 | 4152 | b2b22f1b3ac8872e | b2b22f1b3ac8872e | OK |
| data/prospect_events.json | 4152 | 4152 | 4f50522ebe4a14cd | 4f50522ebe4a14cd | OK |
| data/prospects.csv | 1163 | 1163 | 903e131138e85951 | 903e131138e85951 | OK |
| data/prospects.json | 1163 | 1163 | 5cfe1f711c99aedf | 5cfe1f711c99aedf | OK |
| data/retention_outcomes.csv | 1044 | 1044 | e8755c95004e3c1d | e8755c95004e3c1d | OK |
| data/retention_outcomes.json | 1044 | 1044 | f25e1e2f91584039 | f25e1e2f91584039 | OK |
| data/subscription_events.csv | 2582 | 2582 | 3fda816bc0bf9b20 | 3fda816bc0bf9b20 | OK |
| data/subscription_events.json | 2582 | 2582 | 588cf55765b3206e | 588cf55765b3206e | OK |
| data/subscriptions.csv | 1617 | 1617 | f64aee92449e815e | f64aee92449e815e | OK |
| data/subscriptions.json | 1617 | 1617 | 5a98edc42f95c14d | 5a98edc42f95c14d | OK |
| data/support_cases.csv | 2528 | 2528 | 0cc629338bd027ea | 0cc629338bd027ea | OK |
| data/support_cases.json | 2528 | 2528 | 6d7a31471bd4e0b8 | 6d7a31471bd4e0b8 | OK |
| data/usage_snapshots.csv | 24523 | 24523 | 91bdf9d55b015f63 | 91bdf9d55b015f63 | OK |
| data/usage_snapshots.json | 24523 | 24523 | 1db80378d1999c94 | 1db80378d1999c94 | OK |
| ground_truth/ground_truth.csv |  |  | f3ef4a1c476f0286 | f3ef4a1c476f0286 | OK |
| ground_truth/ground_truth.json |  |  | 12a0390feebdd0dc | 12a0390feebdd0dc | OK |
| ground_truth/latent_truth.csv |  |  | 561f20cba7e5dd72 | 561f20cba7e5dd72 | OK |
| ground_truth/true_effects.json |  |  | 996d1f57e88dd5b2 | 996d1f57e88dd5b2 | OK |
| sql/schema.sql |  |  | 0d13eb357c1a3dc2 | 0d13eb357c1a3dc2 | OK |
| sql/seed.sql |  |  | e845a2166375e9a9 | e845a2166375e9a9 | OK |
