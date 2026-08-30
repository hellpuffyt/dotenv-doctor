"""Parser behaviour, including the edges that trip real loaders up."""

from __future__ import annotations

from dotenv_doctor.parser import parse


def test_parses_simple_assignments() -> None:
    parsed = parse("FOO=bar\nBAZ=qux\n")
    assert parsed.as_dict() == {"FOO": "bar", "BAZ": "qux"}
    assert parsed.issues == []


def test_ignores_blank_lines_and_comments() -> None:
    parsed = parse("# a comment\n\n   \nFOO=bar\n   # indented comment\n")
    assert parsed.as_dict() == {"FOO": "bar"}
    assert parsed.issues == []


def test_records_line_numbers() -> None:
    parsed = parse("# comment\nFOO=bar\n\nBAZ=qux\n")
    assert [(e.key, e.line_number) for e in parsed.entries] == [
        ("FOO", 2),
        ("BAZ", 4),
    ]


def test_export_prefix_is_accepted() -> None:
    parsed = parse("export FOO=bar\n")
    assert parsed.as_dict() == {"FOO": "bar"}
    assert parsed.entries[0].exported is True


def test_strips_inline_comment_from_unquoted_value() -> None:
    parsed = parse("FOO=bar   # trailing note\n")
    assert parsed.as_dict() == {"FOO": "bar"}


def test_hash_inside_unquoted_value_is_kept() -> None:
    # A '#' not preceded by whitespace is part of the value, not a comment.
    parsed = parse("PASSWORD=pass#word\n")
    assert parsed.as_dict() == {"PASSWORD": "pass#word"}


def test_double_quotes_are_stripped_and_escapes_expanded() -> None:
    parsed = parse('FOO="line1\\nline2"\n')
    assert parsed.as_dict() == {"FOO": "line1\nline2"}
    assert parsed.entries[0].quoted is True


def test_single_quotes_are_literal() -> None:
    parsed = parse("FOO='line1\\nline2'\n")
    assert parsed.as_dict() == {"FOO": "line1\\nline2"}


def test_quoted_value_keeps_inner_hash() -> None:
    parsed = parse('FOO="a # b"\n')
    assert parsed.as_dict() == {"FOO": "a # b"}


def test_empty_value_is_allowed() -> None:
    parsed = parse("FOO=\n")
    assert parsed.as_dict() == {"FOO": ""}
    assert parsed.issues == []


def test_value_containing_equals_is_kept_whole() -> None:
    parsed = parse("URL=postgres://u:p@h/db?opt=1\n")
    assert parsed.as_dict() == {"URL": "postgres://u:p@h/db?opt=1"}


def test_multiline_quoted_value_is_joined() -> None:
    text = 'KEY="-----BEGIN KEY-----\nabc\n-----END KEY-----"\n'
    parsed = parse(text)
    assert parsed.as_dict()["KEY"].startswith("-----BEGIN KEY-----")
    assert parsed.as_dict()["KEY"].endswith("-----END KEY-----")
    assert parsed.issues == []


def test_line_without_equals_is_an_issue() -> None:
    parsed = parse("JUST_A_WORD\n")
    assert parsed.entries == []
    assert len(parsed.issues) == 1
    assert "no '='" in parsed.issues[0].message


def test_invalid_key_is_an_issue() -> None:
    parsed = parse("2FOO=bar\n")
    assert parsed.entries == []
    assert "portable" in parsed.issues[0].message


def test_empty_key_is_an_issue() -> None:
    parsed = parse("=bar\n")
    assert parsed.entries == []
    assert parsed.issues[0].message == "empty key"


def test_duplicates_are_reported_and_last_wins() -> None:
    parsed = parse("FOO=one\nFOO=two\n")
    assert parsed.as_dict() == {"FOO": "two"}
    assert parsed.duplicates() == {"FOO": [1, 2]}


def test_keys_are_unique_in_first_appearance_order() -> None:
    parsed = parse("B=1\nA=2\nB=3\n")
    assert parsed.keys() == ["B", "A"]
