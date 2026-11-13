"""Bisection of the three period intercepts so churn lands in the documented 5-20% band.

Targets (documented in README): pre-cutoff cumulative churn ~5%, horizon churn ~10% of active customers
(the 'churn wave' used for the offer experiment), post-horizon ~2.5%. Result is hard-coded into
churnlab.config.Config; this script only exists to make that choice reproducible.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from churnlab.config import Config
from churnlab.generate.master import build_population
from churnlab.generate.simulate import calibration_stats, simulate_history
from churnlab.rng import Streams


def bisect(f, lo, hi, target, n=14):
    for _ in range(n):
        mid = (lo + hi) / 2
        if f(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def main():
    cfg = Config()
    streams = Streams(cfg.seed)
    P = build_population(cfg, streams)
    H = simulate_history(cfg, P, streams)
    a = [cfg.intercept_pre, cfg.intercept_wave, cfg.intercept_post]
    a[0] = bisect(lambda x: calibration_stats(cfg, P, H, (x, a[1], a[2]))["pre_rate"], -9, -4, 0.050)
    a[1] = bisect(lambda x: calibration_stats(cfg, P, H, (a[0], x, a[2]))["wave_rate"], -8, -1, 0.100)
    a[2] = bisect(lambda x: calibration_stats(cfg, P, H, (a[0], a[1], x))["post_rate"], -9, -3, 0.025)
    print("intercepts (pre, wave, post):", [round(x, 2) for x in a])
    print(calibration_stats(cfg, P, H, tuple(a)))


if __name__ == "__main__":
    main()
