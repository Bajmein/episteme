"""Credential detection for memories."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any

from episteme.errors import invalid

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"(?<![A-Za-z0-9_-])(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("GitHub token", re.compile(r"(?<![A-Za-z0-9_-])gh[pousr]_[A-Za-z0-9]{36}")),
    ("GitHub token", re.compile(r"(?<![A-Za-z0-9_-])github_pat_[A-Za-z0-9_]{22,}")),
    ("Anthropic API key", re.compile(r"(?<![A-Za-z0-9_-])sk-ant-[A-Za-z0-9_-]{20,}")),
    ("API key", re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}")),
    (
        "Bearer token",
        re.compile(r"(?<![A-Za-z0-9_-])Bearer\s+[A-Za-z0-9._~+/-]{20,}", re.IGNORECASE),
    ),
    ("Stripe live key", re.compile(r"(?<![A-Za-z0-9_-])sk_live_[A-Za-z0-9]{16,}")),
    ("npm token", re.compile(r"(?<![A-Za-z0-9_-])npm_[A-Za-z0-9]{36}")),
    ("Hugging Face token", re.compile(r"(?<![A-Za-z0-9_-])hf_[A-Za-z0-9]{30,}")),
    ("Slack token", re.compile(r"(?<![A-Za-z0-9_-])xox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"(?<![A-Za-z0-9_-])AIza[A-Za-z0-9_-]{35}")),
    (
        "JWT",
        re.compile(
            r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{7,}\.eyJ[A-Za-z0-9_-]{7,}\.[A-Za-z0-9_-]{10,}"
        ),
    ),
)
_URL_CREDENTIALS = re.compile(r"://[^\s/:@]+:([^\s/@]{6,})@")
# The key may be quoted (JSON) and end in ``key``/``access_key`` (``AWS_SECRET_ACCESS_KEY``);
# ``password_hash`` and the like do not match. The value must still pass _looks_like_value.
_ASSIGNED_SECRET = re.compile(
    r"(?:password|passwd|secret|token|api[_-]?key)(?:[_-]?(?:access[_-]?)?key)?[\"'`]?"
    r"\s*[:=]\s*[\"'`]?([^\s\"'`,;]{8,})",
    re.IGNORECASE,
)
_ENV_REFERENCE = re.compile(r"\$(?:[A-Z_][A-Z0-9_]*|\{[A-Z_][A-Z0-9_]*\})")
_PLACEHOLDER_PASSWORDS = {
    "pass",
    "password",
    "passwd",
    "clave",
    "secret",
    "changeme",
    "example",
    "redacted",
    "your_password",
    "your-password",
    "yourpassword",
    "contraseña",
    "tu_clave",
}


def _is_placeholder(password: str) -> bool:
    """True for an example value: ``<x>``, ``$NAME``, ``${NAME}``, ``***``, ``changeme``..."""
    if password[0] == "$":
        return _ENV_REFERENCE.fullmatch(password) is not None
    return (
        password[0] in "<{[%*"
        or set(password) <= {"*", "x", "X", "."}
        or password.lower() in _PLACEHOLDER_PASSWORDS
    )


def _normalize(text: str) -> str:
    """NFKC text without format characters (zero-width and similar), so they cannot hide a key."""
    flat = unicodedata.normalize("NFKC", text)
    return "".join(c for c in flat if unicodedata.category(c) != "Cf")


def _looks_like_value(value: str) -> bool:
    """True when an assigned value is not code or a reference: a digit and no brackets."""
    return any(c.isdigit() for c in value) and not set(value) & set("()[]{}<>")


def _real_passwords(pattern: re.Pattern[str], text: str, strict: bool = False) -> list[str]:
    found = [m.group(1) for m in pattern.finditer(text)]
    return [v for v in found if not _is_placeholder(v) and (_looks_like_value(v) or not strict)]


def _credential_hits(text: str) -> list[tuple[str, str]]:
    """``(type, matched text)`` for every credential in ``text``, in pattern order."""
    text = _normalize(text)
    hits = [(name, m.group(0)) for name, p in SECRET_PATTERNS for m in p.finditer(text)]
    hits += [("credential assignment", v) for v in _real_passwords(_ASSIGNED_SECRET, text, True)]
    hits += [("password in URL", v) for v in _real_passwords(_URL_CREDENTIALS, text)]
    return hits


def find_secrets(text: str) -> str | None:
    """Name of the first credential type found in ``text`` (never the value), else None.

    Best effort: it covers common formats, not every provider.
    """
    hits = _credential_hits(text)
    return hits[0][0] if hits else None


def has_new_secrets(new: str, old: str) -> bool:
    """True when ``new`` holds a credential that ``old`` does not (a replaced one counts)."""
    added = Counter(v for _, v in _credential_hits(new)) - Counter(
        v for _, v in _credential_hits(old)
    )
    return bool(added)


def _strings_in(value: Any) -> list[str]:
    """Every string in ``value``, going into lists and dicts (keys included)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (*_strings_in(k), *_strings_in(v))]
    if isinstance(value, (list, tuple, set)):
        return [s for item in value for s in _strings_in(item)]
    return []


def _reject_secrets(field: str, value: Any) -> None:
    for item in _strings_in(value):
        found = find_secrets(item)
        if found:
            raise invalid(
                f"{field} looks like a secret ({found}). "
                "Remove it and say where it is stored instead."
            )
