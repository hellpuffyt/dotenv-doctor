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


def _closing_quote(body: str, quote: str) -> int:
    """Index of the quote that closes ``body`` (the text after the opening
    quote), or -1. Inside double quotes a backslash escapes the next char."""
    index = 0
    while index < len(body):
        char = body[index]
        if quote == '"' and char == "\\":
            index += 2
            continue
        if char == quote:
            return index
        index += 1
    return -1


def _expand_escapes(body: str) -> str:
    """Double-quote escapes shared by python-dotenv and docker-compose."""
    mapping = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}
    out: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if char == "\\" and index + 1 < len(body) and body[index + 1] in mapping:
            out.append(mapping[body[index + 1]])
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _unquote(raw: str) -> tuple[str, bool, str | None]:
    """Return ``(value, was_quoted, problem)``.

    Double quotes allow ``\\n``/``\\t``/``\\"``/``\\\\`` escapes; single quotes
    are literal. Text after the closing quote may only be a ``# comment``.
    ``problem`` describes a malformed quoted value without quoting any of it.
    """
    if raw[:1] in ("'", '"'):
        quote = raw[0]
        close = _closing_quote(raw[1:], quote)
        if close < 0:
            return "", True, "quoted value is never closed"
        body = raw[1 : close + 1]
        rest = raw[close + 2 :].strip()
        problem = None
        if rest and not rest.startswith("#"):
            problem = "unexpected text after the closing quote"
        value = _expand_escapes(body) if quote == '"' else body
        return value, True, problem
    return _strip_inline_comment(raw), False, None


_PEM_BEGIN = re.compile(r"^-----BEGIN [A-Z0-9 ]+-----")
_PEM_BODY = re.compile(r"^[A-Za-z0-9+/=]*$|^[A-Za-z-]+: ")


def _logical_lines(text: str) -> Iterator[tuple[int, str, str | None]]:
    """Yield ``(first_line_number, logical_line, problem)``.

    A value opened with a quote may span physical lines; joining them here
    keeps multi-line private keys (a very common ``.env`` payload) intact.
    A quote that is never closed does *not* swallow the rest of the file:
    only that line is reported and parsing resumes on the next one.

    An *unquoted* PEM block (``KEY=-----BEGIN ... KEY-----`` followed by
    base64 lines) is consumed as one logical line and reported, so the key
    material is never misread as further assignments -- whose "key names"
    would otherwise be echoed in findings.
    """
    physical = text.splitlines()
    index = 0
    while index < len(physical):
        start = index
        line = physical[index]
        problem: str | None = None
        stripped = _EXPORT_PREFIX.sub("", line.strip(), count=1)
        if stripped and not stripped.startswith("#") and "=" in stripped:
            _, _, raw_value = stripped.partition("=")
            raw_value = raw_value.strip()
            quote = raw_value[:1]
            if quote in ("'", '"') and _closing_quote(raw_value[1:], quote) < 0:
                joined = line
                probe = index
                closed = False
                while probe + 1 < len(physical):
                    probe += 1
                    joined = f"{joined}\n{physical[probe]}"
                    _, _, candidate = _EXPORT_PREFIX.sub(
                        "", joined.strip(), count=1
                    ).partition("=")
                    candidate = candidate.strip()
                    if _closing_quote(candidate[1:], quote) >= 0:
                        closed = True
                        break
                if closed:
                    line, index = joined, probe
                else:
                    problem = "quoted value is never closed"
            elif _PEM_BEGIN.match(raw_value) and "-----END" not in raw_value:
                probe = index
                while probe + 1 < len(physical):
                    nxt = physical[probe + 1].strip()
                    if nxt.startswith("-----END"):
                        probe += 1
                        break
                    if not _PEM_BODY.match(nxt):
                        break
                    probe += 1
                line = "\n".join(physical[index : probe + 1])
                index = probe
                problem = "unquoted multi-line value; wrap it in double quotes"
        yield start + 1, line, problem
        index += 1


def parse(text: str) -> ParsedFile:
    """Parse ``.env`` content into entries and issues.

    Issue messages describe the problem and never contain the line's
    content, which may be a secret.
    """
    result = ParsedFile()
    text = text.removeprefix("\ufeff")  # a UTF-8 BOM is not part of the first key
    for line_number, line, problem in _logical_lines(text):
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
            # The "key" may be a fragment of a secret (e.g. a stray base64
            # line), so it is deliberately not repeated in the message.
            result.issues.append(
                ParseIssue(
                    line_number,
                    line,
                    "key is not a portable environment variable name",
                )
            )
            continue

        if problem == "quoted value is never closed":
            result.issues.append(ParseIssue(line_number, line, problem))
            continue

        value, quoted, value_problem = _unquote(raw_value.strip())
        if problem is not None:
            # Unquoted PEM block: keep the entry (the key is present) but
            # report the portability problem.
            value = raw_value.strip()
            result.issues.append(ParseIssue(line_number, line, problem))
        elif value_problem is not None:
            result.issues.append(ParseIssue(line_number, line, value_problem))
            continue

        # Decide whether this parser dropped whitespace that some other loader
        # would have kept. Derived from the *original* line, because `stripped`
        # above has already removed the trailing whitespace we are looking for.
        stripped_whitespace = False
        if not quoted and value and problem is None:
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
    with open(path, encoding="utf-8-sig") as handle:
        return parse(handle.read())
