import ast
from pathlib import Path


def test_latest_migration_revision_fits_default_alembic_version_column():
    migration = Path(__file__).parents[1] / "migrations" / "versions" / "0020_overture_production_pipeline.py"
    tree = ast.parse(migration.read_text(encoding="utf-8"))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in {"revision", "down_revision"}:
                values[node.targets[0].id] = ast.literal_eval(node.value)
    assert len(values["revision"]) <= 32
    assert values["revision"] == "0020_overture_feed"
    assert values["down_revision"] == "0019_identity_assessment_runs"
