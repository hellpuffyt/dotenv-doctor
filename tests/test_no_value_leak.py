"""The README promises: "No value is ever printed."

These tests feed every rule, every format and every parse-error path with
secret-shaped values and assert that none of them -- not even a fragment of
a private key -- reaches stdout or stderr. Token-shaped fixtures are built
at runtime so no credential-looking literal is stored in the repository.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dotenv_doctor.cli import main

AWS = "AK" + "IA" + "Z7Q3FAKEFIXTURE0"
GITHUB = "gh" + "p_" + "F4keF1xtureT0kenF0rTests0nly0123456789"
SLACK = "xo" + "xb-" + "1234567890-fakefixture"
STRIPE = "sk" + "_live_" + "F4keF1xtureStr1pe99"
OPENAI = "s" + "k-" + "F4keF1xtureOpenAiKey0123"
ANTHROPIC = "s" + "k-ant-" + "F4keF1xtureAnthrop1c0123"
GOOGLE = "AI" + "za" + "SyF4keF1xtureG00gleKey0123456789abc"
JWT = ".".join(
    ["ey" + "JhbGciOiJIUzI1NiJ9", "eyJzdWIiOiJmaXh0dXJlIn0", "c2lnbmF0dXJlZml4dHVyZQ"]
)
PEM_BODY = [
    "MIIEowIBAAKCAQEAF4keF1xture+Body/Line0001",
    "Q1dEf4keF1xtureBodyLine0002ZZ==",
]
PEM = "\n".join(
    [
        "-----BEGIN RSA " + "PRIVATE KEY-----",
        *PEM_BODY,
        "-----END RSA " + "PRIVATE KEY-----",
    ]
)
STRONG = "Zq8#vT2!mW9$kL4@pX7"
WEAK_SHORT = "hunter2"
WEAK_LOW_ENTROPY = "aaaaaaaabbbb"
PLACEHOLDER_REAL = "Password"
SPACED = "  Sp4c3dS3cr3tV4lue  "
DUP_1, DUP_2 = "F1rstDupl1cateV4lue", "S3condDupl1cateV4lue"
UNCLOSED = "Uncl0sedQu0teS3cret"
TRAILING = "Tra1l1ngT3xtS3cret"

SECRETS = [AWS, GITHUB, SLACK, STRIPE, OPENAI, ANTHROPIC, GOOGLE, JWT, *PEM_BODY, STRONG,
           WEAK_SHORT, WEAK_LOW_ENTROPY, PLACEHOLDER_REAL, SPACED.strip(), DUP_1, DUP_2,
           UNCLOSED, TRAILING]

ENV = "\n".join([
    f"AWS_ACCESS_KEY_ID={AWS}",
    f"GITHUB_TOKEN={GITHUB}",
    f"SLACK_TOKEN={SLACK}",
    f"STRIPE_SECRET={STRIPE}",
    f"OPENAI_API_KEY={OPENAI}",
    f"ANTHROPIC_API_KEY={ANTHROPIC}",
    f"GOOGLE_API_KEY={GOOGLE}",
    f"SESSION_TOKEN={JWT}",
    f'QUOTED_PRIVATE_KEY="{PEM}"',
    f"UNQUOTED_PRIVATE_KEY={PEM}",
    f"STRONG_SECRET={STRONG}",
    f"DB_PASSWORD={WEAK_SHORT}",
    f"SIGNING_SECRET={WEAK_LOW_ENTROPY}",
    f"ADMIN_PASSWORD={PLACEHOLDER_REAL}",
    f"SPACED_TOKEN={SPACED}",
    f"DUP_TOKEN={DUP_1}",
    f"DUP_TOKEN={DUP_2}",
    f"{PEM_BODY[0]}",                       # stray line, no '='
    f"bad key name={STRONG}",               # invalid key
    f"{PEM_BODY[1][:-2]}+/x=1",             # invalid key made of key material
    f'UNCLOSED_TOKEN="{UNCLOSED}',
    f'TRAILING_TOKEN="x" {TRAILING}',
    "",
])


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    real = ENV + f"UNDOCUMENTED_TOKEN={STRONG}\n"
    (tmp_path / ".env").write_text(real, encoding="utf-8")
    (tmp_path / ".env.example").write_text(ENV, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("fmt", ["text", "json", "github"])
@pytest.mark.parametrize(
    "extra",
    [[], ["--strict"], ["--example-only"], ["--no-example"]],
    ids=["default", "strict", "example-only", "no-example"],
)
def test_no_secret_value_reaches_any_output(
    project: Path, capsys: pytest.CaptureFixture[str], fmt: str, extra: list[str]
) -> None:
    rc = main(["--format", fmt, *extra])
    out = capsys.readouterr()
    assert rc == 1  # there are findings in every mode
    combined = out.out + out.err
    for secret in SECRETS:
        assert secret not in combined, f"leaked a fixture value ({len(secret)} chars)"
    # Fragments of key material must not appear either (e.g. as a "key name").
    for line in PEM_BODY:
        assert line[:12] not in combined


def test_every_rule_fired_so_the_leak_test_is_meaningful(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["--format", "json"])
    out = capsys.readouterr().out
    for code in ("secret-in-example", "placeholder-value", "weak-secret", "duplicate-key",
                 "unquoted-whitespace", "syntax", "undocumented-key"):
        assert f'"{code}"' in out, code
