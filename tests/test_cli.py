"""End-to-end CLI behaviour: exit codes, formats, and file handling."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dotenv_doctor.cli import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, main


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def write(path: Path, name: str, content: str) -> Path:
    target = path / name
    target.write_text(content, encoding="utf-8")
    return target


class TestExitCodes:
    def test_clean_project_exits_zero(self, project: Path) -> None:
        write(project, ".env.example", "API_KEY=\nPORT=\n")
        write(project, ".env", "API_KEY=xJ3$kQ9zPw27Lm4TbVn8\nPORT=3000\n")
        assert main([]) == EXIT_OK

    def test_missing_key_exits_one(self, project: Path) -> None:
        write(project, ".env.example", "API_KEY=\nPORT=\n")
        write(project, ".env", "API_KEY=xJ3$kQ9zPw27Lm4TbVn8\n")
        assert main([]) == EXIT_FINDINGS

    def test_warnings_alone_pass_without_strict(self, project: Path) -> None:
        write(project, ".env.example", "PORT=\n")
        write(project, ".env", "PORT=3000\nEXTRA=1\n")
        assert main([]) == EXIT_OK

    def test_warnings_fail_under_strict(self, project: Path) -> None:
        write(project, ".env.example", "PORT=\n")
        write(project, ".env", "PORT=3000\nEXTRA=1\n")
        assert main(["--strict"]) == EXIT_FINDINGS

    def test_no_target_is_a_usage_error(self, project: Path) -> None:
        assert main([]) == EXIT_USAGE

    def test_missing_named_file_is_a_usage_error(self, project: Path) -> None:
        assert main(["nope.env"]) == EXIT_USAGE


class TestFormats:
    def test_json_output_is_valid_and_structured(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write(project, ".env.example", "API_KEY=\nPORT=\n")
        write(project, ".env", "PORT=3000\n")
        assert main(["--format", "json"]) == EXIT_FINDINGS

        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["errors"] >= 1
        findings = payload["files"][0]["findings"]
        assert any(f["code"] == "missing-key" and f["key"] == "API_KEY" for f in findings)

    def test_github_format_emits_workflow_commands(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write(project, ".env.example", "API_KEY=\n")
        write(project, ".env", "")
        main(["--format", "github"])
        assert "::error " in capsys.readouterr().out

    def test_text_output_names_the_file(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write(project, ".env.example", "PORT=\n")
        write(project, ".env", "PORT=3000\n")
        main([])
        assert ".env" in capsys.readouterr().out

    def test_missing_key_is_not_printed_twice(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A finding with no line number must not render the key as both its
        # location and its name.
        write(project, ".env.example", "DATABASE_URL=\n")
        write(project, ".env", "")
        main(["--no-colour"])
        line = next(
            row
            for row in capsys.readouterr().out.splitlines()
            if "missing-key" in row
        )
        assert line.count("DATABASE_URL") == 1


class TestOptions:
    def test_ignore_suppresses_a_key(self, project: Path) -> None:
        write(project, ".env.example", "API_KEY=\nPORT=\n")
        write(project, ".env", "PORT=3000\n")
        assert main(["--ignore", "API_KEY"]) == EXIT_OK

    def test_no_example_skips_comparison(self, project: Path) -> None:
        write(project, ".env.example", "API_KEY=\n")
        write(project, ".env", "PORT=3000\n")
        assert main(["--no-example"]) == EXIT_OK

    def test_custom_example_path_is_honoured(self, project: Path) -> None:
        write(project, "env.sample", "PORT=\n")
        write(project, ".env", "PORT=3000\n")
        assert main(["--example", "env.sample"]) == EXIT_OK

    def test_multiple_files_are_all_checked(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write(project, ".env.example", "PORT=\n")
        write(project, ".env.dev", "PORT=3000\n")
        write(project, ".env.prod", "PORT=8080\n")
        assert main([".env.dev", ".env.prod", "--format", "json"]) == EXIT_OK

        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["files"] == 2

    def test_example_only_passes_on_a_placeholder_example(
        self, project: Path
    ) -> None:
        # Placeholders are exactly what an example file should contain.
        write(project, ".env.example", "API_KEY=\nPORT=3000\nTOKEN=changeme\n")
        assert main(["--example-only"]) == EXIT_OK

    def test_example_only_fails_on_a_committed_credential(
        self, project: Path
    ) -> None:
        write(project, ".env.example", "AWS_KEY=AKIAIOSFODNN7EXAMPLE\n")
        assert main(["--example-only"]) == EXIT_FINDINGS

    def test_example_only_fails_on_a_syntax_error(self, project: Path) -> None:
        write(project, ".env.example", "NOT_AN_ASSIGNMENT\n")
        assert main(["--example-only"]) == EXIT_FINDINGS

    def test_example_only_needs_no_real_env_file(self, project: Path) -> None:
        # No .env exists at all; the audit must still run.
        write(project, ".env.example", "API_KEY=\n")
        assert not (project / ".env").exists()
        assert main(["--example-only"]) == EXIT_OK

    def test_example_only_reports_a_missing_example(self, project: Path) -> None:
        assert main(["--example-only"]) == EXIT_USAGE

    def test_example_only_honours_a_custom_path(self, project: Path) -> None:
        write(project, "env.sample", "AWS_KEY=AKIAIOSFODNN7EXAMPLE\n")
        assert main(["--example-only", "--example", "env.sample"]) == EXIT_FINDINGS

    def test_secret_left_in_example_fails_the_run(self, project: Path) -> None:
        write(project, ".env.example", "AWS_KEY=AKIAIOSFODNN7EXAMPLE\n")
        write(project, ".env", "AWS_KEY=xJ3$kQ9zPw27Lm4TbVn8\n")
        assert main([]) == EXIT_FINDINGS
