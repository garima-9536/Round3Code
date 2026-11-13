# Data dictionary

Generated from `churnlab/schema.py` (single source of truth). `req` = required (NOT NULL). `DERIVED` in a rule means the value is computed from source records, not independently generated.

| Table | Entity | Kind | Primary key | Description |
|---|---|---|---|---|
| `customers` | Customer | master | customer_id | One row per customer (master). |
| `prospects` | Prospect | master | prospect_id | Pre-customer lead. Customers acquired inside the window originate from a CONVERTED prospect; customers that pre-date the window have none (optional 1:0..1 link). |
| `prospect_events` | ProspectEvent | event | prospect_event_id | Append-only lead funnel history (CREATED -> CONTACTED* / TRIAL_STARTED? -> CONVERTED \| LOST). |
| `plans` | Plan (reference) | reference | plan_id | Plan price list with effective dating (price changes create a new version, never overwrite). |
| `subscriptions` | Subscription | master | subscription_id | Customer subscription. -01 is the primary (core) subscription, -02 an optional add-on. |
| `subscription_events` | SubscriptionEvent | event | subscription_event_id | Append-only lifecycle history (state changes are events, never overwrites). |
| `usage_snapshots` | UsageSnapshot | event | snapshot_id | One monthly snapshot per active subscription-month. |
| `billing_events` | BillingEvent | event | billing_event_id | Invoice, payment, failure, credit and write-off ledger. Balance per invoice must reconcile to zero. |
| `support_cases` | SupportCase | event | case_id | Support interactions with explicit lifecycle timestamps. |
| `offers` | Offer | reference | offer_id | Retention offer catalogue (all offers are bill credits). |
| `eligibility_rules` | EligibilityRule | reference | rule_id | Versioned, effective-dated eligibility / margin rules. |
| `offer_eligibility_rules` | OfferEligibilityRule (bridge) | reference | offer_id, rule_id | N:M bridge: which rules gate which offers. |
| `eligibility_evaluations` | (decision log) | event | evaluation_id | System eligibility decision per customer x offer at the campaign date, with the rules that failed. |
| `campaigns` | Campaign | reference | campaign_id | Retention campaign definition; a customer belongs to exactly one campaign (one per segment in multi-campaign mode). |
| `campaign_contacts` | CampaignContact | event | contact_id | One row per customer assignment/contact in the retention campaign (randomised treatment/control). |
| `churn_outcomes` | ChurnOutcome | outcome | churn_outcome_id | Churn label per scored customer for the 2026 prediction date / horizon. |
| `retention_outcomes` | RetentionOutcome | outcome | retention_outcome_id | Outcome of each campaign contact: response, cost and retention. |
| `admin_audit_log` | AdminAuditLog | event | audit_id | Who changed what and when: price/rule/offer publication and manual eligibility overrides (system-administrator and marketing/sales-ops actors). Append-only. |

## customers

**Entity:** Customer - One row per customer (master).  
**Primary key:** `customer_id`

| field | type | req | allowed values / range | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `customer_id` | str | Y | regex `^CUS-\d{6}$` |  | yes | CUS-000001 sequence, immutable |
| `signup_date` | date | Y |  |  |  | equals ACTIVATED date of the primary subscription |
| `segment` | str | Y | CONSUMER, SMB |  |  |  |
| `region` | str | Y | NORTH, SOUTH, EAST, WEST |  |  |  |
| `acquisition_channel` | str | Y | ORGANIC, PAID, REFERRAL, PARTNER |  |  |  |
| `marketing_consent` | bool | Y | 0, 1 |  |  | 1 = may receive retention offers |
| `status_as_of_data_end` | str | Y | ACTIVE, CHURNED |  |  | derived from primary subscription lifecycle |

## prospects

**Entity:** Prospect - Pre-customer lead. Customers acquired inside the window originate from a CONVERTED prospect; customers that pre-date the window have none (optional 1:0..1 link).  
**Primary key:** `prospect_id`

| field | type | req | allowed values / range | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `prospect_id` | str | Y | regex `^PRS-\d{6}$` |  | yes | numbered by created_date |
| `created_date` | date | Y |  |  |  | = CREATED event date |
| `source_channel` | str | Y | ORGANIC, PAID, REFERRAL, PARTNER |  |  | equals customers.acquisition_channel when converted |
| `segment` | str | Y | CONSUMER, SMB |  |  |  |
| `region` | str | Y | NORTH, SOUTH, EAST, WEST |  |  |  |
| `marketing_consent` | bool | Y | 0, 1 |  |  |  |
| `owner_id` | str | Y | regex `^USR-3\d{2}$` |  |  | sales-ops owner of the lead |
| `status` | str | Y | OPEN, CONVERTED, LOST |  |  | DERIVED from the terminal prospect event; OPEN = no terminal event by data end |
| `closed_date` | date | N |  |  |  | DERIVED = terminal event date; for CONVERTED = customer signup_date |
| `converted_customer_id` | str | N |  |  |  | FK customers; set iff CONVERTED; unique |
| `lost_reason` | str | N | PRICE, COMPETITOR, NO_RESPONSE, NOT_A_FIT |  |  | set iff LOST |

**Foreign keys**

- `converted_customer_id` -> `customers.customer_id` (1:0..1; optional) lead that became a customer; legacy customers have none

## prospect_events

**Entity:** ProspectEvent - Append-only lead funnel history (CREATED -> CONTACTED* / TRIAL_STARTED? -> CONVERTED | LOST).  
**Primary key:** `prospect_event_id`

| field | type | req | allowed values / range | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `prospect_event_id` | str | Y | regex `^PEV-PRS-\d{6}-\d{2}$` |  | yes |  |
| `prospect_id` | str | Y |  |  |  | FK prospects |
| `event_seq` | int | Y | 1 ..  |  |  | 1..n chronological per prospect |
| `event_type` | str | Y | CREATED, CONTACTED, TRIAL_STARTED, CONVERTED, LOST |  |  |  |
| `event_date` | date | Y |  |  |  |  |
| `reason_code` | str | N | PRICE, COMPETITOR, NO_RESPONSE, NOT_A_FIT |  |  | LOST only |
| `customer_id` | str | N |  |  |  | FK customers; CONVERTED only |

**Foreign keys**

- `prospect_id` -> `prospects.prospect_id` (1:N; required) funnel history
- `customer_id` -> `customers.customer_id` (N:0..1; optional) CONVERTED event only

## plans

**Entity:** Plan (reference) - Plan price list with effective dating (price changes create a new version, never overwrite).  
**Primary key:** `plan_id`

| field | type | req | allowed values / range | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `plan_id` | str | Y | regex `^PLN-[A-Z]{3}-V\d+$` |  | yes |  |
| `plan_code` | str | Y | BASIC, STANDARD, PREMIUM, ADDON |  |  |  |
| `product_type` | str | Y | CORE, ADDON |  |  |  |
| `version` | int | Y | 1 ..  |  |  |  |
| `monthly_price` | decimal | Y | 0.01 ..  | USD |  |  |
| `unit_cost` | decimal | Y | 0 ..  | USD |  | <= monthly_price; margin = price - unit_cost |
| `effective_from` | date | Y |  |  |  |  |
| `effective_to` | date | N |  |  |  | null = open ended; >= effective_from |
| `status` | str | Y | ACTIVE, SUPERSEDED |  |  |  |

## subscriptions

**Entity:** Subscription - Customer subscription. -01 is the primary (core) subscription, -02 an optional add-on.  
**Primary key:** `subscription_id`

| field | type | req | allowed values / range | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `subscription_id` | str | Y | regex `^SUB-CUS-\d{6}-\d{2}$` |  | yes | SUB-<customer-id>-NN |
| `customer_id` | str | Y | regex `^CUS-\d{6}$` |  |  | FK customers |
| `product_type` | str | Y | CORE, ADDON |  |  |  |
| `is_primary` | bool | Y | 0, 1 |  |  |  |
| `initial_plan_code` | str | Y | BASIC, STANDARD, PREMIUM, ADDON |  |  |  |
| `current_plan_code` | str | Y | BASIC, STANDARD, PREMIUM, ADDON |  |  | derived from the last plan event |
| `start_date` | date | Y |  |  |  | = ACTIVATED event date |
| `end_date` | date | N |  |  |  | = terminal event date; null while ACTIVE; >= start_date |
| `status` | str | Y | ACTIVE, CANCELLED, TERMINATED_NONPAYMENT |  |  | derived from terminal event |
| `payment_method` | str | Y | CARD, BANK_DEBIT, WALLET |  |  |  |
| `billing_day` | int | Y | 1 .. 1 | day of month |  |  |
| `cohort_month` | str | Y | regex `^\d{4}-\d{2}$` |  |  | YYYY-MM of start_date |

**Foreign keys**

- `customer_id` -> `customers.customer_id` (1:N; required) customer has 1..2 subscriptions

## subscription_events

**Entity:** SubscriptionEvent - Append-only lifecycle history (state changes are events, never overwrites).  
**Primary key:** `subscription_event_id`

| field | type | req | allowed values / range | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `subscription_event_id` | str | Y | regex `^SEV-SUB-CUS-\d{6}-\d{2}-\d{2}$` |  | yes |  |
| `subscription_id` | str | Y |  |  |  | FK subscriptions |
| `event_seq` | int | Y | 1 ..  |  |  | 1..n per subscription in chronological order |
| `event_type` | str | Y | ACTIVATED, PLAN_UPGRADE, PLAN_DOWNGRADE, PRICE_CHANGE, CANCELLED, TERMINATED_NONPAYMENT |  |  |  |
| `event_date` | date | Y |  |  |  |  |
| `from_plan_code` | str | N | BASIC, STANDARD, PREMIUM, ADDON |  |  |  |
| `to_plan_code` | str | Y | BASIC, STANDARD, PREMIUM, ADDON |  |  |  |
| `plan_id` | str | Y |  |  |  | FK plans: price version in force after the event |
| `reason_code` | str | N | PRICE, LOW_USAGE, SERVICE_QUALITY, COMPETITOR, OTHER, NONPAYMENT, ADDON_REMOVED, PRIMARY_ENDED |  |  | only on terminal events |

**Foreign keys**

- `subscription_id` -> `subscriptions.subscription_id` (1:N; required) lifecycle history
- `plan_id` -> `plans.plan_id` (N:1; required) 

## usage_snapshots

**Entity:** UsageSnapshot - One monthly snapshot per active subscription-month.  
**Primary key:** `snapshot_id`

| field | type | req | allowed values / range | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `snapshot_id` | str | Y | regex `^SNAP-SUB-CUS-\d{6}-\d{2}-\d{4}-\d{2}$` |  | yes | SNAP-<subscription-id>-YYYY-MM |
| `subscription_id` | str | Y |  |  |  | FK subscriptions |
| `snapshot_month` | date | Y |  |  |  | first day of the month |
| `plan_code` | str | Y | BASIC, STANDARD, PREMIUM, ADDON |  |  | plan in force during the month |
| `days_in_service` | int | Y | 1 .. 31 | days |  | < days in month for partial first/last month |
| `sessions` | int | Y | 0 ..  | count |  |  |
| `active_days` | int | Y | 0 .. 31 | days |  | <= days_in_service and <= sessions |
| `avg_session_minutes` | decimal | Y | 0 ..  | minutes |  |  |
| `usage_hours` | decimal | Y | 0 ..  | hours |  | DERIVED = round(sessions*avg_session_minutes/60, 2) |
| `features_used` | int | Y | 0 .. 10 | count |  |  |

**Foreign keys**

- `subscription_id` -> `subscriptions.subscription_id` (1:N; required) one per active month

## billing_events

**Entity:** BillingEvent - Invoice, payment, failure, credit and write-off ledger. Balance per invoice must reconcile to zero.  
**Primary key:** `billing_event_id`

| field | type | req | allowed values / range | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `billing_event_id` | str | Y | regex `^BILL-SUB-CUS-\d{6}-\d{2}-\d{6}-\d{2}$` |  | yes | BILL-<subscription-id>-YYYYMM-NN |
| `subscription_id` | str | Y |  |  |  | FK subscriptions |
| `billing_period` | str | Y | regex `^\d{4}-\d{2}$` |  |  |  |
| `event_date` | date | Y |  |  |  |  |
| `event_type` | str | Y | INVOICE, PAYMENT, PAYMENT_FAILED, CREDIT, WRITE_OFF |  |  |  |
| `amount` | decimal | Y | 0.01 ..  | USD |  |  |
| `currency` | str | Y | USD |  |  |  |
| `invoice_id` | str | N |  |  |  | FK billing_events (self); required unless INVOICE |
| `service_cost` | decimal | N |  | USD |  | INVOICE only = plan unit_cost |
| `offer_id` | str | N |  |  |  | FK offers; CREDIT only |
| `failure_reason` | str | N | CARD_DECLINED, INSUFFICIENT_FUNDS, BANK_REJECTED, WALLET_ERROR |  |  | PAYMENT_FAILED only |

**Foreign keys**

- `subscription_id` -> `subscriptions.subscription_id` (1:N; required) 
- `invoice_id` -> `billing_events.billing_event_id` (1:N; optional) payments/credits point at their invoice
- `offer_id` -> `offers.offer_id` (N:1; optional) CREDIT events carry the offer for cost tracking

## support_cases

**Entity:** SupportCase - Support interactions with explicit lifecycle timestamps.  
**Primary key:** `case_id`

| field | type | req | allowed values / range | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `case_id` | str | Y | regex `^CASE-CUS-\d{6}-\d{2}$` |  | yes | CASE-<customer-id>-NN |
| `customer_id` | str | Y |  |  |  | FK customers |
| `subscription_id` | str | Y |  |  |  | FK subscriptions |
| `opened_at` | datetime | Y |  |  |  |  |
| `first_response_at` | datetime | N |  |  |  | >= opened_at |
| `escalated_at` | datetime | N |  |  |  | >= opened_at |
| `resolved_at` | datetime | N |  |  |  | >= opened_at; null unless status RESOLVED |
| `status` | str | Y | OPEN, ESCALATED, RESOLVED |  |  | state as of data end |
| `category` | str | Y | TECHNICAL, BILLING, ACCOUNT, FEEDBACK, CANCELLATION_QUERY |  |  |  |
| `priority` | str | Y | LOW, MEDIUM, HIGH |  |  |  |
| `channel` | str | Y | PHONE, CHAT, EMAIL |  |  |  |
| `assigned_agent_id` | str | Y | regex `^AGT-\d{3}$` |  |  |  |
| `csat_score` | int | N | 1 .. 5 | 1-5 |  |  |
| `resolution_hours` | decimal | N | 0 ..  | hours |  | DERIVED = resolved_at - opened_at |

**Foreign keys**

- `customer_id` -> `customers.customer_id` (1:N; required) 
- `subscription_id` -> `subscriptions.subscription_id` (N:1; required) 

## offers

**Entity:** Offer - Retention offer catalogue (all offers are bill credits).  
**Primary key:** `offer_id`

| field | type | req | allowed values / range | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `offer_id` | str | Y | regex `^OFF-2026-\d{6}$` |  | yes |  |
| `offer_name` | str | Y |  |  |  |  |
| `offer_type` | str | Y | PCT_DISCOUNT, FREE_MONTHS, FIXED_CREDIT |  |  |  |
| `discount_pct` | decimal | N | 1 .. 100 | percent |  | PCT_DISCOUNT; FREE_MONTHS = 100 |
| `fixed_credit_amount` | decimal | N | 0.01 ..  | USD |  | FIXED_CREDIT only |
| `duration_months` | int | Y | 1 .. 12 | months |  | number of invoices credited |
| `valid_from` | date | Y |  |  |  |  |
| `valid_to` | date | Y |  |  |  | >= valid_from |
| `status` | str | Y | ACTIVE, EXPIRED |  |  |  |

## eligibility_rules

**Entity:** EligibilityRule - Versioned, effective-dated eligibility / margin rules.  
**Primary key:** `rule_id`

| field | type | req | allowed values / range | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `rule_id` | str | Y | regex `^ELR-\d{6}$` |  | yes |  |
| `rule_code` | str | Y | MIN_TENURE_MONTHS, MARKETING_CONSENT, MAX_FAILED_PAYMENTS_WINDOW, MARGIN_CAP_PCT |  |  |  |
| `description` | str | Y |  |  |  |  |
| `operator` | str | Y | >=, ==, <= |  |  |  |
| `threshold_value` | decimal | Y |  |  |  |  |
| `effective_from` | date | Y |  |  |  |  |
| `effective_to` | date | N |  |  |  |  |
| `status` | str | Y | ACTIVE, RETIRED |  |  |  |
| `superseded_by_rule_id` | str | N |  |  |  | FK eligibility_rules |

**Foreign keys**

- `superseded_by_rule_id` -> `eligibility_rules.rule_id` (1:0..1; optional) 

## offer_eligibility_rules

**Entity:** OfferEligibilityRule (bridge) - N:M bridge: which rules gate which offers.  
**Primary key:** `offer_id, rule_id`

| field | type | req | allowed values / range | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `offer_id` | str | Y |  |  |  | FK offers |
| `rule_id` | str | Y |  |  |  | FK eligibility_rules |
| `effective_from` | date | Y |  |  |  |  |
| `effective_to` | date | N |  |  |  |  |

**Foreign keys**

- `offer_id` -> `offers.offer_id` (N:M bridge; required) 
- `rule_id` -> `eligibility_rules.rule_id` (N:M bridge; required) 

## eligibility_evaluations

**Entity:** (decision log) - System eligibility decision per customer x offer at the campaign date, with the rules that failed.  
**Primary key:** `evaluation_id`

| field | type | req | allowed values / range | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `evaluation_id` | str | Y | regex `^EVAL-2026-\d{6}$` |  | yes |  |
| `customer_id` | str | Y |  |  |  | FK customers |
| `subscription_id` | str | Y |  |  |  | FK subscriptions (primary) |
| `offer_id` | str | Y |  |  |  | FK offers |
| `evaluated_on` | date | Y |  |  |  | = prediction_date; uses only data before that date |
| `tenure_months` | int | Y | 0 ..  | months |  | floor(days since start / 30.4375) |
| `plan_code` | str | Y | BASIC, STANDARD, PREMIUM, ADDON |  |  |  |
| `marketing_consent` | bool | Y | 0, 1 |  |  |  |
| `failed_payments_window` | int | Y | 0 ..  | count |  | PAYMENT_FAILED events in the look-back window |
| `monthly_margin` | decimal | Y |  | USD |  | price - unit_cost of the plan in force the day before evaluation |
| `offer_cost` | decimal | Y | 0 ..  | USD |  | max planned credit cost over the offer duration |
| `margin_cap_amount` | decimal | Y |  | USD |  | margin_cap_pct% x monthly_margin x margin horizon |
| `failed_rules` | str | N |  |  |  | semicolon-separated rule_codes |
| `decision` | str | Y | ELIGIBLE, INELIGIBLE |  |  |  |

**Foreign keys**

- `customer_id` -> `customers.customer_id` (1:N; required) 
- `subscription_id` -> `subscriptions.subscription_id` (1:N; required) 
- `offer_id` -> `offers.offer_id` (N:1; required) 

## campaigns

**Entity:** Campaign - Retention campaign definition; a customer belongs to exactly one campaign (one per segment in multi-campaign mode).  
**Primary key:** `campaign_id`

| field | type | req | allowed values / range | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `campaign_id` | str | Y | regex `^CMP-` |  | yes |  |
| `campaign_name` | str | Y |  |  |  |  |
| `objective` | str | Y |  |  |  |  |
| `target_segment` | str | Y | ALL, CONSUMER, SMB |  |  | ALL = every segment; otherwise only customers of this segment are contacted |
| `start_date` | date | Y |  |  |  | = prediction_date |
| `end_date` | date | Y |  |  |  | >= start_date; = horizon end - 1 day |
| `planned_treat_share` | decimal | Y | 0 ..  |  |  | target share randomised to TREATMENT |
| `launched_by_role` | str | Y | MARKETING_OPS, SALES_OPS |  |  |  |
| `status` | str | Y | PLANNED, ACTIVE, COMPLETED |  |  |  |

## campaign_contacts

**Entity:** CampaignContact - One row per customer assignment/contact in the retention campaign (randomised treatment/control).  
**Primary key:** `contact_id`

| field | type | req | allowed values / range | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `contact_id` | str | Y | regex `^CNT-2026-\d{6}$` |  | yes |  |
| `campaign_id` | str | Y |  |  |  | FK campaigns |
| `customer_id` | str | Y |  |  |  | FK customers |
| `subscription_id` | str | Y |  |  |  | FK subscriptions (primary) |
| `offer_id` | str | N |  |  |  | FK offers; null for CONTROL |
| `randomization_group` | str | Y | TREATMENT, CONTROL |  |  | a customer belongs to exactly one arm per campaign |
| `randomization_stratum` | str | Y |  |  |  | plan\|tenure band; randomisation done within stratum |
| `contact_date` | date | Y |  |  |  | >= prediction_date |
| `channel` | str | N | EMAIL, SMS, IN_APP |  |  | null for CONTROL |
| `contact_status` | str | Y | DELIVERED, BOUNCED, HOLDOUT |  |  |  |
| `contact_source` | str | Y | AUTO_ELIGIBLE, MANUAL_OVERRIDE |  |  | MANUAL_OVERRIDE bypasses the eligibility engine |
| `launched_by_role` | str | Y | SYSTEM, MARKETING_OPS, SALES_OPS |  |  |  |
| `eligibility_evaluation_id` | str | N |  |  |  | FK eligibility_evaluations used for the decision; null for CONTROL/override |
| `override_reason` | str | N |  |  |  | documented reason when MANUAL_OVERRIDE |

**Foreign keys**

- `campaign_id` -> `campaigns.campaign_id` (N:1; required) 
- `customer_id` -> `customers.customer_id` (1:N; required) 1:1 per campaign (violations = anomalies)
- `subscription_id` -> `subscriptions.subscription_id` (1:N; required) 
- `offer_id` -> `offers.offer_id` (N:1; optional) null for CONTROL
- `eligibility_evaluation_id` -> `eligibility_evaluations.evaluation_id` (N:0..1; optional) 

## churn_outcomes

**Entity:** ChurnOutcome - Churn label per scored customer for the 2026 prediction date / horizon.  
**Primary key:** `churn_outcome_id`

| field | type | req | allowed values / range | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `churn_outcome_id` | str | Y | regex `^CHURN-CUS-\d{6}-2026$` |  | yes | CHURN-<customer-id>-2026 |
| `customer_id` | str | Y |  |  |  | FK customers |
| `subscription_id` | str | Y |  |  |  | FK subscriptions (primary) |
| `prediction_date` | date | Y |  |  |  |  |
| `horizon_end_date` | date | Y |  |  |  | exclusive; = prediction_date + horizon months |
| `churn_definition` | str | Y | PRIMARY_SUBSCRIPTION_ENDED_IN_HORIZON |  |  | label = primary subscription ends (cancelled or terminated for non-payment) with prediction_date <= end < horizon_end |
| `churned_in_horizon` | bool | Y | 0, 1 |  |  | DERIVED from subscription_events |
| `churn_event_id` | str | N |  |  |  | FK subscription_events |
| `churn_event_date` | date | N |  |  |  | must be >= prediction_date for scored customers |
| `churn_type` | str | N | VOLUNTARY, INVOLUNTARY |  |  |  |
| `days_to_churn` | int | N |  | days |  | DERIVED churn_event_date - prediction_date; >= 0 |
| `churned_after_horizon` | bool | Y | 0, 1 |  |  | ended after horizon_end but before data end (right-censoring info) |

**Foreign keys**

- `customer_id` -> `customers.customer_id` (1:0..1; required) one label per customer per year
- `subscription_id` -> `subscriptions.subscription_id` (1:1; required) 
- `churn_event_id` -> `subscription_events.subscription_event_id` (N:0..1; optional) 

## retention_outcomes

**Entity:** RetentionOutcome - Outcome of each campaign contact: response, cost and retention.  
**Primary key:** `retention_outcome_id`

| field | type | req | allowed values / range | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `retention_outcome_id` | str | Y | regex `^RET-2026-\d{6}$` |  | yes |  |
| `contact_id` | str | Y |  |  | yes | FK campaign_contacts (1:1) |
| `customer_id` | str | Y |  |  |  | FK customers |
| `subscription_id` | str | Y |  |  |  | FK subscriptions |
| `offer_id` | str | N |  |  |  | FK offers |
| `randomization_group` | str | Y | TREATMENT, CONTROL |  |  |  |
| `offer_viewed` | bool | Y | 0, 1 |  |  |  |
| `offer_accepted` | bool | Y | 0, 1 |  |  | 1 only if viewed |
| `accepted_at` | date | N |  |  |  | >= contact_date |
| `offer_cost` | decimal | Y | 0 ..  | USD |  | DERIVED = sum of CREDIT events for (subscription, offer) |
| `credits_applied_count` | int | Y | 0 ..  | count |  | DERIVED |
| `retained_at_horizon_end` | bool | Y | 0, 1 |  |  | DERIVED = no churn event before horizon_end |
| `revenue_collected_horizon` | decimal | Y | 0 ..  | USD |  | DERIVED sum PAYMENT in [contact_date, horizon_end) |
| `service_cost_horizon` | decimal | Y | 0 ..  | USD |  | DERIVED sum INVOICE service_cost in window |
| `net_margin_horizon` | decimal | Y |  | USD |  | DERIVED = revenue_collected - service_cost (offer cost already netted) |
| `retention_attributed` | bool | Y | 0, 1 |  |  | 1 iff TREATMENT and accepted and retained; at most one attributed offer per customer |
| `attributed_offer_id` | str | N |  |  |  | = offer_id when retention_attributed |

**Foreign keys**

- `contact_id` -> `campaign_contacts.contact_id` (1:1; required) 
- `customer_id` -> `customers.customer_id` (1:N; required) 
- `subscription_id` -> `subscriptions.subscription_id` (1:N; required) 
- `offer_id` -> `offers.offer_id` (N:1; optional) 
- `attributed_offer_id` -> `offers.offer_id` (N:1; optional) 

## admin_audit_log

**Entity:** AdminAuditLog - Who changed what and when: price/rule/offer publication and manual eligibility overrides (system-administrator and marketing/sales-ops actors). Append-only.  
**Primary key:** `audit_id`

| field | type | req | allowed values / range | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| `audit_id` | str | Y | regex `^AUD-\d{6}$` |  | yes | numbered in chronological order |
| `event_time` | datetime | Y |  |  |  |  |
| `actor_role` | str | Y | SYSTEM_ADMIN, MARKETING_OPS, SALES_OPS |  |  |  |
| `actor_id` | str | Y | regex `^USR-\d{3}$` |  |  |  |
| `action` | str | Y | PRICE_VERSION_PUBLISHED, RULE_ACTIVATED, RULE_RETIRED, OFFER_PUBLISHED, ELIGIBILITY_OVERRIDE |  |  |  |
| `entity_table` | str | Y | plans, eligibility_rules, offers, campaign_contacts |  |  |  |
| `entity_id` | str | Y |  |  |  | polymorphic reference: must exist in entity_table's primary key; event_time precedes the entity's effective date |
| `details` | str | N |  |  |  |  |

## Ground truth (separate files, never used as features)

| file | content |
|---|---|
| `ground_truth/ground_truth.csv` / `.json` | one row per injected anomaly: issue_type, entity, expected decision, expected detecting check |
| `ground_truth/latent_truth.csv` | per in-scope customer: potential churn outcomes with/without offer, latent traits (seasonal user, risk, price sensitivity) |
| `ground_truth/true_effects.json` | true average treatment effects (overall and per offer) used only to score estimators |
