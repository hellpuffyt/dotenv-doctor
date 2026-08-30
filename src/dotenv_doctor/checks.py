"""The checks that turn a parsed ``.env`` into actionable findings.

Every check is a pure function of already-parsed data, so the whole rule set
is testable without touching a filesystem.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum

from .parser import ParsedFile


class Severity(str, Enum):
    """How much a finding should hurt."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    @property
    def rank(self) -> int:
        return {"error": 3, "warning": 2, "info": 1}[self.value]


@dataclass(frozen=True)
class Finding:
    """One thing worth telling the user about."""

    code: str
    severity: Severity
    key: str | None
    message: str
    line_number: int | None = None

    def location(self) -> str:
        """Where the finding is, for display.

        A missing key has no line to point at, so it renders as a dash — the
        key itself is printed separately and must not be duplicated here.
        """
        if self.line_number is None:
            return "-"
        return f"line {self.line_number}"


# Values that mean "you forgot to fill this in". Compared case-insensitively
# against the whole value, so a real secret containing "changeme" is not
# flagged.
PLACEHOLDERS = frozenset(
    {
        "",
        "changeme",
        "change_me",
        "change-me",
        "todo",
        "tbd",
        "fixme",
        "xxx",
        "xxxx",
        "your_api_key",
        "your-api-key",
        "yourapikey",
        "placeholder",
        "replace_me",
        "replace-me",
        "secret",
        "password",
        "none",
        "null",
        "undefined",
        "<your-key>",
        "<key>",
        "...",
        "example",
        "test",
        "foo",
        "bar",
    }
)

# Substrings that mark a key as carrying a credential.
SECRET_HINTS = (
    "secret",
    "password",
    "passwd",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "privatekey",
    "credential",
    "auth",
    "access_key",
    "client_secret",
    "signing",
    "salt",
)

# Well-known live-credential shapes. Finding one of these in a committed
# example file is an emergency, not a style nit.
LIVE_CREDENTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws-access-key-id", re.compile(r"^(AKIA|ASIA)[0-9A-Z]{16}$")),
    ("github-token", re.compile(r"^gh[pousr]_[A-Za-z0-9]{36,}$")),
    ("slack-token", re.compile(r"^xox[baprs]-[A-Za-z0-9-]{10,}$")),
    ("stripe-secret-key", re.compile(r"^sk_(live|test)_[A-Za-z0-9]{16,}$")),
    ("openai-key", re.compile(r"^sk-[A-Za-z0-9_-]{20,}$")),
    ("anthropic-key", re.compile(r"^sk-ant-[A-Za-z0-9_-]{20,}$")),
    ("google-api-key", re.compile(r"^AIza[0-9A-Za-z_-]{35}$")),
    ("private-key-block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("json-web-token", re.compile(r"^eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.")),
)


def shannon_entropy(value: str) -> float:
    """Bits of entropy per character.

    Used only as a weak signal alongside the key name; entropy alone produces
    far too many false positives on things like URLs and base64 config blobs.
    """
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    return -sum(
        (count / length) * math.log2(count / length) for count in counts.values()
    )


def is_placeholder(value: str) -> bool:
    """True when a value is obviously an unfilled template."""
    return value.strip().lower() in PLACEHOLDERS


def looks_secret(key: str) -> bool:
    """True when the key name says it holds a credential."""
    lowered = key.lower()
    return any(hint in lowered for hint in SECRET_HINTS)


def detect_live_credential(value: str) -> str | None:
    """Return the name of a matched live-credential shape, if any."""
    candidate = value.strip()
    for name, pattern in LIVE_CREDENTIAL_PATTERNS:
        if pattern.search(candidate):
            return name
    return None


def check_syntax(parsed: ParsedFile) -> list[Finding]:
    """Turn parse issues and duplicate keys into findings."""
    findings = [
        Finding(
            code="syntax",
            severity=Severity.ERROR,
            key=None,
            message=issue.message,
            line_number=issue.line_number,
        )
        for issue in parsed.issues
    ]
    for key, lines in sorted(parsed.duplicates().items()):
        rendered = ", ".join(str(number) for number in lines)
        findings.append(
            Finding(
                code="duplicate-key",
                severity=Severity.WARNING,
                key=key,
                message=(
                    f"assigned {len(lines)} times (lines {rendered}); "
                    "the last assignment wins"
                ),
                line_number=lines[-1],
            )
        )
    return findings


def check_against_example(
    parsed: ParsedFile,
    example: ParsedFile,
    *,
    ignore: frozenset[str] = frozenset(),
) -> list[Finding]:
    """Compare a real ``.env`` against the committed ``.env.example``."""
    findings: list[Finding] = []
    actual = parsed.as_dict()
    expected_keys = [key for key in example.keys() if key not in ignore]  # noqa: SIM118

    for key in expected_keys:
        if key not in actual:
            findings.append(
                Finding(
                    code="missing-key",
                    severity=Severity.ERROR,
                    key=key,
                    message="declared in the example file but absent here",
                )
            )

    example_keys = set(example.keys())
    for entry in parsed.entries:
        if entry.key in ignore or entry.key in example_keys:
            continue
        findings.append(
            Finding(
                code="undocumented-key",
                severity=Severity.WARNING,
                key=entry.key,
                message="set here but missing from the example file",
                line_number=entry.line_number,
            )
        )
    return findings


def check_values(
    parsed: ParsedFile, *, ignore: frozenset[str] = frozenset()
) -> list[Finding]:
    """Check each value on its own merits."""
    findings: list[Finding] = []
    for entry in parsed.entries:
        if entry.key in ignore:
            continue

        if is_placeholder(entry.value):
            findings.append(
                Finding(
                    code="placeholder-value",
                    # An unfilled credential is an outage; an unfilled
                    # ordinary value is usually just untidy.
                    severity=(
                        Severity.ERROR
                        if looks_secret(entry.key)
                        else Severity.WARNING
                    ),
                    key=entry.key,
                    message=(
                        f"value {entry.value!r} looks like an unfilled placeholder"
                    ),
                    line_number=entry.line_number,
                )
            )
            continue

        if looks_secret(entry.key):
            entropy = shannon_entropy(entry.value)
            if len(entry.value) < 8:
                findings.append(
                    Finding(
                        code="weak-secret",
                        severity=Severity.WARNING,
                        key=entry.key,
                        message=(
                            f"only {len(entry.value)} characters long for a "
                            "credential-shaped key"
                        ),
                        line_number=entry.line_number,
                    )
                )
            elif entropy < 2.5:
                findings.append(
                    Finding(
                        code="weak-secret",
                        severity=Severity.WARNING,
                        key=entry.key,
                        message=(
                            f"low entropy ({entropy:.2f} bits/char) for a "
                            "credential-shaped key"
                        ),
                        line_number=entry.line_number,
                    )
                )

        if entry.stripped_whitespace:
            findings.append(
                Finding(
                    code="unquoted-whitespace",
                    severity=Severity.WARNING,
                    key=entry.key,
                    message=(
                        "unquoted value has leading or trailing whitespace; "
                        "loaders disagree about keeping it — quote the value "
                        "if the whitespace is intentional"
                    ),
                    line_number=entry.line_number,
                )
            )
    return findings


def check_example_for_secrets(example: ParsedFile) -> list[Finding]:
    """A committed example file must never hold a real credential."""
    findings: list[Finding] = []
    for entry in example.entries:
        detected = detect_live_credential(entry.value)
        if detected is not None:
            findings.append(
                Finding(
                    code="secret-in-example",
                    severity=Severity.ERROR,
                    key=entry.key,
                    message=(
                        f"looks like a real {detected}; example files are "
                        "committed and must only contain placeholders"
                    ),
                    line_number=entry.line_number,
                )
            )
    return findings
