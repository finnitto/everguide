import hashlib
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile

import pytest


PLATFORM_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PLATFORM_ROOT / "scripts" / "package_release.py"
SPEC = importlib.util.spec_from_file_location("everguide_package_release", SCRIPT_PATH)
package_release = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(package_release)


def _release_source(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for relative in package_release.REQUIRED_FILES:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative == "VERSION":
            target.write_text("2.8.0\n", encoding="utf-8")
        elif relative == "RELEASE-MANIFEST.json":
            target.write_text(json.dumps({"version": "2.8.0"}), encoding="utf-8")
        else:
            target.write_text(f"fixture: {relative}\n", encoding="utf-8")
    return root


def test_release_archive_contains_required_files_and_excludes_secrets_and_local_state(tmp_path):
    root = _release_source(tmp_path / "platform")
    (root / ".env").write_text("PRODUCTION_SECRET=do-not-package", encoding="utf-8")
    (root / ".env.production").write_text("SECRET=do-not-package", encoding="utf-8")
    (root / ".env.example").write_text("APP_ENV=example", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "candidate.parquet").write_bytes(b"local candidate data")
    (root / "pgdata").mkdir()
    (root / "pgdata" / "database.db").write_bytes(b"local database")
    (root / "apps" / "web" / "node_modules" / "pkg").mkdir(parents=True)
    (root / "apps" / "web" / "node_modules" / "pkg" / "index.js").write_text("dependency", encoding="utf-8")
    (root / "apps" / "web" / ".next").mkdir()
    (root / "apps" / "web" / ".next" / "server.js").write_text("build output", encoding="utf-8")
    (root / "secrets").mkdir()
    (root / "secrets" / "private.pem").write_text("private key", encoding="utf-8")

    archive_path = tmp_path / "out" / "everguide-test.zip"
    result = package_release.build_release_archive(
        root=root,
        output_path=archive_path,
        source_commit="test-source-commit",
    )

    assert archive_path.exists()
    assert result["source_commit"] == "test-source-commit"
    assert result["version"] == "2.8.0"
    assert result["file_count"] >= len(package_release.REQUIRED_FILES)

    with ZipFile(archive_path, "r") as archive:
        assert archive.testzip() is None
        names = set(archive.namelist())

    assert set(package_release.REQUIRED_FILES).issubset(names)
    assert ".env.example" in names
    assert ".env" not in names
    assert ".env.production" not in names
    assert not any(name.startswith("data/") for name in names)
    assert not any(name.startswith("pgdata/") for name in names)
    assert not any("/node_modules/" in name for name in names)
    assert not any("/.next/" in name for name in names)
    assert "secrets/private.pem" not in names

    actual_digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    assert actual_digest == result["sha256"]
    assert result["checksum_path"]
    assert Path(result["checksum_path"]).read_text(encoding="utf-8").startswith(actual_digest)
    package_manifest = json.loads(Path(result["package_manifest_path"]).read_text(encoding="utf-8"))
    assert package_manifest["source_commit"] == "test-source-commit"
    assert package_manifest["sha256"] == actual_digest


def test_release_archive_is_reproducible_for_identical_source(tmp_path):
    root = _release_source(tmp_path / "platform")
    (root / "app.py").write_text("print('stable')\n", encoding="utf-8")

    first = package_release.build_release_archive(
        root=root,
        output_path=tmp_path / "first" / "everguide.zip",
        source_commit="same-commit",
    )
    second = package_release.build_release_archive(
        root=root,
        output_path=tmp_path / "second" / "everguide.zip",
        source_commit="same-commit",
    )

    assert first["sha256"] == second["sha256"]
    assert (tmp_path / "first" / "everguide.zip").read_bytes() == (
        tmp_path / "second" / "everguide.zip"
    ).read_bytes()


def test_release_archive_fails_when_required_migration_is_missing(tmp_path):
    root = _release_source(tmp_path / "platform")
    (root / "apps" / "api" / "migrations" / "versions" / "0023_stage3_evidence_domains.py").unlink()

    with pytest.raises(RuntimeError, match="missing required files"):
        package_release.build_release_archive(
            root=root,
            output_path=tmp_path / "out" / "everguide.zip",
            source_commit="test-source-commit",
        )
