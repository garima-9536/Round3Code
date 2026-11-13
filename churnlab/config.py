"""Single configuration object shared by generator, validator and evaluator."""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field


@dataclass
class Config:
    # ---- reproducibility / scale -------------------------------------------------
    seed: int = 20261022
    n_customers: int = 20000

    # ---- timeline ------------------------------------------------------------------
    window_start: dt.date = dt.date(2025, 7, 1)      # first day of month 0
    n_months: int = 18                                # 2025-07 .. 2026-12
    prediction_date: dt.date = dt.date(2026, 7, 1)    # features use data strictly before this
    horizon_months: int = 3                           # churn horizon = [prediction_date, +3 calendar months)
    price_increase_date: dt.date = dt.date(2026, 3, 1)  # STANDARD price rise (behavioural shock)

    # ---- population ----------------------------------------------------------------
    new_customer_share: float = 0.22                  # customers acquired inside the window
    addon_share: float = 0.08                         # customers with a second (add-on) subscription
    prospect_conversion_rate: float = 0.30            # target share of closed leads that convert (lost leads are sized from it)

    # ---- churn mechanics (intercepts calibrated by scripts/calibrate.py) --------------
    intercept_pre: float = -6.94                      # months before the prediction date
    intercept_wave: float = -4.43                     # months inside the horizon (churn wave)
    intercept_post: float = -5.97                     # months after the horizon
    dunning_retry_success: float = 0.60               # per retry; P(terminate | first failure) = 0.4**2
    wave_offer_effect_months: int = 4                 # offer shifts hazard for this many months

    # ---- campaign ------------------------------------------------------------------
    campaign_id: str = "CMP-2026-RETENTION-Q3"
    treat_share: float = 0.70
    margin_cap_pct: int = 60                          # offer cost <= 60% of 3 months of margin
    margin_horizon_months: int = 3
    recent_failure_window_days: int = 45
    min_tenure_months: int = 3
    loyalty_tenure_months: int = 12

    # ---- optional extensions (defaults reproduce the original single-campaign dataset exactly) -------------
    n_campaigns: int = 1                              # 1 = one campaign; 2 = one independently randomised campaign per segment
    expose_override_flag: bool = True                 # False = manual overrides look like ordinary automatic contacts

    # ---- anomalies -----------------------------------------------------------------
    anomaly_rate: float = 0.0025                      # per issue type, share of customers (min 3)

    # ---- helpers ---------------------------------------------------------------------
    @property
    def data_end(self) -> dt.date:
        return month_start(self, self.n_months) - dt.timedelta(days=1)

    @property
    def horizon_end(self) -> dt.date:
        return add_months(self.prediction_date, self.horizon_months)

    @property
    def pred_month_idx(self) -> int:
        return (self.prediction_date.year - self.window_start.year) * 12 + (
            self.prediction_date.month - self.window_start.month
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, dt.date):
                d[k] = v.isoformat()
        return d


def add_months(d: dt.date, n: int) -> dt.date:
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    return dt.date(y, m, 1)


def month_start(cfg: Config, m: int) -> dt.date:
    return add_months(cfg.window_start, m)


def scaled_config(scale: str, **overrides) -> Config:
    """starter and full datasets share the same generator; only scale differs."""
    n = {"starter": 1500, "full": 20000}[scale] if scale in ("starter", "full") else int(scale)
    return Config(n_customers=n, **overrides)
