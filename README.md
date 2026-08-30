# dotenv-doctor

Validate `.env` files against a committed `.env.example` — catching the
configuration mistakes that only surface after a deploy.

[![CI](https://github.com/hellpuffyt/dotenv-doctor/actions/workflows/ci.yml/badge.svg)](https://github.com/hellpuffyt/dotenv-doctor/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## What is it?

A dependency-free CLI that reads your `.env` files and tells you what is wrong
with them before your application does.

```console
$ dotenv-doctor
.env
  error - DATABASE_URL: declared in the example file but absent here [missing-key]
  error line 1 API_KEY: value 'changeme' looks like an unfilled placeholder [placeholder-value]
  warning line 3 LEGACY_FLAG: set here but missing from the example file [undocumented-key]

2 error(s), 1 warning(s) across 1 file(s)
$ echo $?
1
```

A `-` in place of a line number means the finding is about the file as a whole
— a key that should be present and simply is not.

## Why does it exist?

`.env.example` is a promise: *these are the variables this service needs.* Nothing
enforces it. The file drifts, and the failure modes all look the same from the
outside — a service that boots fine locally and dies in staging.

The specific mistakes this catches, all of which are ordinary and all of which
are invisible until runtime:

- A new required variable was added to `.env.example` but never to the deploy
  environment.
- A placeholder like `changeme` was committed and then shipped as if real.
- A *real* credential was pasted into `.env.example` and committed to git.
- A key is assigned twice in one file and the earlier value is silently ignored.
- A value has trailing whitespace that the loader keeps and the API rejects.

Existing linters mostly check syntax. This checks the *relationship* between
your real environment and the contract your repository publishes.

## Features

- **Example-contract checking** — missing keys are errors, undocumented keys are
  warnings.
- **Placeholder detection** — a curated list of ~25 template values, matched
  against the whole value so a real secret containing `changeme` is not flagged.
- **Weak-secret detection** — for credential-shaped keys only, combining length
  and Shannon entropy. `PORT=3000` is short and low-entropy, and is correctly
  left alone.
- **Committed-credential detection** — nine live-credential shapes (AWS, GitHub,
  Slack, Stripe, OpenAI, Anthropic, Google, PEM private keys, JWTs) flagged as
  errors when found in the example file.
- **A parser that handles the awkward cases** — `export` prefixes, inline
  comments, `pass#word`, single vs double quoting with escapes, values
  containing `=`, and multi-line quoted values such as PEM keys.
- **Three output formats** — human text, JSON for tooling, and GitHub Actions
  workflow commands that annotate the diff directly.
- **Meaningful exit codes** — `0` clean, `1` findings, `2` usage error.
- **Zero runtime dependencies.**

## Architecture

Four modules, each independently testable:

```
src/dotenv_doctor/
├── parser.py    text  → entries + parse issues   (no rules, no I/O opinions)
├── checks.py    parsed data → findings           (pure functions, no filesystem)
├── report.py    findings → text / JSON / GitHub  (no logic, only rendering)
└── cli.py       argument parsing and wiring      (the only module doing I/O)
```

The split exists so the rule set can be tested without touching a filesystem,
and so a new output format never risks changing a rule's behaviour.

`parser.py` deliberately implements the *intersection* of what mainstream `.env`
loaders agree on (python-dotenv, docker-compose, foreman, direnv) rather than
inventing a shell parser. Anything genuinely ambiguous is recorded as a parse
issue instead of guessed at.

## Installation

```bash
pip install dotenv-doctor
```

From source:

```bash
git clone https://github.com/hellpuffyt/dotenv-doctor
cd dotenv-doctor
pip install -e ".[dev]"
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```bash
# Check ./.env against ./.env.example
dotenv-doctor

# Check several environment files at once
dotenv-doctor .env.staging .env.production

# A differently named reference file
dotenv-doctor --example env.sample

# Fail the build on warnings too
dotenv-doctor --strict

# Skip keys that are intentionally environment-only
dotenv-doctor --ignore SENTRY_DSN,BUILD_SHA

# Check syntax and values only, ignoring the example contract
dotenv-doctor --no-example
```

Run `dotenv-doctor --help` for the full option list.

### Options

| Option | Description |
| --- | --- |
| `-e`, `--example PATH` | Reference file (default `.env.example`) |
| `-f`, `--format FORMAT` | `text`, `json`, or `github` (default `text`) |
| `--strict` | Treat warnings as failures |
| `--ignore KEYS` | Comma-separated keys to skip |
| `--no-example` | Skip the example-contract comparison |
| `--example-only` | Audit the example file alone (syntax + committed credentials) |
| `--no-colour` | Disable ANSI colour |
| `-V`, `--version` | Print the version |

## Examples

**JSON output**, for piping into other tooling:

```console
$ dotenv-doctor --format json
{
  "summary": { "files": 1, "errors": 1, "warnings": 0 },
  "files": [
    {
      "path": ".env",
      "errors": 1,
      "warnings": 0,
      "findings": [
        {
          "code": "missing-key",
          "severity": "error",
          "key": "DATABASE_URL",
          "line": null,
          "message": "declared in the example file but absent here"
        }
      ]
    }
  ]
}
```

**GitHub Actions output**, which annotates the file in the pull request:

```console
$ dotenv-doctor --format github
::error file=.env,title=missing-key::DATABASE_URL: declared in the example file but absent here
```

## Configuration

There is no configuration file, by design — everything is a flag, so a check is
reproducible from the command line alone. For repeated invocations, put the
flags in a `Makefile` target or your CI step.

## Findings reference

| Code | Severity | Meaning |
| --- | --- | --- |
| `missing-key` | error | In the example file, absent from the checked file |
| `placeholder-value` | error / warning | Unfilled template value; error when the key is credential-shaped |
| `secret-in-example` | error | A real credential shape found in the committed example |
| `syntax` | error | Line is not a valid assignment |
| `undocumented-key` | warning | Set in the real file, missing from the example |
| `duplicate-key` | warning | Assigned more than once; the last assignment wins |
| `weak-secret` | warning | Credential-shaped key with a short or low-entropy value |
| `unquoted-whitespace` | warning | Leading or trailing whitespace without quoting |

## Testing

```bash
pytest                       # the suite
pytest --cov=dotenv_doctor   # with coverage
ruff check .                 # lint
mypy                         # type check (strict)
```

The suite covers the parser's edge cases (quoting, escapes, multi-line values,
inline comments), each rule in isolation including its false-positive guards,
and the CLI end to end through a temporary directory.

## Deployment

Use it as a CI gate. With the `github` format, findings appear as inline
annotations on the pull request:

```yaml
- name: No credentials committed in the example file
  run: |
    pip install dotenv-doctor
    dotenv-doctor --format github --example-only
```

`--example-only` is the variant that works in a public CI job: it audits the
committed example file for syntax errors and real credentials **without needing
a real `.env` to exist**, and it skips the placeholder rules — an example file
is meant to be full of placeholders, so flagging them there would be noise.

To validate a real deployment environment instead, check the actual file:

```yaml
- name: Validate environment contract
  run: dotenv-doctor --format github --strict .env.production
```

## Security

- **No value is ever printed.** Findings name the key and describe the problem;
  the value itself never reaches stdout, so running this in CI cannot leak a
  secret into build logs.
- **Nothing is sent anywhere.** No network access, no telemetry, no runtime
  dependencies.
- **Credential detection is shape-based**, using published prefix formats. It
  will not catch a credential with no recognisable shape — treat it as a safety
  net, not a guarantee.
- `.gitignore` excludes `.env` and `.env.*` while keeping `.env.example`.

## Roadmap

- A `--fix` mode that appends missing keys to `.env` as commented stubs.
- Type annotations in the example file (`PORT=  # int`) with value validation.
- Pre-commit hook definition.

## License

MIT — see [LICENSE](LICENSE).
