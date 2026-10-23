"""Explain must return the same safety verdict as check on real SQL files."""

import os
import subprocess
import sys

import pytest
from click.testing import CliRunner

from migrate_safe.cli import main


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize(
    "sql, marker, expected",
    [
        ("CREATE TABLE users (id INTEGER);", "no issues", 0),
        ("DROP TABLE users;", "WARNING", 0),
        ("ALTER TABLE users DROP COLUMN email;", "UNSAFE", 1),
        ("ALTER TABLE users RENAME COLUMN email TO address;", "CRITICAL", 1),
    ],
)
def test_explain_verdict_matches_check(tmp_path, strict, sql, marker, expected):
    path = tmp_path / "migration.sql"
    path.write_text(sql, encoding="utf-8")
    options = ["--strict"] if strict else []
    if strict and marker == "WARNING":
        expected = 1
    runner = CliRunner()
    checked = runner.invoke(main, ["check", *options, str(path)])
    explained = runner.invoke(main, ["explain", *options, str(path)])

    assert checked.exit_code == expected, checked.output
    assert explained.exit_code == expected, explained.output
    assert marker in explained.output


@pytest.mark.parametrize("strict", [False, True])
def test_explain_empty_directory_succeeds(tmp_path, strict):
    options = ["--strict"] if strict else []
    result = CliRunner().invoke(main, ["explain", *options, str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "No .sql" in result.output


def test_explain_directory_reports_all_files_and_fails(tmp_path):
    (tmp_path / "0001_unsafe.sql").write_text(
        "ALTER TABLE users DROP COLUMN email;", encoding="utf-8"
    )
    (tmp_path / "0002_safe.sql").write_text(
        "CREATE TABLE teams (id INTEGER);", encoding="utf-8"
    )
    (tmp_path / "0003_warning.sql").write_text("DROP TABLE teams;", encoding="utf-8")

    result = CliRunner().invoke(main, ["explain", str(tmp_path)])

    assert result.exit_code == 1, result.output
    for name in ("0001_unsafe.sql", "0002_safe.sql", "0003_warning.sql"):
        assert name in result.output
    assert "UNSAFE" in result.output
    assert "WARNING" in result.output


@pytest.mark.parametrize(
    "sql, options, expected",
    [
        ("ALTER TABLE users RENAME COLUMN email TO address;", [], 1),
        ("DROP TABLE users;", ["--strict"], 1),
        ("DROP TABLE users;", [], 0),
    ],
)
def test_explain_process_exit_code(tmp_path, sql, options, expected):
    path = tmp_path / "migration.sql"
    path.write_text(sql, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "migrate_safe.cli", "explain", *options, str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=False,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert "MIGRATE-SAFE" in result.stdout
