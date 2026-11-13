"""Credential detection for memories."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from episteme.errors import invalid

if TYPE_CHECKING:
    pass


SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"(?<![A-Za-z0-9_-])(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("GitHub token", re.compile(r"(?<![A-Za-z0-9_-])gh[pousr]_[A-Za-z0-9]{36}")),
    ("GitHub token", re.compile(r"(?<![A-Za-z0-9_-])github_pat_[A-Za-z0-9_]{22,}")),
    ("Anthropic API key", re.compile(r"(?<![A-Za-z0-9_-])sk-ant-[A-Za-z0-9_-]{20,}")),
    ("API key", re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9]{32,}")),
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
    return (
        password[0] in "<${[%*"
        or set(password) <= {"*", "x", "X", "."}
        or password.lower() in _PLACEHOLDER_PASSWORDS
    )


def _has_url_password(text: str) -> bool:
    return any(not _is_placeholder(m.group(1)) for m in _URL_CREDENTIALS.finditer(text))


def find_secrets(text: str) -> str | None:
    """Name of the first credential type found in ``text`` (never the value), else None."""
    for name, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            return name
    return "password in URL" if _has_url_password(text) else None


def _reject_secrets(field: str, value: Any) -> None:
    values = value if isinstance(value, list) else [value]
    for item in values:
        found = find_secrets(item) if isinstance(item, str) else None
        if found:
            raise invalid(
                f"{field} looks like a secret ({found}). "
                "Remove it and say where it is stored instead."
            )
