"""Rule behaviour: what gets flagged, and just as importantly what does not."""

from __future__ import annotations

import pytest

from dotenv_doctor.checks import (
    Severity,
    check_against_example,
    check_example_for_secrets,
    check_syntax,
    check_values,
    detect_live_credential,
    is_placeholder,
    looks_secret,
    shannon_entropy,
)
from dotenv_doctor.parser import parse


def codes(findings) -> set[str]:
    return {finding.code for finding in findings}


class TestHelpers:
    def test_entropy_of_empty_string_is_zero(self) -> None:
        assert shannon_entropy("") == 0.0

    def test_entropy_of_uniform_string_is_zero(self) -> None:
        assert shannon_entropy("aaaaaaaa") == 0.0

    def test_entropy_rises_with_variety(self) -> None:
        assert shannon_entropy("aB3$xQ71zP") > shannon_entropy("aaaabbbb")

    @pytest.mark.parametrize(
        "value", ["", "changeme", "TODO", "your_api_key", "<your-key>", "..."]
    )
    def test_placeholders_are_detected(self, value: str) -> None:
        assert is_placeholder(value)

    @pytest.mark.parametrize("value", ["s3cr3t-real-value", "postgres://x/y"])
    def test_real_values_are_not_placeholders(self, value: str) -> None:
        assert not is_placeholder(value)

    def test_placeholder_match_is_whole_value_only(self) -> None:
        # A real secret that merely contains "changeme" must not be flagged.
        assert not is_placeholder("changeme-but-actually-a-long-real-secret")

    @pytest.mark.parametrize(
        "key", ["API_KEY", "db_password", "GITHUB_TOKEN", "CLIENT_SECRET"]
    )
    def test_secret_shaped_keys_are_detected(self, key: str) -> None:
        assert looks_secret(key)

    @pytest.mark.parametrize("key", ["PORT", "LOG_LEVEL", "NODE_ENV"])
    def test_ordinary_keys_are_not_secret_shaped(self, key: str) -> None:
        assert not looks_secret(key)


class TestLiveCredentialDetection:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("AKIAIOSFODNN7EXAMPLE", "aws-access-key-id"),
            ("ghp_" + "a" * 36, "github-token"),
            ("xoxb-123456789012-abcdef", "slack-token"),
            ("sk_live_" + "a" * 24, "stripe-secret-key"),
            ("AIza" + "b" * 35, "google-api-key"),
            ("-----BEGIN RSA PRIVATE KEY-----", "private-key-block"),
        ],
    )
    def test_known_shapes_are_detected(self, value: str, expected: str) -> None:
        assert detect_live_credential(value) == expected

    @pytest.mark.parametrize(
        "value", ["changeme", "", "postgres://localhost/db", "a-normal-value"]
    )
    def test_ordinary_values_are_not_credentials(self, value: str) -> None:
        assert detect_live_credential(value) is None


class TestSyntaxChecks:
    def test_clean_file_yields_nothing(self) -> None:
        assert check_syntax(parse("FOO=bar\n")) == []

    def test_parse_issue_becomes_an_error(self) -> None:
        findings = check_syntax(parse("NOT_AN_ASSIGNMENT\n"))
        assert findings[0].severity is Severity.ERROR
        assert findings[0].code == "syntax"

    def test_duplicate_key_becomes_a_warning(self) -> None:
        findings = check_syntax(parse("FOO=1\nFOO=2\n"))
        assert codes(findings) == {"duplicate-key"}
        assert findings[0].severity is Severity.WARNING


class TestExampleComparison:
    def test_missing_key_is_an_error(self) -> None:
        findings = check_against_example(parse("A=1\n"), parse("A=\nB=\n"))
        assert codes(findings) == {"missing-key"}
        assert findings[0].key == "B"
        assert findings[0].severity is Severity.ERROR

    def test_undocumented_key_is_a_warning(self) -> None:
        findings = check_against_example(parse("A=1\nZ=9\n"), parse("A=\n"))
        assert codes(findings) == {"undocumented-key"}
        assert findings[0].key == "Z"

    def test_matching_files_yield_nothing(self) -> None:
        assert check_against_example(parse("A=1\nB=2\n"), parse("A=\nB=\n")) == []

    def test_ignored_keys_are_skipped_in_both_directions(self) -> None:
        findings = check_against_example(
            parse("Z=9\n"), parse("B=\n"), ignore=frozenset({"B", "Z"})
        )
        assert findings == []


class TestValueChecks:
    def test_placeholder_in_secret_key_is_an_error(self) -> None:
        findings = check_values(parse("API_KEY=changeme\n"))
        assert findings[0].code == "placeholder-value"
        assert findings[0].severity is Severity.ERROR

    def test_placeholder_in_ordinary_key_is_a_warning(self) -> None:
        findings = check_values(parse("GREETING=todo\n"))
        assert findings[0].severity is Severity.WARNING

    def test_short_secret_is_flagged_as_weak(self) -> None:
        findings = check_values(parse("API_KEY=abc123\n"))
        assert codes(findings) == {"weak-secret"}

    def test_low_entropy_secret_is_flagged_as_weak(self) -> None:
        findings = check_values(parse("API_KEY=aaaaaaaaaaaaaaaa\n"))
        assert codes(findings) == {"weak-secret"}

    def test_strong_secret_passes(self) -> None:
        findings = check_values(parse("API_KEY=xJ3$kQ9zPw27Lm4TbVn8\n"))
        assert findings == []

    def test_non_secret_short_value_is_not_flagged(self) -> None:
        # PORT=3000 is short and low-entropy but is not a credential.
        assert check_values(parse("PORT=3000\n")) == []

    def test_unquoted_trailing_whitespace_is_flagged(self) -> None:
        # Trailing space on an unquoted value is dropped by this parser but
        # kept by some loaders, so the value is not portable.
        findings = check_values(parse("GREETING=hello   \n"))
        assert codes(findings) == {"unquoted-whitespace"}

    def test_quoted_whitespace_is_intentional_and_not_flagged(self) -> None:
        findings = check_values(parse('GREETING="hello "\n'))
        assert findings == []

    def test_value_without_surrounding_whitespace_is_not_flagged(self) -> None:
        assert check_values(parse("GREETING=hello\n")) == []

    def test_inline_comment_alone_does_not_trigger_whitespace_finding(self) -> None:
        assert check_values(parse("GREETING=hello  # a note\n")) == []

    def test_leading_whitespace_is_flagged(self) -> None:
        findings = check_values(parse("GREETING=   hello\n"))
        assert codes(findings) == {"unquoted-whitespace"}

    def test_leading_whitespace_before_comment_is_flagged(self) -> None:
        findings = check_values(parse("GREETING=   hello  # note\n"))
        assert codes(findings) == {"unquoted-whitespace"}

    def test_empty_value_is_not_a_whitespace_finding(self) -> None:
        # An empty value is a placeholder, but never a whitespace finding.
        assert "unquoted-whitespace" not in codes(check_values(parse("GREETING=\n")))

    def test_ignored_key_is_skipped(self) -> None:
        findings = check_values(
            parse("API_KEY=changeme\n"), ignore=frozenset({"API_KEY"})
        )
        assert findings == []


class TestExampleSecrets:
    def test_real_credential_in_example_is_an_error(self) -> None:
        findings = check_example_for_secrets(parse("AWS_KEY=AKIAIOSFODNN7EXAMPLE\n"))
        assert findings[0].code == "secret-in-example"
        assert findings[0].severity is Severity.ERROR

    def test_placeholder_example_is_clean(self) -> None:
        assert check_example_for_secrets(parse("AWS_KEY=\nTOKEN=changeme\n")) == []
