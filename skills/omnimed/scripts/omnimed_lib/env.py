# Configuration loading for the OmniMed skill.
#
# Keys never live inside the skill folder: it is meant to be published, and a
# key committed there would be a key leaked. They are read from the process
# environment first, then from env files outside the repo:
#
#   OMNIMED_ENV_FILE        one or more paths, separated by os.pathsep (":")
#   ~/.config/omnimed/*.env every *.env file there, in name order
#
# A variable already set in the environment always wins, so a CI job or a
# one-off `GEMINI_API_KEY=… omnimed.py ask …` overrides the files.
#
# Values are never printed. `describe()` reports which keys are present as
# booleans only.

import os
from pathlib import Path

CONFIG_DIR = Path(os.path.expanduser("~/.config/omnimed"))

PROVIDER_KEYS = {
    "anthropic":  "ANTHROPIC_API_KEY",
    "openai":     "OPENAI_API_KEY",
    "google":     "GEMINI_API_KEY",
    "groq":       "GROQ_API_KEY",
    "deepseek":   "DEEPSEEK_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "cohere":     "COHERE_API_KEY",
}

_loaded_from: list[str] = []


def _parse(path: Path) -> dict:
    out = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        elif " #" in val:
            val = val.split(" #", 1)[0].rstrip()
        if key:
            out[key] = val
    return out


def _candidate_files() -> list[Path]:
    explicit = os.getenv("OMNIMED_ENV_FILE")
    if explicit:
        return [Path(os.path.expanduser(p)) for p in explicit.split(os.pathsep) if p]
    if CONFIG_DIR.is_dir():
        return sorted(p for p in CONFIG_DIR.glob("*.env") if p.is_file())
    return []


def load() -> list[str]:
    """Populate os.environ from the env files. Safe to call more than once."""
    if _loaded_from:
        return _loaded_from
    for path in _candidate_files():
        values = _parse(path)
        if not values:
            continue
        for k, v in values.items():
            if v and not os.environ.get(k):
                os.environ[k] = v
        _loaded_from.append(str(path))
    return _loaded_from


def has_key(provider: str) -> bool:
    name = PROVIDER_KEYS.get(provider)
    return bool(name and os.getenv(name))


def get_key(provider: str) -> str | None:
    name = PROVIDER_KEYS.get(provider)
    return os.getenv(name) if name else None


def describe() -> dict:
    return {
        "env_files": list(_loaded_from),
        "keys_present": {p: has_key(p) for p in PROVIDER_KEYS},
        "ncbi_email_set": bool(os.getenv("NCBI_EMAIL")),
        "ncbi_api_key_set": bool(os.getenv("NCBI_API_KEY")),
    }
