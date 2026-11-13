# Reproducibility check

- generator command: `python -m churnlab repro --customers 20000 --seed 20261022`
- seed: **20261022**, customers: **20,000**
- method: the full generate+export pipeline was run twice in fresh directories; row counts and SHA-256 of every exported file were compared
- a different seed (20261023) produces different data: **True**
- **result: IDENTICAL (reproducible)**

| file | rows run1 | rows run2 | sha256 run1 | sha256 run2 | match |
|---|---|---|---|---|---|
| data/admin_audit_log.csv | 66 | 66 | 5d64e0171219d16c | 5d64e0171219d16c | OK |
| data/admin_audit_log.json | 66 | 66 | f8b2bcf42eea5de9 | f8b2bcf42eea5de9 | OK |
| data/billing_events.csv | 649631 | 649631 | 186de4eed6a27de8 | 186de4eed6a27de8 | OK |
| data/billing_events.jsonl | 649631 | 649631 | 1d8e9702eb43f371 | 1d8e9702eb43f371 | OK |
| data/campaign_contacts.csv | 14019 | 14019 | b06406c01153dda1 | b06406c01153dda1 | OK |
| data/campaign_contacts.json | 14019 | 14019 | 2ee2cba58a636f23 | 2ee2cba58a636f23 | OK |
| data/churn_outcomes.csv | 17914 | 17914 | acb552b33ddb4fa4 | acb552b33ddb4fa4 | OK |
| data/churn_outcomes.json | 17914 | 17914 | b92592711468662c | b92592711468662c | OK |
| data/customers.csv | 20000 | 20000 | 8b356198f4cc937f | 8b356198f4cc937f | OK |
| data/customers.json | 20000 | 20000 | a94a3057b4f896a8 | a94a3057b4f896a8 | OK |
| data/eligibility_evaluations.csv | 71456 | 71456 | be83c8de3808e536 | be83c8de3808e536 | OK |
| data/eligibility_evaluations.json | 71456 | 71456 | 0e1fe1289ce00303 | 0e1fe1289ce00303 | OK |
| data/eligibility_rules.csv | 6 | 6 | 97af7f2663dd5811 | 97af7f2663dd5811 | OK |
| data/eligibility_rules.json | 6 | 6 | 80d931b47e79111e | 80d931b47e79111e | OK |
| data/offer_eligibility_rules.csv | 17 | 17 | 268857a023af08fb | 268857a023af08fb | OK |
| data/offer_eligibility_rules.json | 17 | 17 | 0b11a2632dc4b853 | 0b11a2632dc4b853 | OK |
| data/offers.csv | 4 | 4 | b56adae464663142 | b56adae464663142 | OK |
| data/offers.json | 4 | 4 | 4a889591cb1a72fa | 4a889591cb1a72fa | OK |
| data/plans.csv | 5 | 5 | f958f2a9cdde8608 | f958f2a9cdde8608 | OK |
| data/plans.json | 5 | 5 | 2bba7aead2ee8720 | 2bba7aead2ee8720 | OK |
| data/prospect_events.csv | 53698 | 53698 | a45fa803d164f2cf | a45fa803d164f2cf | OK |
| data/prospect_events.json | 53698 | 53698 | d037eadecd845196 | d037eadecd845196 | OK |
| data/prospects.csv | 14990 | 14990 | 9aa7db0f62a1632c | 9aa7db0f62a1632c | OK |
| data/prospects.json | 14990 | 14990 | 1f626acef9feef6f | 1f626acef9feef6f | OK |
| data/retention_outcomes.csv | 14019 | 14019 | 3a08d99776fda6a0 | 3a08d99776fda6a0 | OK |
| data/retention_outcomes.json | 14019 | 14019 | 89c6a80dd322bbf6 | 89c6a80dd322bbf6 | OK |
| data/subscription_events.csv | 34159 | 34159 | 4ab2fa25b4941a6e | 4ab2fa25b4941a6e | OK |
| data/subscription_events.json | 34159 | 34159 | e94ba6fbc5432d23 | e94ba6fbc5432d23 | OK |
| data/subscriptions.csv | 21449 | 21449 | 28b483e72d6d979f | 28b483e72d6d979f | OK |
| data/subscriptions.json | 21449 | 21449 | 04565a337db2ac18 | 04565a337db2ac18 | OK |
| data/support_cases.csv | 32685 | 32685 | 937e168464430594 | 937e168464430594 | OK |
| data/support_cases.json | 32685 | 32685 | b99a394e60ee9fb7 | b99a394e60ee9fb7 | OK |
| data/usage_snapshots.csv | 325152 | 325152 | 7a3449f582e026c7 | 7a3449f582e026c7 | OK |
| data/usage_snapshots.jsonl | 325152 | 325152 | 2bbeaa6b821f3b61 | 2bbeaa6b821f3b61 | OK |
| ground_truth/ground_truth.csv |  |  | ec10728fa9f241b5 | ec10728fa9f241b5 | OK |
| ground_truth/ground_truth.json |  |  | 5aee5ec94a7805f5 | 5aee5ec94a7805f5 | OK |
| ground_truth/latent_truth.csv |  |  | 1604d3e5d7cf093d | 1604d3e5d7cf093d | OK |
| ground_truth/true_effects.json |  |  | 3f6cfb67460bff5b | 3f6cfb67460bff5b | OK |
| sql/schema.sql |  |  | 0d13eb357c1a3dc2 | 0d13eb357c1a3dc2 | OK |
| sql/seed.sql |  |  | ac949b1e2d101d80 | ac949b1e2d101d80 | OK |
