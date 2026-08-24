"""YAML configuration loading (PRD v1.1.1 Sections 11.6, 23).

All numeric parameters of the twin, the data generator, the ML layer and the optimizer live
in ``configs/*.yaml``; this module is the only place that reads them. Configs are loaded
once, cached, and exposed as read-only mappings with dotted-path access, so a caller can
never mutate a shared config in place (a silent-drift failure mode that would break the
reproducibility guarantee of NFR-4).

The plain-dict form returned by :func:`as_plain_dict` is what gets serialized next to every
generated dataset as the JSON sidecar required by PRD 11.6.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Final

import yaml

from src.paths import CONFIG_DIR, config_path

# Canonical config names (PRD Section 23 lists exactly these five files).
KILN: Final = "kiln_dynamics"
MILL: Final = "mill_dynamics"
ML: Final = "ml"
OPTIMIZATION: Final = "optimization"
SCENARIOS: Final = "scenarios"

CONFIG_NAMES: Final[tuple[str, ...]] = (KILN, MILL, ML, OPTIMIZATION, SCENARIOS)

# The presentation layer's own config (PRD Sections 17-19, 29). Deliberately NOT a member of
# CONFIG_NAMES: it holds no process limit, engineering range or model threshold, so it must not
# enter the PRD 11.6 dataset sidecars or the reproducibility signature of a run. It exists so
# that no alarm band, animation constant or downsampling budget is a literal inside a panel
# (NFR-6, AC-12).
DASHBOARD: Final = "dashboard"

_MISSING = object()


class ConfigError(KeyError):
    """Raised when a required configuration key is absent or has the wrong shape."""


class Config(Mapping[str, Any]):
    """Immutable, dotted-path view over a parsed YAML mapping."""

    __slots__ = ("_data", "_source")

    def __init__(self, data: Mapping[str, Any], source: str | Path = "<memory>") -> None:
        self._data: dict[str, Any] = {key: _wrap(value, source) for key, value in data.items()}
        self._source = str(source)

    # -- Mapping protocol ---------------------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        try:
            return self._data[key]
        except KeyError as exc:  # pragma: no cover - message clarity only
            raise ConfigError(f"{key!r} not found in {self._source}") from exc

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Config({self._source!r}, keys={sorted(self._data)})"

    # -- Convenience --------------------------------------------------------------------
    def __getattr__(self, key: str) -> Any:
        """Attribute access for readability: ``cfg.reference.kiln_feed_rate_tph``."""
        if key.startswith("_"):  # never shadow the slots / dunder lookups
            raise AttributeError(key)
        try:
            return self._data[key]
        except KeyError as exc:
            raise AttributeError(
                f"{key!r} not found in {self._source}; available: {sorted(self._data)}"
            ) from exc

    @property
    def source(self) -> str:
        """Path (or ``<memory>``) this config was parsed from."""
        return self._source

    def get_path(self, dotted: str, default: Any = _MISSING) -> Any:
        """Return the value at ``"a.b.c"``.

        Raises :class:`ConfigError` when the path is missing and no ``default`` is given -
        configs are contracts, so a typo must fail loudly rather than silently fall back
        to a magic number (PRD closing note: never silently invent a different number).
        """
        node: Any = self
        for part in dotted.split("."):
            if isinstance(node, Mapping) and part in node:
                node = node[part]
            elif default is not _MISSING:
                return default
            else:
                raise ConfigError(f"{dotted!r} not found in {self._source}")
        return node

    def require(self, *dotted: str) -> None:
        """Assert that every dotted path exists (used at module import / load time)."""
        missing = [path for path in dotted if self.get_path(path, None) is None]
        if missing:
            raise ConfigError(f"missing required keys in {self._source}: {missing}")

    def to_dict(self) -> dict[str, Any]:
        """Deep copy as plain Python containers (JSON-serializable)."""
        return {key: _unwrap(value) for key, value in self._data.items()}


def _wrap(value: Any, source: str | Path) -> Any:
    if isinstance(value, Mapping):
        return Config(value, source)
    if isinstance(value, list):
        return tuple(_wrap(item, source) for item in value)
    return value


def _unwrap(value: Any) -> Any:
    if isinstance(value, Config):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {key: _unwrap(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_unwrap(item) for item in value]
    return value


_CACHE: dict[Path, Config] = {}


def load_config(name: str, config_dir: Path | None = None, *, use_cache: bool = True) -> Config:
    """Load ``configs/<name>.yaml`` (cached by resolved path)."""
    path = (config_dir / f"{name}.yaml") if config_dir is not None else config_path(name)
    path = path.resolve()
    if use_cache and path in _CACHE:
        return _CACHE[path]
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, Mapping):
        raise ConfigError(f"config {path} must parse to a mapping, got {type(raw).__name__}")
    config = Config(raw, path)
    if use_cache:
        _CACHE[path] = config
    return config


def load_all(config_dir: Path | None = None, *, use_cache: bool = True) -> dict[str, Config]:
    """Load all five PRD Section 23 configs, keyed by canonical name."""
    return {name: load_config(name, config_dir, use_cache=use_cache) for name in CONFIG_NAMES}


def clear_cache() -> None:
    """Drop the config cache (tests that write temporary configs rely on this)."""
    _CACHE.clear()


def as_plain_dict(configs: Mapping[str, Config] | Config) -> dict[str, Any]:
    """Convert one config or a mapping of configs into JSON-serializable dicts."""
    if isinstance(configs, Config):
        return configs.to_dict()
    return {name: cfg.to_dict() for name, cfg in configs.items()}


def write_config_sidecar(target: Path, configs: Mapping[str, Config] | Config) -> Path:
    """Write the JSON config sidecar required alongside every dataset (PRD 11.6)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = as_plain_dict(configs)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=str)
    return target


def config_dir() -> Path:
    """Directory the configs are read from (PRD Section 23 ``configs/``)."""
    return CONFIG_DIR


__all__ = [
    "Config",
    "ConfigError",
    "CONFIG_NAMES",
    "DASHBOARD",
    "KILN",
    "MILL",
    "ML",
    "OPTIMIZATION",
    "SCENARIOS",
    "load_config",
    "load_all",
    "clear_cache",
    "as_plain_dict",
    "write_config_sidecar",
    "config_dir",
]
