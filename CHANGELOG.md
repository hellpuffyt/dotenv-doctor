# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- Values were printed despite the "no value is ever printed" promise: the
  placeholder finding echoed the value (`'Password'`, `'test'` are both
  placeholders and real weak passwords), and an invalid key — which can be a
  fragment of a pasted private key — was echoed in the syntax error.
- `KEY="value" # comment` swallowed every following line into one value,
  hiding later keys (false `missing-key` errors).
- An unterminated quote silently consumed the rest of the file; it is now a
  syntax error and parsing resumes on the next line.
- Text after a closing quote is reported instead of kept with the quotes.
- An unquoted multi-line PEM block produced one syntax error per line and,
  for lines ending in `=` padding, assignments named after key material.
- A UTF-8 byte-order mark made the first key invalid.
- An explicitly given `--example` that does not exist was silently skipped;
  it is now a usage error. A missing default example is noted on stderr.
- Non-UTF-8 or unreadable files crashed with a traceback (now exit 2).
- GitHub workflow-command output did not escape `%`, newlines, `:` and `,`.
- README told users to `pip install dotenv-doctor`, which installs an
  unrelated PyPI project.

### Added

- Exhaustive no-value-leak tests; token-shaped fixtures built at runtime.
- `SECURITY.md`, `.editorconfig`, `docs/PRODUCTION_READINESS.md`.

## [0.1.0] - 2026-08-30

First release.

### Added

- `.env` parser handling the cases real files contain: `export` prefixes,
  inline comments, `#` inside unquoted values, single and double quoting with
  escape expansion, values containing `=`, and multi-line quoted values such as
  PEM private keys.
- Example-contract checks: `missing-key` (error) and `undocumented-key`
  (warning).
- Value checks: `placeholder-value`, `weak-secret` (length and Shannon entropy,
  applied only to credential-shaped keys), and `unquoted-whitespace`.
- `secret-in-example`: nine live-credential shapes (AWS, GitHub, Slack, Stripe,
  OpenAI, Anthropic, Google, PEM private keys, JWTs) flagged when found in a
  committed example file.
- `duplicate-key` warning reporting every line a key is assigned on.
- `--example-only` mode: audits the example file for syntax errors and
  committed credentials without needing a real `.env`, skipping the placeholder
  rules that an example file is expected to trip.
- Three output formats — `text`, `json`, and `github` workflow commands.
- Exit codes `0` clean, `1` findings, `2` usage error, with `--strict` to
  promote warnings to failures.

### Security

- Values are never printed. Findings name the key and describe the problem, so
  running the tool in CI cannot leak a secret into build logs.

[0.1.0]: https://github.com/hellpuffyt/dotenv-doctor/releases/tag/v0.1.0
