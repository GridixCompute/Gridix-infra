"""Session 12.3 — every migration's upgrade() is expand-only (zero-downtime safe)."""

import ast
from pathlib import Path

_VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

# Ops that would lock out or crash currently-running code during a rolling deploy.
_DESTRUCTIVE = {"drop_column", "drop_table", "drop_constraint", "alter_column", "rename_table"}


def _upgrade_ops(source: str) -> set[str]:
    """Return the set of alembic op.* calls inside the module's upgrade() function."""
    tree = ast.parse(source)
    ops: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
            for call in ast.walk(node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "op"
                ):
                    ops.add(call.func.attr)
    return ops


def test_all_upgrades_are_additive() -> None:
    files = sorted(_VERSIONS.glob("[0-9]*.py"))
    assert files, "no migrations found"
    for path in files:
        ops = _upgrade_ops(path.read_text())
        destructive = ops & _DESTRUCTIVE
        assert not destructive, (
            f"{path.name} upgrade() uses non-expand ops {destructive}; "
            "forward migrations must be additive (expand/contract, see docs/DEPLOY.md)"
        )


def test_deploy_doc_exists() -> None:
    doc = Path(__file__).resolve().parents[1] / "docs" / "DEPLOY.md"
    assert doc.exists()
    assert "expand" in doc.read_text().lower()
