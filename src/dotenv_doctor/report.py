"""Rendering findings for humans and for machines."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .checks import Finding, Severity

# ANSI colours, applied only when the caller says the stream is a TTY.
_COLOURS = {
    Severity.ERROR: "\033[31m",
    Severity.WARNING: "\033[33m",
    Severity.INFO: "\033[36m",
}
_RESET = "\033[0m"
_DIM = "\033[2m"
_BOLD = "\033[1m"


@dataclass
class FileReport:
    """All findings for one checked file."""

    path: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(1 for f in self.findings if f.severity is Severity.ERROR)

    @property
    def warnings(self) -> int:
        return sum(1 for f in self.findings if f.severity is Severity.WARNING)


@dataclass
class Report:
    """The whole run."""

    files: list[FileReport] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(f.errors for f in self.files)

    @property
    def warnings(self) -> int:
        return sum(f.warnings for f in self.files)

    def ok(self, *, strict: bool = False) -> bool:
        """True when the run should be considered a pass."""
        return self.errors == 0 and (not strict or self.warnings == 0)


def _sorted(findings: list[Finding]) -> list[Finding]:
    """Most severe first, then by line, then by key, for stable output."""
    return sorted(
        findings,
        key=lambda f: (-f.severity.rank, f.line_number or 0, f.key or ""),
    )


def render_text(report: Report, *, colour: bool = False) -> str:
    """Human-readable output, one finding per line."""

    def paint(text: str, code: str) -> str:
        return f"{code}{text}{_RESET}" if colour else text

    lines: list[str] = []
    for file_report in report.files:
        if not file_report.findings:
            lines.append(f"{paint('ok', _COLOURS[Severity.INFO])} {file_report.path}")
            continue
        lines.append(paint(file_report.path, _BOLD))
        for finding in _sorted(file_report.findings):
            label = paint(finding.severity.value, _COLOURS[finding.severity])
            where = paint(finding.location(), _DIM)
            name = f" {finding.key}" if finding.key else ""
            lines.append(
                f"  {label} {where}{name}: {finding.message} "
                f"{paint('[' + finding.code + ']', _DIM)}"
            )
        lines.append("")

    summary = (
        f"{report.errors} error(s), {report.warnings} warning(s) "
        f"across {len(report.files)} file(s)"
    )
    lines.append(paint(summary, _BOLD))
    return "\n".join(lines)


def render_json(report: Report) -> str:
    """Machine-readable output for CI and other tools."""
    payload = {
        "summary": {
            "files": len(report.files),
            "errors": report.errors,
            "warnings": report.warnings,
        },
        "files": [
            {
                "path": file_report.path,
                "errors": file_report.errors,
                "warnings": file_report.warnings,
                "findings": [
                    {
                        "code": finding.code,
                        "severity": finding.severity.value,
                        "key": finding.key,
                        "line": finding.line_number,
                        "message": finding.message,
                    }
                    for finding in _sorted(file_report.findings)
                ],
            }
            for file_report in report.files
        ],
    }
    return json.dumps(payload, indent=2)


def render_github(report: Report) -> str:
    """GitHub Actions workflow commands, so findings annotate the diff."""
    lines: list[str] = []
    for file_report in report.files:
        for finding in _sorted(file_report.findings):
            level = "error" if finding.severity is Severity.ERROR else "warning"
            location = f",line={finding.line_number}" if finding.line_number else ""
            name = f"{finding.key}: " if finding.key else ""
            lines.append(
                f"::{level} file={file_report.path}{location},"
                f"title={finding.code}::{name}{finding.message}"
            )
    return "\n".join(lines)
