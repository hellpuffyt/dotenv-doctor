"""A tolerant ``.env`` parser.

Deliberately not a shell parser. ``.env`` files are read by dozens of
loaders (python-dotenv, dotenv, docker-compose, foreman, direnv) that all
disagree about the edges, so this module implements the intersection that
every one of them agrees on, and records anything ambiguous as a
:class:`ParseIssue` rather than guessing.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

# `export FOO=bar` is accepted by every loader that reads shell-ish files.
_EXPORT_PREFIX = re.compile(r"^export\s+")
# A key is POSIX-portable: letters, digits, underscore, not leading a digit.
_VALID_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ParseIssue:
    """Something wrong with a single physical line."""

    line_number: int
    line: str
    message: str


@dataclass(frozen=True)
class Entry:
    """One resolved ``KEY=value`` assignment."""

    key: str
    value: str
    line_number: int
    quoted: bool = False
    exported: bool = False
    #: True when the unquoted source value carried leading or trailing
    #: whitespace that this parser removed. Loaders disagree about whether to
    #: keep it, so the value is not portable — worth reporting.
    stripped_whitespace: bool = False


@dataclass
class ParsedFile:
    """The result of parsing one ``.env`` file."""

    entries: list[Entry] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)

    def as_dict(self) -> dict[str, str]:
        """Later assignments win, matching every mainstream loader."""
        return {entry.key: entry.value for entry in self.entries}

    def keys(self) -> list[str]:
        """Unique keys, in first-appearance order."""
        seen: dict[str, None] = {}
        for entry in self.entries:
            seen.setdefault(entry.key, None)
        return list(seen)

    def duplicates(self) -> dict[str, list[int]]:
        """Keys assigned more than once, mapped to every line they appear on."""
        lines: dict[str, list[int]] = {}
        for entry in self.entries:
            lines.setdefault(entry.key, []).append(entry.line_number)
        return {key: nums for key, nums in lines.items() if len(nums) > 1}


def _strip_inline_comment(value: str) -> str:
    """Remove a trailing ``# comment`` from an unquoted value.

    Only a ``#`` that follows whitespace starts a comment; ``pass#word`` is
    a legitimate unquoted value and must survive intact.
    """
    out: list[str] = []
    previous_was_space = True  # a leading '#' is a comment
    for char in value:
        if char == "#" and previous_was_space:
            break
        out.append(char)
        previous_was_space = char.isspace()
    return "".join(out).rstrip()


def _strip_inline_comment_keep_space(value: str) -> str:
    """Remove a trailing ``# comment`` but preserve surrounding whitespace.

    Used to detect whitespace that :func:`_strip_inline_comment` would drop.
    """
    out: list[str] = []
    previous_was_space = True
    for char in value:
        if char == "#" and previous_was_space:
            break
        out.append(char)
        previous_was_space = char.isspace()
    return "".join(out)


def _unquote(raw: str) -> tuple[str, bool]:
    """Return ``(value, was_quoted)``.

    Double quotes allow ``\\n``/``\\t``/``\\"``/``\\\\`` escapes; single quotes
    are literal. This is the behaviour python-dotenv and docker-compose share.
    """
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        body = raw[1:-1]
        if raw[0] == "'":
            return body, True
        out: list[str] = []
        index = 0
        while index < len(body):
            char = body[index]
            if char == "\\" and index + 1 < len(body):
                nxt = body[index + 1]
                mapping = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}
                if nxt in mapping:
                    out.append(mapping[nxt])
                    index += 2
                    continue
            out.append(char)
            index += 1
        return "".join(out), True
    return _strip_inline_comment(raw), False


def _logical_lines(text: str) -> Iterator[tuple[int, str]]:
    """Yield ``(first_line_number, logical_line)``.

    A value opened with a quote may span physical lines; joining them here
    keeps multi-line private keys (a very common ``.env`` payload) intact.
    """
    physical = text.splitlines()
    index = 0
    while index < len(physical):
        start = index
        line = physical[index]
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            _, _, raw_value = stripped.partition("=")
            raw_value = raw_value.strip()
            if raw_value[:1] in ("'", '"'):
                quote = raw_value[0]
                closed = len(raw_value) >= 2 and raw_value.endswith(quote)
                while not closed and index + 1 < len(physical):
                    index += 1
                    line = f"{line}\n{physical[index]}"
                    closed = physical[index].rstrip().endswith(quote)
        yield start + 1, line
        index += 1


def parse(text: str) -> ParsedFile:
    """Parse ``.env`` content into entries and issues."""
    result = ParsedFile()
    for line_number, line in _logical_lines(text):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        exported = bool(_EXPORT_PREFIX.match(stripped))
        if exported:
            stripped = _EXPORT_PREFIX.sub("", stripped, count=1)

        if "=" not in stripped:
            result.issues.append(
                ParseIssue(line_number, line, "no '=' found; not an assignment")
            )
            continue

        key, _, raw_value = stripped.partition("=")
        key = key.strip()

        if not key:
            result.issues.append(ParseIssue(line_number, line, "empty key"))
            continue
        if not _VALID_KEY.match(key):
            result.issues.append(
                ParseIssue(
                    line_number,
                    line,
                    f"key {key!r} is not a portable environment variable name",
                )
            )
            continue

        value, quoted = _unquote(raw_value.strip())

        # Decide whether this parser dropped whitespace that some other loader
        # would have kept. Derived from the *original* line, because `stripped`
        # above has already removed the trailing whitespace we are looking for.
        stripped_whitespace = False
        if not quoted and value:
            _, _, raw_original = line.partition("=")
            raw_original = raw_original.rstrip("\r\n")
            body = _strip_inline_comment_keep_space(raw_original)
            if len(body) != len(raw_original):
                # An inline comment follows. The whitespace separating value
                # from comment is a separator, not part of the value, so only
                # leading whitespace is significant here.
                stripped_whitespace = body != body.lstrip()
            else:
                stripped_whitespace = raw_original != raw_original.strip()

        result.entries.append(
            Entry(
                key=key,
                value=value,
                line_number=line_number,
                quoted=quoted,
                exported=exported,
                stripped_whitespace=stripped_whitespace,
            )
        )
    return result


def parse_file(path: str) -> ParsedFile:
    """Parse a ``.env`` file from disk as UTF-8."""
    with open(path, encoding="utf-8") as handle:
        return parse(handle.read())
