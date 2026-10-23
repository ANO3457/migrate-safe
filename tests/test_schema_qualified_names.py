"""Schema qualifiers must not hide findings or truncate object names."""

import os
import subprocess
import sys

import pytest
from click.testing import CliRunner

from migrate_safe.cli import main
from migrate_safe.detectors import Severity, analyze_migration
from migrate_safe.parser import StatementType, parse_sql_file

NAMES = [
    "public.users",
    '"public"."users"',
    '"tenant data"."user accounts"',
    "`billing`.`users`",
    "tenant$one.users$archive",
    '"ten""ant"."us""ers"',
    "public . users",
]
STATEMENTS = [
    ("ALTER TABLE {name} DROP COLUMN email", StatementType.DROP_COLUMN, Severity.UNSAFE),
    (
        "ALTER TABLE {name} RENAME COLUMN email TO address",
        StatementType.RENAME_COLUMN,
        Severity.CRITICAL,
    ),
    (
        "ALTER TABLE {name} ADD COLUMN phone TEXT NOT NULL",
        StatementType.ADD_COLUMN,
        Severity.UNSAFE,
    ),
    (
        "ALTER TABLE {name} ALTER COLUMN age TYPE INTEGER",
        StatementType.ALTER_COLUMN_TYPE,
        Severity.WARNING,
    ),
    ("DROP TABLE {name}", StatementType.DROP_TABLE, Severity.WARNING),
    ("DROP TYPE {name}", StatementType.DROP_TYPE, Severity.WARNING),
    ("CREATE TABLE {name} (id INTEGER)", StatementType.CREATE_TABLE, None),
]


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("template, kind, severity", STATEMENTS)
def test_qualified_names_through_parser_and_detectors(tmp_path, name, template, kind, severity):
    path = tmp_path / "migration.sql"
    path.write_text(template.format(name=name) + ";", encoding="utf-8")
    migration = parse_sql_file(path)
    assert len(migration.statements) == 1
    assert migration.statements[0].type == kind
    assert migration.statements[0].table == name
    findings = analyze_migration(migration)
    if severity is None:
        assert findings == []
    else:
        assert len(findings) == 1
        assert findings[0].severity == severity
        assert f"`{name}`" in findings[0].message


@pytest.mark.parametrize("name", ["users", "public.users", '"public"."users"'])
@pytest.mark.parametrize(
    "template, kind",
    [
        ("ALTER TABLE IF EXISTS {name} DROP COLUMN email", StatementType.DROP_COLUMN),
        ("DROP TABLE IF EXISTS {name}", StatementType.DROP_TABLE),
        ("DROP TYPE IF EXISTS {name}", StatementType.DROP_TYPE),
        ("CREATE TABLE IF NOT EXISTS {name} (id INTEGER)", StatementType.CREATE_TABLE),
    ],
)
def test_guarded_object_names(tmp_path, name, template, kind):
    path = tmp_path / "guarded.sql"
    path.write_text(template.format(name=name), encoding="utf-8")
    statement = parse_sql_file(path).statements[0]
    assert statement.type == kind
    assert statement.table == name


@pytest.mark.parametrize("name", ["users", '"users"', "`users`", "'users'"])
@pytest.mark.parametrize("template, kind", [(s[0], s[1]) for s in STATEMENTS])
def test_simple_names_keep_legacy_representation(tmp_path, name, template, kind):
    path = tmp_path / "legacy.sql"
    path.write_text(template.format(name=name), encoding="utf-8")
    statement = parse_sql_file(path).statements[0]
    assert statement.type == kind
    assert statement.table == "users"


@pytest.mark.parametrize(
    "name", ["public.", "public.users-extra", '"public"."unterminated', '"unclosed']
)
@pytest.mark.parametrize("template", ["DROP TABLE {name}", "DROP TYPE {name}"])
def test_incomplete_identifiers_are_not_truncated(tmp_path, name, template):
    path = tmp_path / "invalid.sql"
    path.write_text(template.format(name=name), encoding="utf-8")
    statement = parse_sql_file(path).statements[0]
    assert statement.type == StatementType.OTHER
    assert statement.table == ""


def test_schema_qualified_directory_keeps_all_five_findings(tmp_path):
    statements = [
        "ALTER TABLE public.users DROP COLUMN email;",
        "ALTER TABLE public.users RENAME COLUMN a TO b;",
        "ALTER TABLE public.users ADD COLUMN phone TEXT NOT NULL;",
        "DROP TABLE public.orders;",
        "DROP TYPE public.user_role;",
    ]
    findings = []
    for i, sql in enumerate(statements):
        path = tmp_path / f"{i:04}.sql"
        path.write_text(sql, encoding="utf-8")
        findings.extend(analyze_migration(parse_sql_file(path)))
    assert len(findings) == 5
    assert [f.severity for f in findings] == [
        Severity.UNSAFE,
        Severity.CRITICAL,
        Severity.UNSAFE,
        Severity.WARNING,
        Severity.WARNING,
    ]
    for options in ([], ["--strict"]):
        result = CliRunner().invoke(main, ["check", *options, str(tmp_path)])
        assert result.exit_code == 1, result.output
    process = subprocess.run(
        [sys.executable, "-m", "migrate_safe.cli", "check", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert process.returncode == 1, process.stdout + process.stderr
    assert "Traceback" not in process.stderr
