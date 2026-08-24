"""``SimulationConfig`` - the reproducibility contract of the generator (PRD v1.1.1 11.2/11.6).

PRD 11.2 names this object as the entry point of the data pipeline:

    SimulationConfig(seed, duration, dt, regime schedule)
        -> ScenarioScheduler -> Twin.simulate_scenario -> SensorModel -> export

and NFR-4 requires that the same config and seed reproduce a byte-identical dataset. Two rules
follow, and both are enforced here rather than trusted to callers:

* **No global RNG.** ``numpy.random.seed`` is never touched. Every stochastic component of the
  generator asks for its own named substream via :meth:`SimulationConfig.rng`, so adding a
  component (or reordering two of them) cannot shift the numbers drawn by any other.
* **No hidden clock.** The row index is derived from ``start_timestamp``, ``dt_seconds`` and the
  duration, so the exported timestamps are a pure function of the config.

The warm-up window (``simulation.warmup_minutes``) is simulated but *not* exported: it is the
stretch in which the twin is driven onto the scheduled operating point before recording starts.
Its timestamps therefore sit *before* ``start_timestamp``, which keeps the exported dataset
starting exactly on the configured epoch.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, replace
from typing import Any, Final

import numpy as np
import pandas as pd

from src.config import SCENARIOS, Config, ConfigError, load_config

SECONDS_PER_MINUTE: Final = 60.0
MINUTES_PER_DAY: Final = 1440.0


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    """Seed, horizon and step size of one generator run (PRD 11.2)."""

    seed: int
    dt_seconds: float
    duration_minutes: float
    warmup_minutes: float
    start_timestamp: pd.Timestamp
    export_csv: bool = True
    export_parquet: bool = True
    export_config_sidecar: bool = True
    source: str = "<memory>"

    def __post_init__(self) -> None:
        if int(self.seed) != self.seed or int(self.seed) < 0:
            raise ConfigError(f"simulation.seed must be a non-negative integer, got {self.seed!r}")
        if float(self.dt_seconds) <= 0.0:
            raise ConfigError(f"simulation.dt_seconds must be > 0, got {self.dt_seconds!r}")
        if float(self.duration_minutes) <= 0.0:
            raise ConfigError(f"simulation duration must be > 0 min, got {self.duration_minutes!r}")
        if float(self.warmup_minutes) < 0.0:
            raise ConfigError(f"simulation.warmup_minutes must be >= 0, got {self.warmup_minutes!r}")

    # -- construction -------------------------------------------------------------------
    @classmethod
    def from_config(cls, scenarios: Config | None = None, **overrides: Any) -> SimulationConfig:
        """Build from the ``simulation:`` block of ``configs/scenarios.yaml``.

        ``overrides`` accepts the same names as the fields plus ``duration_days`` (the unit the
        config file uses), so a test or a demo can shorten the horizon without editing the config
        - the override is recorded by :meth:`describe` and lands in the PRD 11.6 sidecar.
        """
        cfg = scenarios if scenarios is not None else load_config(SCENARIOS)
        block = cfg["simulation"]
        duration_days = overrides.pop("duration_days", block["duration_days"])
        duration_minutes = overrides.pop(
            "duration_minutes", float(duration_days) * MINUTES_PER_DAY
        )
        instance = cls(
            seed=int(overrides.pop("seed", block["seed"])),
            dt_seconds=float(overrides.pop("dt_seconds", block["dt_seconds"])),
            duration_minutes=float(duration_minutes),
            warmup_minutes=float(overrides.pop("warmup_minutes", block["warmup_minutes"])),
            start_timestamp=pd.Timestamp(
                overrides.pop("start_timestamp", block["start_timestamp"])
            ),
            export_csv=bool(overrides.pop("export_csv", cfg.get_path("simulation.export.csv"))),
            export_parquet=bool(
                overrides.pop("export_parquet", cfg.get_path("simulation.export.parquet"))
            ),
            export_config_sidecar=bool(
                overrides.pop(
                    "export_config_sidecar", cfg.get_path("simulation.export.config_sidecar_json")
                )
            ),
            source=str(cfg.source),
        )
        if overrides:
            raise ConfigError(f"unknown SimulationConfig overrides: {sorted(overrides)}")
        return instance

    def replace(self, **changes: Any) -> SimulationConfig:
        """A copy with fields replaced (frozen dataclass; used by the what-if rollouts)."""
        if "duration_days" in changes:
            changes["duration_minutes"] = float(changes.pop("duration_days")) * MINUTES_PER_DAY
        return replace(self, **changes)

    # -- horizon ------------------------------------------------------------------------
    @property
    def steps_per_minute(self) -> float:
        return SECONDS_PER_MINUTE / float(self.dt_seconds)

    @property
    def warmup_steps(self) -> int:
        """Simulated-but-discarded steps that precede the exported window."""
        return int(round(float(self.warmup_minutes) * self.steps_per_minute))

    @property
    def export_steps(self) -> int:
        """Number of exported rows (PRD 11.2: 1-minute native sampling at dt = 60 s)."""
        return int(round(float(self.duration_minutes) * self.steps_per_minute))

    @property
    def total_steps(self) -> int:
        return self.warmup_steps + self.export_steps

    @property
    def duration_days(self) -> float:
        return float(self.duration_minutes) / MINUTES_PER_DAY

    @property
    def step(self) -> pd.Timedelta:
        return pd.Timedelta(seconds=float(self.dt_seconds))

    @property
    def timestamps(self) -> pd.DatetimeIndex:
        """Index of the exported rows, starting exactly on ``start_timestamp``."""
        return pd.date_range(
            start=pd.Timestamp(self.start_timestamp), periods=self.export_steps, freq=self.step
        )

    @property
    def run_timestamps(self) -> pd.DatetimeIndex:
        """Index of every simulated row: the warm-up window precedes ``start_timestamp``."""
        return pd.date_range(
            start=pd.Timestamp(self.start_timestamp) - self.warmup_steps * self.step,
            periods=self.total_steps,
            freq=self.step,
        )

    # -- reproducible randomness (NFR-4) ------------------------------------------------
    def substream_entropy(self, stream: str) -> tuple[int, int]:
        """Entropy of one named substream: ``(seed, crc32(stream))``.

        ``zlib.crc32`` is used deliberately instead of :func:`hash`, whose salt varies between
        interpreter runs - a hashed stream name would make the dataset irreproducible across
        processes, which is precisely the failure NFR-4 forbids.
        """
        if not stream:
            raise ValueError("an RNG substream must be named (NFR-4 traceability)")
        return int(self.seed), int(zlib.crc32(stream.encode("utf-8")))

    def rng(self, stream: str) -> np.random.Generator:
        """An independent :class:`numpy.random.Generator` for one named component."""
        return np.random.default_rng(self.substream_entropy(stream))

    # -- provenance ---------------------------------------------------------------------
    def describe(self) -> dict[str, Any]:
        """JSON-serializable record of the run, embedded in the PRD 11.6 sidecar."""
        return {
            "seed": int(self.seed),
            "dt_seconds": float(self.dt_seconds),
            "duration_minutes": float(self.duration_minutes),
            "duration_days": self.duration_days,
            "warmup_minutes": float(self.warmup_minutes),
            "start_timestamp": pd.Timestamp(self.start_timestamp).isoformat(),
            "export_steps": self.export_steps,
            "warmup_steps": self.warmup_steps,
            "export": {
                "csv": bool(self.export_csv),
                "parquet": bool(self.export_parquet),
                "config_sidecar_json": bool(self.export_config_sidecar),
            },
            "config_source": self.source,
        }


__all__ = ["MINUTES_PER_DAY", "SECONDS_PER_MINUTE", "SimulationConfig"]
