"""Data dictionary = single source of truth.

Used to: render docs/data_dictionary.md, emit schema.sql, and drive generic validation
(required / enum / range / id-pattern / uniqueness checks).
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

PLAN_CODES = ["BASIC", "STANDARD", "PREMIUM", "ADDON"]
SUB_STATUS = ["ACTIVE", "CANCELLED", "TERMINATED_NONPAYMENT"]
SEV_TYPES = ["ACTIVATED", "PLAN_UPGRADE", "PLAN_DOWNGRADE", "PRICE_CHANGE", "CANCELLED", "TERMINATED_NONPAYMENT"]
REASONS = ["PRICE", "LOW_USAGE", "SERVICE_QUALITY", "COMPETITOR", "OTHER", "NONPAYMENT", "ADDON_REMOVED", "PRIMARY_ENDED"]
BILL_TYPES = ["INVOICE", "PAYMENT", "PAYMENT_FAILED", "CREDIT", "WRITE_OFF"]
CASE_CATEGORIES = ["TECHNICAL", "BILLING", "ACCOUNT", "FEEDBACK", "CANCELLATION_QUERY"]
OFFER_TYPES = ["PCT_DISCOUNT", "FREE_MONTHS", "FIXED_CREDIT"]
GROUPS = ["TREATMENT", "CONTROL"]


@dataclass
class Field:
    name: str
    type: str                       # str | int | decimal | date | datetime | bool
    required: bool = True
    allowed: Optional[list] = None  # enum
    unit: str = ""
    unique: bool = False
    rule: str = ""
    min: Optional[float] = None
    max: Optional[float] = None
    pattern: Optional[str] = None   # regex for ids


@dataclass
class Table:
    name: str
    entity: str
    description: str
    pk: list
    fields: list
    kind: str = "event"             # master | reference | event | outcome


@dataclass
class Rel:
    child: str
    child_col: str
    parent: str
    parent_col: str
    cardinality: str
    optional: bool
    note: str = ""


def F(name, type="str", required=True, allowed=None, unit="", unique=False, rule="", min=None, max=None, pattern=None):
    return Field(name, type, required, allowed, unit, unique, rule, min, max, pattern)


T = OrderedDict()


def _t(name, entity, description, pk, fields, kind):
    T[name] = Table(name, entity, description, pk if isinstance(pk, list) else [pk], fields, kind)


_t("customers", "Customer", "One row per customer (master).", "customer_id", [
    F("customer_id", pattern=r"^CUS-\d{6}$", unique=True, rule="CUS-000001 sequence, immutable"),
    F("signup_date", "date", rule="equals ACTIVATED date of the primary subscription"),
    F("segment", allowed=["CONSUMER", "SMB"]),
    F("region", allowed=["NORTH", "SOUTH", "EAST", "WEST"]),
    F("acquisition_channel", allowed=["ORGANIC", "PAID", "REFERRAL", "PARTNER"]),
    F("marketing_consent", "bool", allowed=[0, 1], rule="1 = may receive retention offers"),
    F("status_as_of_data_end", allowed=["ACTIVE", "CHURNED"], rule="derived from primary subscription lifecycle"),
], "master")

_t("prospects", "Prospect", "Pre-customer lead. Customers acquired inside the window originate from a CONVERTED prospect; "
   "customers that pre-date the window have none (optional 1:0..1 link).", "prospect_id", [
    F("prospect_id", pattern=r"^PRS-\d{6}$", unique=True, rule="numbered by created_date"),
    F("created_date", "date", rule="= CREATED event date"),
    F("source_channel", allowed=["ORGANIC", "PAID", "REFERRAL", "PARTNER"], rule="equals customers.acquisition_channel when converted"),
    F("segment", allowed=["CONSUMER", "SMB"]),
    F("region", allowed=["NORTH", "SOUTH", "EAST", "WEST"]),
    F("marketing_consent", "bool", allowed=[0, 1]),
    F("owner_id", pattern=r"^USR-3\d{2}$", rule="sales-ops owner of the lead"),
    F("status", allowed=["OPEN", "CONVERTED", "LOST"], rule="DERIVED from the terminal prospect event; OPEN = no terminal event by data end"),
    F("closed_date", "date", required=False, rule="DERIVED = terminal event date; for CONVERTED = customer signup_date"),
    F("converted_customer_id", required=False, rule="FK customers; set iff CONVERTED; unique"),
    F("lost_reason", allowed=["PRICE", "COMPETITOR", "NO_RESPONSE", "NOT_A_FIT"], required=False, rule="set iff LOST"),
], "master")

_t("prospect_events", "ProspectEvent", "Append-only lead funnel history (CREATED -> CONTACTED* / TRIAL_STARTED? -> CONVERTED | LOST).", "prospect_event_id", [
    F("prospect_event_id", pattern=r"^PEV-PRS-\d{6}-\d{2}$", unique=True),
    F("prospect_id", rule="FK prospects"),
    F("event_seq", "int", min=1, rule="1..n chronological per prospect"),
    F("event_type", allowed=["CREATED", "CONTACTED", "TRIAL_STARTED", "CONVERTED", "LOST"]),
    F("event_date", "date"),
    F("reason_code", allowed=["PRICE", "COMPETITOR", "NO_RESPONSE", "NOT_A_FIT"], required=False, rule="LOST only"),
    F("customer_id", required=False, rule="FK customers; CONVERTED only"),
], "event")

_t("plans", "Plan (reference)", "Plan price list with effective dating (price changes create a new version, never overwrite).", "plan_id", [
    F("plan_id", pattern=r"^PLN-[A-Z]{3}-V\d+$", unique=True),
    F("plan_code", allowed=PLAN_CODES),
    F("product_type", allowed=["CORE", "ADDON"]),
    F("version", "int", min=1),
    F("monthly_price", "decimal", unit="USD", min=0.01),
    F("unit_cost", "decimal", unit="USD", min=0, rule="<= monthly_price; margin = price - unit_cost"),
    F("effective_from", "date"),
    F("effective_to", "date", required=False, rule="null = open ended; >= effective_from"),
    F("status", allowed=["ACTIVE", "SUPERSEDED"]),
], "reference")

_t("subscriptions", "Subscription", "Customer subscription. -01 is the primary (core) subscription, -02 an optional add-on.", "subscription_id", [
    F("subscription_id", pattern=r"^SUB-CUS-\d{6}-\d{2}$", unique=True, rule="SUB-<customer-id>-NN"),
    F("customer_id", pattern=r"^CUS-\d{6}$", rule="FK customers"),
    F("product_type", allowed=["CORE", "ADDON"]),
    F("is_primary", "bool", allowed=[0, 1]),
    F("initial_plan_code", allowed=PLAN_CODES),
    F("current_plan_code", allowed=PLAN_CODES, rule="derived from the last plan event"),
    F("start_date", "date", rule="= ACTIVATED event date"),
    F("end_date", "date", required=False, rule="= terminal event date; null while ACTIVE; >= start_date"),
    F("status", allowed=SUB_STATUS, rule="derived from terminal event"),
    F("payment_method", allowed=["CARD", "BANK_DEBIT", "WALLET"]),
    F("billing_day", "int", min=1, max=1, unit="day of month"),
    F("cohort_month", pattern=r"^\d{4}-\d{2}$", rule="YYYY-MM of start_date"),
], "master")

_t("subscription_events", "SubscriptionEvent", "Append-only lifecycle history (state changes are events, never overwrites).", "subscription_event_id", [
    F("subscription_event_id", pattern=r"^SEV-SUB-CUS-\d{6}-\d{2}-\d{2}$", unique=True),
    F("subscription_id", rule="FK subscriptions"),
    F("event_seq", "int", min=1, rule="1..n per subscription in chronological order"),
    F("event_type", allowed=SEV_TYPES),
    F("event_date", "date"),
    F("from_plan_code", allowed=PLAN_CODES, required=False),
    F("to_plan_code", allowed=PLAN_CODES),
    F("plan_id", rule="FK plans: price version in force after the event"),
    F("reason_code", allowed=REASONS, required=False, rule="only on terminal events"),
], "event")

_t("usage_snapshots", "UsageSnapshot", "One monthly snapshot per active subscription-month.", "snapshot_id", [
    F("snapshot_id", pattern=r"^SNAP-SUB-CUS-\d{6}-\d{2}-\d{4}-\d{2}$", unique=True, rule="SNAP-<subscription-id>-YYYY-MM"),
    F("subscription_id", rule="FK subscriptions"),
    F("snapshot_month", "date", rule="first day of the month"),
    F("plan_code", allowed=PLAN_CODES, rule="plan in force during the month"),
    F("days_in_service", "int", min=1, max=31, unit="days", rule="< days in month for partial first/last month"),
    F("sessions", "int", min=0, unit="count"),
    F("active_days", "int", min=0, max=31, unit="days", rule="<= days_in_service and <= sessions"),
    F("avg_session_minutes", "decimal", min=0, unit="minutes"),
    F("usage_hours", "decimal", min=0, unit="hours", rule="DERIVED = round(sessions*avg_session_minutes/60, 2)"),
    F("features_used", "int", min=0, max=10, unit="count"),
], "event")

_t("billing_events", "BillingEvent", "Invoice, payment, failure, credit and write-off ledger. Balance per invoice must reconcile to zero.", "billing_event_id", [
    F("billing_event_id", pattern=r"^BILL-SUB-CUS-\d{6}-\d{2}-\d{6}-\d{2}$", unique=True, rule="BILL-<subscription-id>-YYYYMM-NN"),
    F("subscription_id", rule="FK subscriptions"),
    F("billing_period", pattern=r"^\d{4}-\d{2}$"),
    F("event_date", "date"),
    F("event_type", allowed=BILL_TYPES),
    F("amount", "decimal", unit="USD", min=0.01),
    F("currency", allowed=["USD"]),
    F("invoice_id", required=False, rule="FK billing_events (self); required unless INVOICE"),
    F("service_cost", "decimal", required=False, unit="USD", rule="INVOICE only = plan unit_cost"),
    F("offer_id", required=False, rule="FK offers; CREDIT only"),
    F("failure_reason", allowed=["CARD_DECLINED", "INSUFFICIENT_FUNDS", "BANK_REJECTED", "WALLET_ERROR"], required=False,
      rule="PAYMENT_FAILED only"),
], "event")

_t("support_cases", "SupportCase", "Support interactions with explicit lifecycle timestamps.", "case_id", [
    F("case_id", pattern=r"^CASE-CUS-\d{6}-\d{2}$", unique=True, rule="CASE-<customer-id>-NN"),
    F("customer_id", rule="FK customers"),
    F("subscription_id", rule="FK subscriptions"),
    F("opened_at", "datetime"),
    F("first_response_at", "datetime", required=False, rule=">= opened_at"),
    F("escalated_at", "datetime", required=False, rule=">= opened_at"),
    F("resolved_at", "datetime", required=False, rule=">= opened_at; null unless status RESOLVED"),
    F("status", allowed=["OPEN", "ESCALATED", "RESOLVED"], rule="state as of data end"),
    F("category", allowed=CASE_CATEGORIES),
    F("priority", allowed=["LOW", "MEDIUM", "HIGH"]),
    F("channel", allowed=["PHONE", "CHAT", "EMAIL"]),
    F("assigned_agent_id", pattern=r"^AGT-\d{3}$"),
    F("csat_score", "int", required=False, min=1, max=5, unit="1-5"),
    F("resolution_hours", "decimal", required=False, min=0, unit="hours", rule="DERIVED = resolved_at - opened_at"),
], "event")

_t("offers", "Offer", "Retention offer catalogue (all offers are bill credits).", "offer_id", [
    F("offer_id", pattern=r"^OFF-2026-\d{6}$", unique=True),
    F("offer_name"),
    F("offer_type", allowed=OFFER_TYPES),
    F("discount_pct", "decimal", required=False, min=1, max=100, unit="percent", rule="PCT_DISCOUNT; FREE_MONTHS = 100"),
    F("fixed_credit_amount", "decimal", required=False, min=0.01, unit="USD", rule="FIXED_CREDIT only"),
    F("duration_months", "int", min=1, max=12, unit="months", rule="number of invoices credited"),
    F("valid_from", "date"),
    F("valid_to", "date", rule=">= valid_from"),
    F("status", allowed=["ACTIVE", "EXPIRED"]),
], "reference")

_t("eligibility_rules", "EligibilityRule", "Versioned, effective-dated eligibility / margin rules.", "rule_id", [
    F("rule_id", pattern=r"^ELR-\d{6}$", unique=True),
    F("rule_code", allowed=["MIN_TENURE_MONTHS", "MARKETING_CONSENT", "MAX_FAILED_PAYMENTS_WINDOW", "MARGIN_CAP_PCT"]),
    F("description"),
    F("operator", allowed=[">=", "==", "<="]),
    F("threshold_value", "decimal"),
    F("effective_from", "date"),
    F("effective_to", "date", required=False),
    F("status", allowed=["ACTIVE", "RETIRED"]),
    F("superseded_by_rule_id", required=False, rule="FK eligibility_rules"),
], "reference")

_t("offer_eligibility_rules", "OfferEligibilityRule (bridge)", "N:M bridge: which rules gate which offers.", ["offer_id", "rule_id"], [
    F("offer_id", rule="FK offers"),
    F("rule_id", rule="FK eligibility_rules"),
    F("effective_from", "date"),
    F("effective_to", "date", required=False),
], "reference")

_t("eligibility_evaluations", "(decision log)", "System eligibility decision per customer x offer at the campaign date, with the rules that failed.", "evaluation_id", [
    F("evaluation_id", pattern=r"^EVAL-2026-\d{6}$", unique=True),
    F("customer_id", rule="FK customers"),
    F("subscription_id", rule="FK subscriptions (primary)"),
    F("offer_id", rule="FK offers"),
    F("evaluated_on", "date", rule="= prediction_date; uses only data before that date"),
    F("tenure_months", "int", min=0, unit="months", rule="floor(days since start / 30.4375)"),
    F("plan_code", allowed=PLAN_CODES),
    F("marketing_consent", "bool", allowed=[0, 1]),
    F("failed_payments_window", "int", min=0, unit="count", rule="PAYMENT_FAILED events in the look-back window"),
    F("monthly_margin", "decimal", unit="USD", rule="price - unit_cost of the plan in force the day before evaluation"),
    F("offer_cost", "decimal", unit="USD", min=0, rule="max planned credit cost over the offer duration"),
    F("margin_cap_amount", "decimal", unit="USD", rule="margin_cap_pct% x monthly_margin x margin horizon"),
    F("failed_rules", required=False, rule="semicolon-separated rule_codes"),
    F("decision", allowed=["ELIGIBLE", "INELIGIBLE"]),
], "event")

_t("campaigns", "Campaign", "Retention campaign definition; a customer belongs to exactly one campaign (one per segment in multi-campaign mode).", "campaign_id", [
    F("campaign_id", pattern=r"^CMP-", unique=True),
    F("campaign_name"),
    F("objective"),
    F("target_segment", allowed=["ALL", "CONSUMER", "SMB"], rule="ALL = every segment; otherwise only customers of this segment are contacted"),
    F("start_date", "date", rule="= prediction_date"),
    F("end_date", "date", rule=">= start_date; = horizon end - 1 day"),
    F("planned_treat_share", "decimal", min=0, rule="target share randomised to TREATMENT"),
    F("launched_by_role", allowed=["MARKETING_OPS", "SALES_OPS"]),
    F("status", allowed=["PLANNED", "ACTIVE", "COMPLETED"]),
], "reference")

_t("campaign_contacts", "CampaignContact", "One row per customer assignment/contact in the retention campaign (randomised treatment/control).", "contact_id", [
    F("contact_id", pattern=r"^CNT-2026-\d{6}$", unique=True),
    F("campaign_id", rule="FK campaigns"),
    F("customer_id", rule="FK customers"),
    F("subscription_id", rule="FK subscriptions (primary)"),
    F("offer_id", required=False, rule="FK offers; null for CONTROL"),
    F("randomization_group", allowed=GROUPS, rule="a customer belongs to exactly one arm per campaign"),
    F("randomization_stratum", rule="plan|tenure band; randomisation done within stratum"),
    F("contact_date", "date", rule=">= prediction_date"),
    F("channel", allowed=["EMAIL", "SMS", "IN_APP"], required=False, rule="null for CONTROL"),
    F("contact_status", allowed=["DELIVERED", "BOUNCED", "HOLDOUT"]),
    F("contact_source", allowed=["AUTO_ELIGIBLE", "MANUAL_OVERRIDE"], rule="MANUAL_OVERRIDE bypasses the eligibility engine"),
    F("launched_by_role", allowed=["SYSTEM", "MARKETING_OPS", "SALES_OPS"]),
    F("eligibility_evaluation_id", required=False, rule="FK eligibility_evaluations used for the decision; null for CONTROL/override"),
    F("override_reason", required=False, rule="documented reason when MANUAL_OVERRIDE"),
], "event")

_t("churn_outcomes", "ChurnOutcome", "Churn label per scored customer for the 2026 prediction date / horizon.", "churn_outcome_id", [
    F("churn_outcome_id", pattern=r"^CHURN-CUS-\d{6}-2026$", unique=True, rule="CHURN-<customer-id>-2026"),
    F("customer_id", rule="FK customers"),
    F("subscription_id", rule="FK subscriptions (primary)"),
    F("prediction_date", "date"),
    F("horizon_end_date", "date", rule="exclusive; = prediction_date + horizon months"),
    F("churn_definition", allowed=["PRIMARY_SUBSCRIPTION_ENDED_IN_HORIZON"],
      rule="label = primary subscription ends (cancelled or terminated for non-payment) with prediction_date <= end < horizon_end"),
    F("churned_in_horizon", "bool", allowed=[0, 1], rule="DERIVED from subscription_events"),
    F("churn_event_id", required=False, rule="FK subscription_events"),
    F("churn_event_date", "date", required=False, rule="must be >= prediction_date for scored customers"),
    F("churn_type", allowed=["VOLUNTARY", "INVOLUNTARY"], required=False),
    F("days_to_churn", "int", required=False, unit="days", rule="DERIVED churn_event_date - prediction_date; >= 0"),
    F("churned_after_horizon", "bool", allowed=[0, 1], rule="ended after horizon_end but before data end (right-censoring info)"),
], "outcome")

_t("retention_outcomes", "RetentionOutcome", "Outcome of each campaign contact: response, cost and retention.", "retention_outcome_id", [
    F("retention_outcome_id", pattern=r"^RET-2026-\d{6}$", unique=True),
    F("contact_id", unique=True, rule="FK campaign_contacts (1:1)"),
    F("customer_id", rule="FK customers"),
    F("subscription_id", rule="FK subscriptions"),
    F("offer_id", required=False, rule="FK offers"),
    F("randomization_group", allowed=GROUPS),
    F("offer_viewed", "bool", allowed=[0, 1]),
    F("offer_accepted", "bool", allowed=[0, 1], rule="1 only if viewed"),
    F("accepted_at", "date", required=False, rule=">= contact_date"),
    F("offer_cost", "decimal", unit="USD", min=0, rule="DERIVED = sum of CREDIT events for (subscription, offer)"),
    F("credits_applied_count", "int", min=0, unit="count", rule="DERIVED"),
    F("retained_at_horizon_end", "bool", allowed=[0, 1], rule="DERIVED = no churn event before horizon_end"),
    F("revenue_collected_horizon", "decimal", unit="USD", min=0, rule="DERIVED sum PAYMENT in [contact_date, horizon_end)"),
    F("service_cost_horizon", "decimal", unit="USD", min=0, rule="DERIVED sum INVOICE service_cost in window"),
    F("net_margin_horizon", "decimal", unit="USD", rule="DERIVED = revenue_collected - service_cost (offer cost already netted)"),
    F("retention_attributed", "bool", allowed=[0, 1],
      rule="1 iff TREATMENT and accepted and retained; at most one attributed offer per customer"),
    F("attributed_offer_id", required=False, rule="= offer_id when retention_attributed"),
], "outcome")

_t("admin_audit_log", "AdminAuditLog", "Who changed what and when: price/rule/offer publication and manual eligibility overrides "
   "(system-administrator and marketing/sales-ops actors). Append-only.", "audit_id", [
    F("audit_id", pattern=r"^AUD-\d{6}$", unique=True, rule="numbered in chronological order"),
    F("event_time", "datetime"),
    F("actor_role", allowed=["SYSTEM_ADMIN", "MARKETING_OPS", "SALES_OPS"]),
    F("actor_id", pattern=r"^USR-\d{3}$"),
    F("action", allowed=["PRICE_VERSION_PUBLISHED", "RULE_ACTIVATED", "RULE_RETIRED", "OFFER_PUBLISHED", "ELIGIBILITY_OVERRIDE"]),
    F("entity_table", allowed=["plans", "eligibility_rules", "offers", "campaign_contacts"]),
    F("entity_id", rule="polymorphic reference: must exist in entity_table's primary key; event_time precedes the entity's effective date"),
    F("details", required=False),
], "event")


RELATIONSHIPS = [
    Rel("prospects", "converted_customer_id", "customers", "customer_id", "1:0..1", True, "lead that became a customer; legacy customers have none"),
    Rel("prospect_events", "prospect_id", "prospects", "prospect_id", "1:N", False, "funnel history"),
    Rel("prospect_events", "customer_id", "customers", "customer_id", "N:0..1", True, "CONVERTED event only"),
    Rel("subscriptions", "customer_id", "customers", "customer_id", "1:N", False, "customer has 1..2 subscriptions"),
    Rel("subscription_events", "subscription_id", "subscriptions", "subscription_id", "1:N", False, "lifecycle history"),
    Rel("subscription_events", "plan_id", "plans", "plan_id", "N:1", False),
    Rel("usage_snapshots", "subscription_id", "subscriptions", "subscription_id", "1:N", False, "one per active month"),
    Rel("billing_events", "subscription_id", "subscriptions", "subscription_id", "1:N", False),
    Rel("billing_events", "invoice_id", "billing_events", "billing_event_id", "1:N", True, "payments/credits point at their invoice"),
    Rel("billing_events", "offer_id", "offers", "offer_id", "N:1", True, "CREDIT events carry the offer for cost tracking"),
    Rel("support_cases", "customer_id", "customers", "customer_id", "1:N", False),
    Rel("support_cases", "subscription_id", "subscriptions", "subscription_id", "N:1", False),
    Rel("offer_eligibility_rules", "offer_id", "offers", "offer_id", "N:M bridge", False),
    Rel("offer_eligibility_rules", "rule_id", "eligibility_rules", "rule_id", "N:M bridge", False),
    Rel("eligibility_rules", "superseded_by_rule_id", "eligibility_rules", "rule_id", "1:0..1", True),
    Rel("eligibility_evaluations", "customer_id", "customers", "customer_id", "1:N", False),
    Rel("eligibility_evaluations", "subscription_id", "subscriptions", "subscription_id", "1:N", False),
    Rel("eligibility_evaluations", "offer_id", "offers", "offer_id", "N:1", False),
    Rel("campaign_contacts", "campaign_id", "campaigns", "campaign_id", "N:1", False),
    Rel("campaign_contacts", "customer_id", "customers", "customer_id", "1:N", False, "1:1 per campaign (violations = anomalies)"),
    Rel("campaign_contacts", "subscription_id", "subscriptions", "subscription_id", "1:N", False),
    Rel("campaign_contacts", "offer_id", "offers", "offer_id", "N:1", True, "null for CONTROL"),
    Rel("campaign_contacts", "eligibility_evaluation_id", "eligibility_evaluations", "evaluation_id", "N:0..1", True),
    Rel("churn_outcomes", "customer_id", "customers", "customer_id", "1:0..1", False, "one label per customer per year"),
    Rel("churn_outcomes", "subscription_id", "subscriptions", "subscription_id", "1:1", False),
    Rel("churn_outcomes", "churn_event_id", "subscription_events", "subscription_event_id", "N:0..1", True),
    Rel("retention_outcomes", "contact_id", "campaign_contacts", "contact_id", "1:1", False),
    Rel("retention_outcomes", "customer_id", "customers", "customer_id", "1:N", False),
    Rel("retention_outcomes", "subscription_id", "subscriptions", "subscription_id", "1:N", False),
    Rel("retention_outcomes", "offer_id", "offers", "offer_id", "N:1", True),
    Rel("retention_outcomes", "attributed_offer_id", "offers", "offer_id", "N:1", True),
]

GROUND_TRUTH_COLUMNS = [
    "anomaly_id", "issue_type", "entity_table", "entity_id", "customer_id", "related_entity_id",
    "violated_rules", "description", "expected_decision", "expected_detection_check",
]

ISSUE_TYPES = {
    "CHURN_LABEL_BEFORE_PREDICTION": ("T01", "EXCLUDE_ROW_FROM_TRAINING_AND_EVALUATION"),
    "INELIGIBLE_OFFER_SENT": ("B01", "BLOCK_OFFER_AND_EXCLUDE_FROM_EVALUATION"),
    "TREATMENT_CONTROL_LEAKAGE": ("X01", "EXCLUDE_CUSTOMER_FROM_EVALUATION"),
    "MULTI_OFFER_ATTRIBUTION": ("X03", "KEEP_SINGLE_ATTRIBUTION_EXCLUDE_DUPLICATE"),
}

SQL_TYPES = {"str": "TEXT", "int": "INTEGER", "decimal": "NUMERIC", "date": "TEXT", "datetime": "TEXT", "bool": "INTEGER"}


def table_order():
    return list(T.keys())


def ddl() -> str:
    """CREATE TABLE statements with PK/FK (SQLite/ANSI-friendly)."""
    out = ["PRAGMA foreign_keys = ON;", ""]
    rels = {}
    for r in RELATIONSHIPS:
        rels.setdefault(r.child, []).append(r)
    for name, t in T.items():
        cols = []
        for f in t.fields:
            c = f"  {f.name} {SQL_TYPES[f.type]}"
            if f.required:
                c += " NOT NULL"
            if f.allowed and f.type in ("str",):
                vals = ", ".join("'" + str(v) + "'" for v in f.allowed)
                c += f" CHECK ({f.name} IN ({vals}))" if not f.required else f" CHECK ({f.name} IN ({vals}))"
            cols.append(c)
        cols.append(f"  PRIMARY KEY ({', '.join(t.pk)})")
        for r in rels.get(name, []):
            cols.append(f"  FOREIGN KEY ({r.child_col}) REFERENCES {r.parent}({r.parent_col})")
        out.append(f"CREATE TABLE {name} (\n" + ",\n".join(cols) + "\n);\n")
    return "\n".join(out)
