"""The preview lists migrations without changing files or bypassing safety checks."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from migrate_safe.cli import main


def snapshot(directory: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("directory", [False, True])
def test_dry_run_lists_all_statements_without_writing(tmp_path, directory):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    first = migrations / "0001_users.sql"
    first.write_text(
        "CREATE TABLE users (id SERIAL PRIMARY KEY);\n"
        "ALTER TABLE users ADD COLUMN email TEXT;\n"
        "INSERT INTO users (email) VALUES ('[red]hello[/red]');\n",
        encoding="utf-8",
    )
    if directory:
        (migrations / "0002_remove.sql").write_text(
            "ALTER TABLE users DROP COLUMN email;", encoding="utf-8"
        )
    (tmp_path / "keep.txt").write_text("Unchanged sentinel", encoding="utf-8")
    before = snapshot(tmp_path)

    result = CliRunner().invoke(
        main, ["check", "--dry-run", str(migrations if directory else first)]
    )

    assert result.exit_code == (1 if directory else 0), result.output
    assert "not executed" in result.output
    # The Rich console wraps long paths at the terminal width (80 cols on CI),
    # inserting a newline inside the filename. Compare against the flattened
    # output so the assertions tolerate any line-wrapping.
    flat = "".join(result.output.splitlines())
    assert "0001_users.sql" in flat
    assert "CREATE TABLE users" in result.output
    assert "ADD COLUMN email" in result.output
    assert "[red]hello[/red]" in result.output
    if directory:
        assert flat.index("0001_users.sql") < flat.index("0002_remove.sql")
        assert "DROP COLUMN email" in result.output
    assert snapshot(tmp_path) == before


def test_dry_run_keeps_strict_warning_exit_code(tmp_path):
    migration = tmp_path / "warning.sql"
    migration.write_text("DROP TYPE status_enum;", encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(main, ["check", "--dry-run", str(migration)]).exit_code == 0
    strict = runner.invoke(main, ["check", "--dry-run", "--strict", str(migration)])
    assert strict.exit_code == 1
    assert "DROP TYPE status_enum" in strict.output


def test_dry_run_empty_directory(tmp_path):
    result = CliRunner().invoke(main, ["check", "--dry-run", str(tmp_path)])
    assert result.exit_code == 0
    assert "No .sql" in result.output
    assert not list(tmp_path.iterdir())
