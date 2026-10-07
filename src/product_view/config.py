"""config.yaml -- the defaults for every stage, overridden by command-line flags.

Precedence is flag > config.yaml > built-in default. Every flag that config
can supply defaults to None in argparse, so an unset flag is distinguishable
from one explicitly set to the built-in value.

Unknown keys are an error rather than ignored: a typo such as
`cohesion_flor: 0.5` would otherwise run silently with the default, and the
output would look like the setting had no effect.

Nothing secret belongs here. Confluence credentials come from environment
variables only (see publish/confluence.py).
"""

from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path("config.yaml")

# The built-in defaults. config.yaml mirrors this shape; any key it omits
# falls back to the value here.
DEFAULTS: dict[str, Any] = {
    "app": {
        "id": "com.rbc.mobile.android",
        "country": "ca",
    },
    "data_dir": "data",
    "fetch": {
        # Play partitions reviews by locale and each partition holds different
        # reviews; fetching only `en` lost 13% of the corpus. `langs` is used
        # only when all_langs is false.
        "all_langs": True,
        "langs": ["en"],
        "max_reviews": 1000,
        "page_size": 200,
        "sleep_seconds": 1.0,
    },
    "corpus": {
        # Shared by translate, embed and cluster: a review shorter than this
        # is never translated, so it must never enter a stream either.
        "min_chars": 20,
    },
    "cluster": {
        "polarities": ["negative", "positive"],   # what `pv run` clusters
        "algorithm": "leiden",
        "granularity": "balanced",   # broad | balanced | fine | "MIN-MAX"
        # Per stream: the positive corpus is about a third the size of the
        # negative one, so the same floor would demand a rarer theme.
        "min_cluster_size": {"negative": 25, "positive": 15},
        "cohesion_floor": 0.35,
        # Cosine at which adjacent segments of one review join into a single
        # complaint unit. Lower merges more (fewer, longer units).
        "merge_threshold": 0.45,
        "knn_k": 15,
        "seed": 42,
        "tau_days": 365.0,
        "momentum_window_days": 365.0,
        "native_override": None,
    },
    # `pv report`: a periodic overview, not all of history (report-design.md
    # D15). The period ends on the newest review's day; the baseline is the
    # mean of that many equal periods before it.
    "report": {
        "period_days": 28,
        "baseline_periods": 6,
        "curation": "curation.yaml",
        "app_name": None,    # in page titles; None: the app id
    },
    # Where `pv publish` puts the page. Credentials are not here: they come
    # from the environment (see publish/confluence.py).
    "confluence": {
        "space": None,       # space key, as in /wiki/spaces/<KEY>/
        "title": None,       # None: the HTML <title>, else the filename
        "parent_id": None,   # new pages go under this page ID
    },
}

# argparse dest -> dotted config key. `min_cluster_size` is absent on purpose:
# it is per-polarity, so it is resolved when the polarity is known.
FLAG_KEYS: dict[str, str] = {
    "app_id": "app.id",
    "country": "app.country",
    "data_dir": "data_dir",
    "lang": "fetch.langs",
    "all_langs": "fetch.all_langs",
    "max_reviews": "fetch.max_reviews",
    "page_size": "fetch.page_size",
    "sleep": "fetch.sleep_seconds",
    "min_chars": "corpus.min_chars",
    "algorithm": "cluster.algorithm",
    "granularity": "cluster.granularity",
    "cohesion_floor": "cluster.cohesion_floor",
    "merge_threshold": "cluster.merge_threshold",
    "knn_k": "cluster.knn_k",
    "seed": "cluster.seed",
    "tau_days": "cluster.tau_days",
    "momentum_window": "cluster.momentum_window_days",
    "native_override": "cluster.native_override",
    "period_days": "report.period_days",
    "baseline_periods": "report.baseline_periods",
    "curation": "report.curation",
    "app_name": "report.app_name",
    "space": "confluence.space",
    "title": "confluence.title",
    "parent_id": "confluence.parent_id",
}


class ConfigError(ValueError):
    pass


def load(path: str | Path | None = None) -> dict[str, Any]:
    """Built-in defaults with config.yaml merged over them.

    With no explicit path, a missing ./config.yaml means "use the defaults".
    An explicit path that does not exist is an error, not a silent fallback.
    """
    explicit = path is not None
    path = Path(path) if explicit else DEFAULT_PATH
    cfg = copy.deepcopy(DEFAULTS)
    if not path.exists():
        if explicit:
            raise ConfigError(f"config file not found: {path}")
        return cfg

    import yaml

    with path.open(encoding="utf-8") as fh:
        user = yaml.safe_load(fh) or {}
    if not isinstance(user, dict):
        raise ConfigError(f"{path}: top level must be a mapping")
    _merge(cfg, user, prefix="", source=path)
    return cfg


def _merge(base: dict, user: dict, prefix: str, source: Path) -> None:
    for key, value in user.items():
        dotted = f"{prefix}{key}"
        if key not in base:
            known = ", ".join(f"{prefix}{k}" for k in base)
            raise ConfigError(f"{source}: unknown key {dotted!r} (expected one of: {known})")
        # min_cluster_size is the one mapping whose keys are data, not schema.
        if isinstance(base[key], dict) and dotted != "cluster.min_cluster_size":
            if not isinstance(value, dict):
                raise ConfigError(f"{source}: {dotted!r} must be a mapping")
            _merge(base[key], value, prefix=f"{dotted}.", source=source)
        else:
            base[key] = value


def get(cfg: dict[str, Any], dotted: str) -> Any:
    node: Any = cfg
    for part in dotted.split("."):
        node = node[part]
    return node


def apply(args: argparse.Namespace, cfg: dict[str, Any]) -> None:
    """Fill every flag left unset on the command line from the config.

    Sets attributes a subcommand's parser never declared too, which is what
    lets `pv run` hand one namespace to every stage in turn.
    """
    for dest, key in FLAG_KEYS.items():
        if getattr(args, dest, None) is None:
            value = get(cfg, key)
            if dest == "lang":
                value = ",".join(value)
            setattr(args, dest, value)
    args.config = cfg


def min_cluster_size(cfg: dict[str, Any], polarity: str) -> int:
    sizes = get(cfg, "cluster.min_cluster_size")
    if isinstance(sizes, int):
        return sizes
    try:
        return int(sizes[polarity])
    except KeyError:
        raise ConfigError(
            f"cluster.min_cluster_size has no entry for {polarity!r}"
        ) from None
