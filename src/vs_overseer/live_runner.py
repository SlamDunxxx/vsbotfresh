from __future__ import annotations

import random

from .config import AppConfig
from .memory_backend import MemoryBackend
from .models import LiveBatchMetrics, PolicyParameters


class LiveRunner:
    """
    Memory-first live runner interface.

    v1 behavior:
    - If memory backend is unavailable, returns blocked status and allows the orchestrator
      to continue simulation-only optimization without stopping.
    - If available, emits deterministic pseudo-live metrics to drive unattended gating.
    """

    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.memory = MemoryBackend(cfg)

    def canary(self, *, parameters: PolicyParameters, runs: int, seed: int) -> LiveBatchMetrics:
        probe = self.memory.probe()
        if not probe.ok or probe.signal is None:
            return LiveBatchMetrics(
                runs=0,
                objective_rate=0.0,
                stability_rate=0.0,
                blocked=True,
                reason=probe.reason,
            )

        signal = probe.signal
        rng = random.Random(seed)
        n = max(1, int(runs))
        objective_hits = 0
        stability_sum = 0.0
        for _ in range(n):
            confidence_scale = 0.5 + (0.5 * signal.confidence)
            base_obj = (
                0.10
                + (0.45 * parameters.aggression)
                + (0.20 * parameters.focus)
                + (0.25 * signal.objective_hint)
            )
            base_stab = (
                0.15
                + (0.55 * parameters.safety)
                + (0.20 * signal.stability_hint)
                - (0.08 * abs(parameters.aggression - parameters.greed))
            )
            objective_p = min(0.98, max(0.02, (base_obj * confidence_scale) + rng.uniform(-0.05, 0.05)))
            stability = min(1.0, max(0.0, (base_stab * confidence_scale) + rng.uniform(-0.06, 0.06)))
            objective_hits += 1 if rng.random() < objective_p else 0
            stability_sum += stability

        return LiveBatchMetrics(
            runs=n,
            objective_rate=objective_hits / float(n),
            stability_rate=stability_sum / float(n),
            blocked=False,
            reason=f"ok:{signal.source}",
        )
