import ast
from pathlib import Path


def _revision_values(filename):
    migration = Path(__file__).parents[1] / "migrations" / "versions" / filename
    tree = ast.parse(migration.read_text(encoding="utf-8"))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in {"revision", "down_revision"}:
                values[node.targets[0].id] = ast.literal_eval(node.value)
    return values


def test_overture_migration_revision_fits_default_alembic_version_column():
    values = _revision_values("0020_overture_production_pipeline.py")
    assert len(values["revision"]) <= 32
    assert values["revision"] == "0020_overture_feed"
    assert values["down_revision"] == "0019_identity_assessment_runs"


def test_stage3_migration_revision_fits_and_follows_previous_head():
    values = _revision_values("0023_stage3_evidence_domains.py")
    assert len(values["revision"]) <= 32
    assert values["revision"] == "0023_stage3_evidence"
    assert values["down_revision"] == "0022_branch_overture_provenance"