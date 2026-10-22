"""Regression tests for defects found in the production-readiness audit."""

from __future__ import annotations

from pathlib import Path

import pytest

from dotenv_doctor.checks import Finding, Severity
from dotenv_doctor.cli import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, main
from dotenv_doctor.parser import parse
from dotenv_doctor.report import FileReport, Report, render_github


def entries(text: str) -> dict[str, str]:
    return parse(text).as_dict()


def issues(text: str) -> list[tuple[int, str]]:
    return [(i.line_number, i.message) for i in parse(text).issues]


def test_quoted_value_with_inline_comment_does_not_swallow_the_file() -> None:
    # Before: the closing quote was only recognised at end of line, so every
    # following line was glued into API_KEY's value and DATABASE_URL / PORT
    # vanished (false missing-key errors).
    text = 'API_KEY="abc" # the key\nDATABASE_URL=postgres://db\nPORT=1\n'
    assert entries(text) == {
        "API_KEY": "abc",
        "DATABASE_URL": "postgres://db",
        "PORT": "1",
    }
    assert issues(text) == []


def test_unterminated_quote_is_reported_and_parsing_resumes() -> None:
    # Before: silently consumed the rest of the file.
    text = 'API_KEY="abc\nDATABASE_URL=postgres://db\nPORT=1\n'
    assert entries(text) == {"DATABASE_URL": "postgres://db", "PORT": "1"}
    assert issues(text) == [(1, "quoted value is never closed")]


def test_text_after_closing_quote_is_reported() -> None:
    assert issues('K="x" y\n') == [(1, "unexpected text after the closing quote")]


def test_escaped_quote_does_not_close_the_value() -> None:
    assert entries('K="a\\"b" # c\n') == {"K": 'a"b'}


def test_multiline_quoted_value_still_joins() -> None:
    assert entries('K="l1\nl2"\nB=2\n') == {"K": "l1\nl2", "B": "2"}


def test_utf8_bom_is_not_part_of_the_first_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Before: the first key became "﻿API_KEY" -> syntax error + missing-key.
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.example").write_text("API_KEY=\n", encoding="utf-8")
    (tmp_path / ".env").write_bytes("﻿API_KEY=xJ3$kQ9zPw27Lm4TbVn8\n".encode())
    assert main([]) == EXIT_OK


def test_unquoted_pem_block_is_one_reported_entry() -> None:
    # Before: base64 body lines became syntax errors and, when a line ended
    # in '=' padding, an "assignment" whose key was key material.
    text = (
        "PRIVATE_KEY=-----BEGIN RSA " + "PRIVATE KEY-----\n"
        "MIIEow+IBAAKCAQEA/x\nAbCdEf123==\n"
        "-----END RSA " + "PRIVATE KEY-----\nB=1\n"
    )
    parsed = parse(text)
    assert [e.key for e in parsed.entries] == ["PRIVATE_KEY", "B"]
    assert issues(text) == [(1, "unquoted multi-line value; wrap it in double quotes")]


def test_invalid_key_message_does_not_repeat_the_key() -> None:
    [(_, message)] = issues("abc+/def=1\n")
    assert "abc" not in message


def test_explicit_example_that_does_not_exist_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Before: silently skipped, so the run passed without any contract check.
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("PORT=1\n", encoding="utf-8")
    assert main(["--example", "missing.example"]) == EXIT_USAGE


def test_missing_default_example_is_announced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("PORT=1\n", encoding="utf-8")
    assert main([]) == EXIT_OK
    assert "example-contract checks skipped" in capsys.readouterr().err
    assert main(["--no-example"]) == EXIT_OK
    assert capsys.readouterr().err == ""


def test_non_utf8_file_is_a_usage_error_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_bytes(b"API_KEY=\xff\xfe\n")
    assert main(["--no-example"]) == EXIT_USAGE
    assert "not valid UTF-8" in capsys.readouterr().err


def test_github_workflow_command_values_are_escaped() -> None:
    finding = Finding("missing-key", Severity.ERROR, "K", "a%b\nc")
    out = render_github(Report([FileReport("dir,with:odd\nname/.env", [finding])]))
    assert out == (
        "::error file=dir%2Cwith%3Aodd%0Aname/.env,title=missing-key::K: a%25b%0Ac"
    )


def test_placeholder_finding_names_no_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("DB_PASSWORD=Password\n", encoding="utf-8")
    assert main(["--no-example"]) == EXIT_FINDINGS
    out = capsys.readouterr().out
    assert "placeholder-value" in out
    assert "Password" not in out
