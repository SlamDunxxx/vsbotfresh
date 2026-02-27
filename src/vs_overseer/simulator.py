from __future__ import annotations

import json
import os
from pathlib import Path
import random
import shutil
import subprocess
from typing import Callable

from .models import PolicyParameters, SimBatchMetrics, SimEpisodeResult


EpisodeCallback = Callable[[SimEpisodeResult], None]


class Simulator:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.sim_core_dir = project_root / "sim-core"
        self.sim_core_bin = self.sim_core_dir / "target" / "release" / "sim-core"
        self.local_cargo_home = project_root / ".cargo"
        self.local_rustup_home = project_root / ".rustup"
        local_cargo_bin = self.local_cargo_home / "bin" / "cargo"
        if local_cargo_bin.exists():
            self.cargo_bin = str(local_cargo_bin)
        else:
            self.cargo_bin = shutil.which("cargo") or ""

    def _rust_env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.local_cargo_home.exists():
            env["CARGO_HOME"] = str(self.local_cargo_home)
            cargo_bin = str(self.local_cargo_home / "bin")
            env["PATH"] = f"{cargo_bin}{os.pathsep}{env.get('PATH', '')}"
        if self.local_rustup_home.exists():
            env["RUSTUP_HOME"] = str(self.local_rustup_home)
        return env

    def _ensure_rust_binary(self) -> bool:
        if self.sim_core_bin.exists():
            return True
        if not self.cargo_bin:
            return False
        try:
            subprocess.run(
                [self.cargo_bin, "build", "--release"],
                cwd=str(self.sim_core_dir),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=self._rust_env(),
            )
        except Exception:
            return False
        return self.sim_core_bin.exists()

    def run_batch(
        self,
        *,
        parameters: PolicyParameters,
        episodes: int,
        seed: int,
        on_episode: EpisodeCallback | None = None,
    ) -> tuple[SimBatchMetrics, list[SimEpisodeResult], str]:
        episodes = max(1, int(episodes))
        if self._ensure_rust_binary():
            try:
                metrics, rows = self._run_rust_batch(
                    parameters=parameters,
                    episodes=episodes,
                    seed=seed,
                    on_episode=on_episode,
                )
                return metrics, rows, "rust"
            except Exception:
                pass

        metrics, rows = self._run_python_batch(
            parameters=parameters,
            episodes=episodes,
            seed=seed,
            on_episode=on_episode,
        )
        return metrics, rows, "python"

    def _run_rust_batch(
        self,
        *,
        parameters: PolicyParameters,
        episodes: int,
        seed: int,
        on_episode: EpisodeCallback | None,
    ) -> tuple[SimBatchMetrics, list[SimEpisodeResult]]:
        cmd = [
            str(self.sim_core_bin),
            "--episodes",
            str(episodes),
            "--seed",
            str(seed),
            "--aggression",
            str(parameters.aggression),
            "--greed",
            str(parameters.greed),
            "--safety",
            str(parameters.safety),
            "--focus",
            str(parameters.focus),
        ]
        completed = subprocess.run(
            cmd,
            cwd=str(self.sim_core_dir),
            check=True,
            capture_output=True,
            text=True,
            env=self._rust_env(),
        )
        payload = json.loads(completed.stdout)
        episodes_raw = payload.get("episodes", [])
        rows: list[SimEpisodeResult] = []
        for item in episodes_raw:
            row = SimEpisodeResult(
                unlock_rate=float(item.get("unlock_rate", 0.0)),
                objective_complete=bool(item.get("objective_complete", False)),
                stability=float(item.get("stability", 0.0)),
                elapsed_s=float(item.get("elapsed_s", 0.0)),
            )
            rows.append(row)
            if on_episode is not None:
                on_episode(row)

        agg = payload.get("aggregate", {})
        metrics = SimBatchMetrics(
            episodes=int(agg.get("episodes", len(rows))),
            objective_rate=float(agg.get("objective_rate", 0.0)),
            unlock_rate=float(agg.get("unlock_rate", 0.0)),
            stability_rate=float(agg.get("stability_rate", 0.0)),
            mean_elapsed_s=float(agg.get("mean_elapsed_s", 0.0)),
        )
        return metrics, rows

    def _run_python_batch(
        self,
        *,
        parameters: PolicyParameters,
        episodes: int,
        seed: int,
        on_episode: EpisodeCallback | None,
    ) -> tuple[SimBatchMetrics, list[SimEpisodeResult]]:
        rng = random.Random(seed)
        rows: list[SimEpisodeResult] = []
        for index in range(episodes):
            row = self._python_episode(parameters, rng=rng, index=index)
            rows.append(row)
            if on_episode is not None:
                on_episode(row)

        n = float(len(rows))
        objective_rate = sum(1.0 for x in rows if x.objective_complete) / n
        unlock_rate = sum(x.unlock_rate for x in rows) / n
        stability_rate = sum(x.stability for x in rows) / n
        mean_elapsed_s = sum(x.elapsed_s for x in rows) / n
        return (
            SimBatchMetrics(
                episodes=len(rows),
                objective_rate=float(objective_rate),
                unlock_rate=float(unlock_rate),
                stability_rate=float(stability_rate),
                mean_elapsed_s=float(mean_elapsed_s),
            ),
            rows,
        )

    @staticmethod
    def _python_episode(parameters: PolicyParameters, *, rng: random.Random, index: int) -> SimEpisodeResult:
        p = parameters.clamp()
        noise = rng.uniform(-0.08, 0.08)
        unlock_rate = (
            0.42 * p.aggression
            + 0.36 * p.greed
            + 0.20 * p.focus
            - 0.10 * max(0.0, p.safety - 0.72)
            + noise
        )
        unlock_rate = min(1.0, max(0.0, unlock_rate))

        stability = (
            0.62 * p.safety
            + 0.22 * p.focus
            - 0.12 * abs(p.aggression - p.greed)
            - 0.08 * max(0.0, p.aggression - 0.82)
            + rng.uniform(-0.06, 0.06)
        )
        stability = min(1.0, max(0.0, stability))

        objective_p = 0.18 + (0.58 * unlock_rate) + (0.24 * stability)
        objective_p = min(0.99, max(0.01, objective_p))
        objective_complete = rng.random() < objective_p

        elapsed_s = 1800.0 * (1.0 - (0.65 * unlock_rate))
        elapsed_s *= 1.0 + rng.uniform(-0.08, 0.05)
        elapsed_s = max(80.0, min(2000.0, elapsed_s))

        return SimEpisodeResult(
            unlock_rate=float(unlock_rate),
            objective_complete=bool(objective_complete),
            stability=float(stability),
            elapsed_s=float(elapsed_s),
        )
