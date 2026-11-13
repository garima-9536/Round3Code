# Reproducibility check

- generator command: `python -m churnlab repro --customers 1500 --seed 20261022`
- seed: **20261022**, customers: **1,500**
- method: the full generate+export pipeline was run twice in fresh directories; row counts and SHA-256 of every exported file were compared
- a different seed (20261023) produces different data: **True**
- **result: IDENTICAL (reproducible)**

| file | rows run1 | rows run2 | sha256 run1 | sha256 run2 | match |
|---|---|---|---|---|---|
| data/admin_audit_log.csv | 16 | 16 | 3ba28e8686895261 | 3ba28e8686895261 | OK |
| data/admin_audit_log.json | 16 | 16 | 2917f97a46dee006 | 2917f97a46dee006 | OK |
| data/billing_events.csv | 48927 | 48927 | 2544215898c8c90b | 2544215898c8c90b | OK |
| data/billing_events.json | 48927 | 48927 | 6a398ef162034f9d | 6a398ef162034f9d | OK |
| data/campaign_contacts.csv | 1044 | 1044 | 3e5c89d905bf031c | 3e5c89d905bf031c | OK |
| data/campaign_contacts.json | 1044 | 1044 | 1d3d7a058d7cce98 | 1d3d7a058d7cce98 | OK |
| data/campaigns.csv | 2 | 2 | d468fb4d12c44427 | d468fb4d12c44427 | OK |
| data/campaigns.json | 2 | 2 | 0f4852492518177f | 0f4852492518177f | OK |
| data/churn_outcomes.csv | 1342 | 1342 | 291ab7cbdf3745b8 | 291ab7cbdf3745b8 | OK |
| data/churn_outcomes.json | 1342 | 1342 | c4d276fdeded2a7b | c4d276fdeded2a7b | OK |
| data/customers.csv | 1500 | 1500 | a0ab320c5fe61070 | a0ab320c5fe61070 | OK |
| data/customers.json | 1500 | 1500 | c05fc7f3375fe8e0 | c05fc7f3375fe8e0 | OK |
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
| data/retention_outcomes.csv | 1044 | 1044 | dc3f73c8c3d4f5bf | dc3f73c8c3d4f5bf | OK |
| data/retention_outcomes.json | 1044 | 1044 | 6ab982a99b7d8c59 | 6ab982a99b7d8c59 | OK |
| data/subscription_events.csv | 2585 | 2585 | 56dd53043daac10c | 56dd53043daac10c | OK |
| data/subscription_events.json | 2585 | 2585 | 96bdf0c65a01e2a2 | 96bdf0c65a01e2a2 | OK |
| data/subscriptions.csv | 1617 | 1617 | 1b4ba1e8371019da | 1b4ba1e8371019da | OK |
| data/subscriptions.json | 1617 | 1617 | b71f3edfceb6ba2f | b71f3edfceb6ba2f | OK |
| data/support_cases.csv | 2528 | 2528 | 62743eae2f9ea81d | 62743eae2f9ea81d | OK |
| data/support_cases.json | 2528 | 2528 | 8106739f04eb6857 | 8106739f04eb6857 | OK |
| data/usage_snapshots.csv | 24508 | 24508 | 78c19e7ae9957153 | 78c19e7ae9957153 | OK |
| data/usage_snapshots.json | 24508 | 24508 | cd9d84ddae6c5d5d | cd9d84ddae6c5d5d | OK |
| ground_truth/ground_truth.csv |  |  | 3424b440d57d1f5c | 3424b440d57d1f5c | OK |
| ground_truth/ground_truth.json |  |  | b25c0a9f05a13ad3 | b25c0a9f05a13ad3 | OK |
| ground_truth/latent_truth.csv |  |  | f631085db5195025 | f631085db5195025 | OK |
| ground_truth/true_effects.json |  |  | 23abdc6c103996f7 | 23abdc6c103996f7 | OK |
| sql/schema.sql |  |  | de76df7a079d2958 | de76df7a079d2958 | OK |
| sql/seed.sql |  |  | 16ab7f07668e5b0e | 16ab7f07668e5b0e | OK |
