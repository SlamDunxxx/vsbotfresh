from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import random
from typing import Callable

from .config import AppConfig, ScoringConfig
from .models import PolicyParameters, SimBatchMetrics
from .scoring import weighted_score
from .simulator import Simulator


@dataclass(frozen=True)
class CandidateResult:
    candidate_id: str
    parameters: PolicyParameters
    metrics: SimBatchMetrics
    score: float
    backend: str


class PopulationTuner:
    def __init__(self, cfg: AppConfig, simulator: Simulator) -> None:
        self.cfg = cfg
        self.simulator = simulator

    def generate_population(self, base: PolicyParameters, *, generation_seed: int) -> list[tuple[str, PolicyParameters]]:
        rng = random.Random(generation_seed)
        size = max(2, int(self.cfg.automation.max_candidates_per_generation))
        population: list[tuple[str, PolicyParameters]] = [("baseline", base.clamp())]

        for i in range(1, size):
            sigma = 0.16 if i < (size // 2) else 0.09
            params = PolicyParameters(
                aggression=base.aggression + rng.gauss(0.0, sigma),
                greed=base.greed + rng.gauss(0.0, sigma),
                safety=base.safety + rng.gauss(0.0, sigma),
                focus=base.focus + rng.gauss(0.0, sigma),
            ).clamp()
            population.append((f"mutant-{i:02d}", params))

        return population

    def evaluate_population(
        self,
        population: list[tuple[str, PolicyParameters]],
        *,
        episodes: int,
        seed_base: int,
        max_workers: int | None = None,
        scoring: ScoringConfig | None = None,
        on_episode: Callable[[], None] | None = None,
    ) -> list[CandidateResult]:
        worker_limit = self.cfg.runtime.max_parallel_workers if max_workers is None else max_workers
        workers = min(len(population), max(1, int(worker_limit)))
        scoring_cfg = self.cfg.scoring if scoring is None else scoring

        def _run_one(idx: int, candidate_id: str, params: PolicyParameters) -> CandidateResult:
            metrics, rows, backend = self.simulator.run_batch(
                parameters=params,
                episodes=episodes,
                seed=seed_base + idx,
                on_episode=(lambda _ep: on_episode()) if on_episode is not None else None,
            )
            _ = rows
            score = weighted_score(metrics, scoring_cfg).total
            return CandidateResult(
                candidate_id=candidate_id,
                parameters=params,
                metrics=metrics,
                score=score,
                backend=backend,
            )

        futures = []
        results: list[CandidateResult] = []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for idx, (candidate_id, params) in enumerate(population):
                futures.append(ex.submit(_run_one, idx, candidate_id, params))
            for fut in as_completed(futures):
                results.append(fut.result())

        results.sort(key=lambda x: x.score, reverse=True)
        return results
