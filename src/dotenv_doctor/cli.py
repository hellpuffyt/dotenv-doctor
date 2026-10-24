"""Command-line entry point for dotenv-doctor."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .checks import (
    check_against_example,
    check_example_for_secrets,
    check_syntax,
    check_values,
)
from .parser import ParsedFile, parse_file
from .report import FileReport, Report, render_github, render_json, render_text

# Exit codes are part of the contract: CI branches on them.
EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2

DEFAULT_EXAMPLE = ".env.example"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dotenv-doctor",
        description=(
            "Validate .env files against a committed .env.example: catch "
            "missing keys, unfilled placeholders, weak secrets, and real "
            "credentials accidentally left in the example."
        ),
        epilog=(
            "Exit codes: 0 clean, 1 findings, 2 usage error. "
            "With --strict, warnings also produce exit code 1."
        ),
    )
    parser.add_argument(
        "files",
        nargs="*",
        default=None,
        help="the .env files to check (default: .env if it exists)",
    )
    parser.add_argument(
        "-e",
        "--example",
        default=None,
        help=(
            "the reference file to compare against (default: .env.example; "
            "an explicitly given file must exist)"
        ),
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("text", "json", "github"),
        default="text",
        help="output format (default: text)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat warnings as failures",
    )
    parser.add_argument(
        "--ignore",
        default="",
        help="comma-separated keys to skip entirely",
    )
    parser.add_argument(
        "--no-example",
        action="store_true",
        help="skip the comparison against the example file",
    )
    parser.add_argument(
        "--example-only",
        action="store_true",
        help=(
            "audit the example file itself for syntax errors and committed "
            "credentials, and check nothing else. Placeholder and weak-secret "
            "rules are skipped, because an example file is meant to hold "
            "placeholders. Needs no real .env, so it suits a public CI job."
        ),
    )
    parser.add_argument(
        "--no-colour",
        "--no-color",
        dest="no_colour",
        action="store_true",
        help="disable ANSI colour even on a TTY",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"dotenv-doctor {__version__}",
    )
    return parser


def _default_targets() -> list[str]:
    return [".env"] if Path(".env").is_file() else []


def _emit(report: Report, args: argparse.Namespace) -> None:
    """Print a report in whichever format was requested."""
    if args.format == "json":
        print(render_json(report))
    elif args.format == "github":
        rendered = render_github(report)
        if rendered:
            print(rendered)
    else:
        colour = (
            not args.no_colour
            and sys.stdout.isatty()
            and os.environ.get("NO_COLOR") is None
        )
        print(render_text(report, colour=colour))


def _load(path: Path) -> ParsedFile | None:
    """Parse a file, reporting unreadable / non-UTF-8 input on stderr without
    echoing any of its content."""
    try:
        return parse_file(str(path))
    except UnicodeDecodeError as exc:
        print(f"{path}: not valid UTF-8 (byte offset {exc.start})", file=sys.stderr)
    except OSError as exc:
        print(f"{path}: cannot read ({exc.strerror})", file=sys.stderr)
    return None


def _audit_example(args: argparse.Namespace) -> int:
    """Check the example file alone for syntax and committed credentials."""
    path = Path(args.example or DEFAULT_EXAMPLE)
    if not path.is_file():
        print(f"no such file: {path}", file=sys.stderr)
        return EXIT_USAGE

    parsed = _load(path)
    if parsed is None:
        return EXIT_USAGE
    findings = check_syntax(parsed) + check_example_for_secrets(parsed)
    report = Report([FileReport(str(path), findings)])
    _emit(report, args)
    return EXIT_OK if report.ok(strict=args.strict) else EXIT_FINDINGS


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.example_only:
        return _audit_example(args)

    targets = args.files or _default_targets()
    if not targets:
        print(
            "no .env file given and none found in the current directory",
            file=sys.stderr,
        )
        return EXIT_USAGE

    ignore = frozenset(
        part.strip() for part in args.ignore.split(",") if part.strip()
    )

    example = ParsedFile()
    example_path = Path(args.example or DEFAULT_EXAMPLE)
    use_example = not args.no_example and example_path.is_file()
    if not args.no_example and not use_example:
        if args.example is not None:
            # An explicitly named contract that does not exist must not be
            # silently skipped: the run would "pass" without checking it.
            print(f"no such file: {args.example}", file=sys.stderr)
            return EXIT_USAGE
        print(
            f"note: {DEFAULT_EXAMPLE} not found; example-contract checks skipped "
            "(pass --no-example to silence this)",
            file=sys.stderr,
        )
    if use_example:
        loaded = _load(example_path)
        if loaded is None:
            return EXIT_USAGE
        example = loaded

    report = Report()

    # The example file is itself checked, once, for committed credentials.
    if use_example:
        secret_findings = check_example_for_secrets(example)
        if secret_findings:
            report.files.append(FileReport(str(example_path), secret_findings))

    for target in targets:
        path = Path(target)
        if not path.is_file():
            print(f"no such file: {target}", file=sys.stderr)
            return EXIT_USAGE

        parsed = _load(path)
        if parsed is None:
            return EXIT_USAGE
        findings = check_syntax(parsed) + check_values(parsed, ignore=ignore)
        if use_example:
            findings += check_against_example(parsed, example, ignore=ignore)
        report.files.append(FileReport(str(path), findings))

    _emit(report, args)
    return EXIT_OK if report.ok(strict=args.strict) else EXIT_FINDINGS


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
