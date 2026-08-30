# Contributing

Thanks for taking a look.

## Getting set up

```bash
git clone https://github.com/hellpuffyt/dotenv-doctor
cd dotenv-doctor
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Before opening a pull request

All four must pass; CI runs the same commands.

```bash
pytest -q
ruff check .
mypy
pytest -q --cov=dotenv_doctor --cov-report=term-missing
```

## Adding a check

1. Write the rule as a pure function in `src/dotenv_doctor/checks.py`. It takes
   already-parsed data and returns `Finding` objects. It must not touch the
   filesystem.
2. Give it a stable kebab-case `code` — codes are part of the public interface,
   because people grep for them in CI logs.
3. Add tests for both directions: what it flags, **and** what it must not flag.
   Most of the value in this tool is in the false-positive guards, so a rule
   without a negative test will not be merged.
4. Document the code in the findings table in `README.md` and add a changelog
   entry.

## Design constraints

- **No runtime dependencies.** The tool has to be installable anywhere without
  argument. Development dependencies are fine.
- **Never print a value.** Findings name keys and describe problems. Printing a
  value would leak secrets into CI logs, which defeats the point of the tool.
- **The parser stays a parser.** It resolves text into entries and records
  ambiguity as a parse issue. Judgements belong in `checks.py`.

## Reporting a bug

A `.env` snippet that reproduces it is worth more than a description. Redact
real values — a placeholder of the same shape and length is enough.
