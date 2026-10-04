from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from scripts import compare_explanation_v2


class _Response:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.operations = []

    def select(self, columns):
        self.operations.append(("select", columns))
        return self

    def eq(self, field, value):
        self.operations.append(("eq", field, value))
        return self

    def order(self, field, desc=False):
        self.operations.append(("order", field, desc))
        return self

    def limit(self, value):
        self.operations.append(("limit", value))
        return self

    def execute(self):
        self.operations.append(("execute",))
        return _Response(self.rows)


class _Client:
    def __init__(self, rows):
        self.query = _Query(rows)

    def table(self, name):
        self.query.operations.append(("table", name))
        return self.query


def test_latest_directive_query_is_select_only_and_scoped_to_exact_content_id():
    client = _Client([{"id": "dir-1", "paper_id": "paper-1", "cuts": []}])

    row = compare_explanation_v2.latest_directive(client, "paper", "paper-1")

    assert row["id"] == "dir-1"
    assert client.query.operations == [
        ("table", "directives"),
        ("select", "id, paper_id, version_type, header, cuts, status, created_at"),
        ("eq", "paper_id", "paper-1"),
        ("order", "created_at", True),
        ("limit", 1),
        ("execute",),
    ]


def test_cli_rejects_blank_content_id_before_database_access():
    with pytest.raises(ValueError, match="content_id_required"):
        compare_explanation_v2.latest_directive(_Client([]), "report", "")


def test_script_help_runs_from_repository_root():
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "scripts/compare_explanation_v2.py", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--with-model" in completed.stdout
