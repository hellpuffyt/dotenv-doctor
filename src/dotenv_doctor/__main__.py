"""Allow ``python -m dotenv_doctor``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
