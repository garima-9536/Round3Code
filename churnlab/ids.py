"""Deterministic, zero-padded, immutable identifiers (see README: ID conventions)."""
from __future__ import annotations

import numpy as np

YEAR = 2026


def cus(n):
    return f"CUS-{int(n):06d}"


def cus_arr(idx0: np.ndarray) -> np.ndarray:
    """idx0 = 0-based customer index -> CUS-000001 ..."""
    return np.array([f"CUS-{i + 1:06d}" for i in idx0], dtype=object)


def sub(customer_id: str, k: int) -> str:
    return f"SUB-{customer_id}-{k:02d}"


def snap(subscription_id: str, year: int, month: int) -> str:
    return f"SNAP-{subscription_id}-{year}-{month:02d}"


def offer(n: int) -> str:
    return f"OFF-{YEAR}-{n:06d}"


def churn(customer_id: str) -> str:
    return f"CHURN-{customer_id}-{YEAR}"


def contact(n: int) -> str:
    return f"CNT-{YEAR}-{n:06d}"


def retention(n: int) -> str:
    return f"RET-{YEAR}-{n:06d}"


def rule(n: int) -> str:
    return f"ELR-{n:06d}"


def evaluation(n: int) -> str:
    return f"EVAL-{YEAR}-{n:06d}"


def agent(n: int) -> str:
    return f"AGT-{n:03d}"
