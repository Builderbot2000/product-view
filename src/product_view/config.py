"""config.yaml -- the defaults for every stage, overridden by command-line flags.

Precedence is flag > config.yaml > built-in default. Every flag that config
can supply defaults to None in argparse, so an unset flag is distinguishable
from one explicitly set to the built-in value.

Unknown keys are an error rather than ignored: a typo such as
`cohesion_flor: 0.5` would otherwise run silently with the default, and the
output would look like the setting had no effect.

Nothing secret belongs here. Credentials come from environment variables
only, which `load_dotenv` fills from a local `.env` file for development.
"""

from __future__ import annotations

import argparse
import copy
import os
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
        # Shared by translate, matching and the report: a review shorter
        # than this is never translated, so it must never be matched either.
        "min_chars": 20,
    },
    # The language model behind matching (llm.py). Keys for an API provider
    # come from the environment (PV_LLM_API_KEY, OPENAI_API_KEY), never from here.
    "llm": {
        "provider": "ollama",    # ollama (local) | openai
        "models": {"fast": "qwen3.5:9b", "strong": "qwen3.5:9b"},
        "base_url": None,        # None: the provider's default
        "max_workers": 1,        # parallel calls; 1 for a local GPU
        "temperature": 0.0,      # None: leave it out of the request
        "seed": 0,
        "timeout": 600,
        "retries": 5,
        "options": {},           # extra request fields, passed through as given
        "prices": {},            # model -> [input, output] USD per 1M tokens
        "budget_usd": None,      # stop before spending past this; None: no limit
    },
    # Embeddings for topic matching (matching/embed.py). The model is fixed by the
    # method; this only says where it runs.
    "embed": {
        "backend": "local",      # local (in this process, CPU) | ollama (the same model, served)
        "base_url": None,        # ollama: None follows OLLAMA_HOST, else 127.0.0.1:11434
    },
    # `pv report`: a periodic overview, not all of history (report-design.md
    # D15). The period ends on the newest review's day; the baseline is the
    # mean of that many equal periods before it.
    "report": {
        "period_days": 28,
        "baseline_periods": 6,
        "app_name": None,    # in page titles; None: the app id
        "overview": None,    # the overview page's title; None: "Product View @ <app_name>"
    },
    # Where `pv publish` puts the page. Credentials are not here: they come
    # from the environment (see publish/confluence.py).
    "confluence": {
        "space": None,       # space key, as in /wiki/spaces/<KEY>/
        "title": None,       # None: the HTML <title>, else the filename
        "parent_id": None,   # new pages go under this page ID
    },
}

# argparse dest -> dotted config key.
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
    "period_days": "report.period_days",
    "baseline_periods": "report.baseline_periods",
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
        # Mappings whose keys are data, not schema.
        if isinstance(base[key], dict) and dotted not in ("llm.models", "llm.options", "llm.prices"):
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
    lets `pv cycle` hand one namespace to every stage in turn.
    """
    for dest, key in FLAG_KEYS.items():
        if getattr(args, dest, None) is None:
            value = get(cfg, key)
            if dest == "lang":
                value = ",".join(value)
            setattr(args, dest, value)
    args.config = cfg


def load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal KEY=VALUE reader; existing environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)
