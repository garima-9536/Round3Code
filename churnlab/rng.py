"""Named, independent random streams derived from one seed (stable under code edits elsewhere)."""
from __future__ import annotations

import zlib

import numpy as np


class Streams:
    def __init__(self, seed: int):
        self.seed = seed

    def get(self, name: str) -> np.random.Generator:
        ss = np.random.SeedSequence([self.seed, zlib.crc32(name.encode("utf-8"))])
        return np.random.default_rng(ss)
