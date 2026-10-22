# Production readiness — dotenv-doctor

Audit date: 2026-10-22. Tested code commit: `9ba213d` (branch
`audit/production-readiness`); later commits change documentation and
repository metadata only.

## Scope

Dependency-free CLI that parses `.env` files, compares them with a committed
`.env.example`, and reports missing/undocumented keys, placeholders, weak
secrets, duplicate keys, whitespace problems and credential shapes committed
to the example — as text, JSON or GitHub workflow commands — **without ever
printing a value**. Architecture: `parser.py` (text → entries + issues) →
`checks.py` (pure rules) → `report.py` (renderers) → `cli.py` (I/O).

## Platforms and prerequisites

Python ≥ 3.10, no runtime dependencies. Verified on macOS 27 (Apple Silicon)
with Python 3.12 (full + clean clone), 3.10 and 3.13 (suite). Linux/Windows
CI legs not run for this audit. Not on PyPI — the PyPI name belongs to an
unrelated project (checked 2026-10-22: `pypi.org/pypi/dotenv-doctor/json`
returns a different author and repository).

## Clean-clone verification (README "From source", Testing, Usage)

```bash
git clone -b audit/production-readiness <repo> dotenv-doctor && cd dotenv-doctor
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"                                  # exit 0
pytest                                                   # 116 passed
pytest --cov=dotenv_doctor                               # 98% line coverage
ruff check .                                             # exit 0
mypy                                                     # no issues in 6 files
dotenv-doctor --format github --example-only             # exit 0 (the committed example is clean)
dotenv-doctor   # with the README's demo .env            # output identical to README, exit 1
```

## Commands and outcomes

| Step | Command | Exit | Result |
|---|---|---:|---|
| Baseline (main `50612a6`) | `pytest` | 0 | 90 passed, 0 failed, 0 skipped |
| Baseline lint/types | `ruff check .`, `mypy` | 0, 0 | clean |
| Final (3.10, 3.12, 3.13) | `pytest` | 0 | 116 passed, 0 failed, 0 skipped |
| Final lint/types/coverage | `ruff`, `mypy`, `--cov` | 0 | clean; 98% |
| Leak tests on original code | `PYTHONPATH=<main>/src pytest tests/test_no_value_leak.py` | 1 | 13 failed (values printed) |
| Dependency audit | `uvx pip-audit -r <frozen dev env> --disable-pip --no-deps --strict -s osv` | 0 | no known vulnerabilities (PyPI service timed out; OSV used) |
| Secret scan, tree | detect-secrets | – | only synthetic test fixtures |
| Secret scan, history | credential-pattern `git grep` over all revisions | – | 7 hits in `50612a6` (AWS documentation key `AKIA…EXAMPLE`, a dummy Slack token, a PEM header string) — test fixtures, not credentials; none in audit commits |

CI: default branch `main`: **success** (run on `50612a6`). Audit branch:
pending until pushed.

## Bugs found and fixed

| # | Severity | Defect | Regression test |
|---|---|---|---|
| 1 | High (secret leak) | `placeholder-value` echoed the value; `Password`/`test`/`secret` are both placeholders and real weak passwords | `test_placeholder_finding_names_no_value`, `tests/test_no_value_leak.py` |
| 2 | High (secret leak) | invalid-key syntax error echoed the "key" — e.g. a fragment of a pasted private key | `test_invalid_key_message_does_not_repeat_the_key`, leak tests |
| 3 | High (wrong core result) | `KEY="v" # comment` swallowed all following lines; later keys reported missing | `test_quoted_value_with_inline_comment_does_not_swallow_the_file` |
| 4 | High (supply chain, docs) | README/CI snippet `pip install dotenv-doctor` installs an unrelated PyPI project | README change (no code) |
| 5 | Medium | unterminated quote silently consumed the rest of the file | `test_unterminated_quote_is_reported_and_parsing_resumes` |
| 6 | Medium | unquoted PEM block → syntax error per line and "keys" made of key material | `test_unquoted_pem_block_is_one_reported_entry` |
| 7 | Medium (fail-open) | explicit `--example` path that does not exist silently skipped | `test_explicit_example_that_does_not_exist_is_a_usage_error` |
| 8 | Low | UTF-8 BOM broke the first key | `test_utf8_bom_is_not_part_of_the_first_key` |
| 9 | Low | non-UTF-8 / unreadable file → traceback | `test_non_utf8_file_is_a_usage_error_without_traceback` |
| 10 | Low (injection) | GitHub workflow commands not escaped | `test_github_workflow_command_values_are_escaped` |
| 11 | Low | text after a closing quote kept the quotes in the value | `test_text_after_closing_quote_is_reported` |

## Security review

Values never reach any output (asserted for 22 secret-shaped values × 4
modes × 3 formats, stdout + stderr). Still printed by design: key names,
line numbers, file paths, and for `weak-secret` the length or entropy of the
value. No network, no subprocess, no writes. History contains only public
documentation/dummy fixtures — **no rotation needed**.

## Known limitations

Shape-based credential detection only; comments in the example are not
inspected; UTF-8 only; ambiguous quoting is reported, not guessed.

## Acceptance checklist

| Item | Expected | Command / test | Result | Actual | Reference |
|---|---|---|---|---|---|
| A1 | Install from source; CLI works | README | pass | exit 0 | clean clone |
| A2 | Suite/lint/types green | `pytest`, `ruff`, `mypy` | pass | 116 passed | CI |
| A3 | No value printed in any mode/format | leak tests | pass | 0 leaks | `tests/test_no_value_leak.py` |
| A4 | Contract: missing = error, undocumented = warning | tests | pass | yes | `tests/test_checks.py` |
| A5 | Exit codes 0/1/2 incl. `--strict` | tests | pass | yes | `tests/test_cli.py` |
| A6 | Parser edge cases (quotes, comments, multi-line, BOM, PEM) | tests | pass | yes | `tests/test_parser.py`, regressions |
| A7 | `--example-only` passes on the repo's own example | clean clone | pass | exit 0 | CI smoke step |
| A8 | README demo output is real | clean clone | pass | identical | README |

## Classification proposal

**Partially Verified** — all documented behaviour tested on macOS with
Python 3.10–3.13, the no-value-printed guarantee is now enforced by tests,
clean clone passes. Not verified: Linux/Windows CI on the audit branch
(pending push).
