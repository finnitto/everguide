"""Build and verify a deterministic Everguide release archive.

The package is built from the maintained platform/ tree only. It excludes
secrets, local state, dependency trees, caches and build outputs, then writes
an SHA-256 checksum and a source-commit manifest beside the archive.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
COMPRESSION_LEVEL = 8

EXCLUDED_DIRS = {
    ".git", ".next", "node_modules", ".venv", "venv", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
    "coverage", "htmlcov", "data", "uploads", "backups", "releases",
    "postgres_data", "pgdata", "postgres", "quality_review", "test-output",
    "test-results", "logs", "tmp", "temp", ".ssh", ".aws", ".azure",
    ".gnupg", "private_keys", "certificates", "certs", "secrets",
}
EXCLUDED_FILES = {
    ".env", ".npmrc", ".pypirc", ".netrc", "auth.json", "credentials",
    "credentials.json", "secrets.json", "id_rsa", "id_ed25519",
    "known_hosts", ".DS_Store", "Thumbs.db",
}
EXCLUDED_SUFFIXES = {
    ".pyc", ".pyo", ".log", ".sqlite", ".sqlite3", ".db", ".bak",
    ".backup", ".dump", ".tmp", ".parquet", ".gpkg", ".pem", ".key",
    ".p12", ".pfx", ".jks", ".zip", ".tar", ".gz", ".env",
}
REQUIRED_FILES = (
    "VERSION",
    "README.md",
    "RELEASE-MANIFEST.json",
    "docker-compose.yml",
    "apps/api/migrations/versions/0023_stage3_evidence_domains.py",
    "apps/web/package-lock.json",
    "docs/FIVE-STAGE-ACCEPTANCE-PLAN.md",
    "docs/STAGE3-EVIDENCE-DATA-DICTIONARY.md",
    "docs/REVIEWER-CREDENTIAL-OPERATIONS.md",
    "docs/VALIDATION.md",
    "scripts/package_release.py",
    "scripts/validate.sh",
    "scripts/validate-docker.sh",
)


def is_excluded(path: Path, root: Path = ROOT) -> bool:
    """Return True for secret, local-state, generated or external-symlink paths."""
    if path.is_symlink():
        return True
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True

    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return True
    if path.name in EXCLUDED_FILES:
        return True
    if path.name.startswith(".env.") and not path.name.endswith(".example"):
        return True
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return True
    return False


def _source_commit(root: Path) -> str:
    configured = os.environ.get("GITHUB_SHA", "").strip()
    if configured:
        return configured
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _validate_archive(output: Path, version: str) -> list[str]:
    with ZipFile(output, "r") as archive:
        corrupt_member = archive.testzip()
        if corrupt_member is not None:
            raise RuntimeError(f"Corrupt ZIP member: {corrupt_member}")

        names = archive.namelist()
        if len(names) != len(set(names)):
            raise RuntimeError("Release archive contains duplicate member paths")
        name_set = set(names)

        missing = sorted(set(REQUIRED_FILES) - name_set)
        if missing:
            raise RuntimeError(f"Release archive is missing required files: {missing}")

        for name in names:
            member_path = Path(name)
            if is_excluded(member_path, root=Path(".")):
                raise RuntimeError(f"Release archive contains excluded path: {name}")

        manifest = json.loads(archive.read("RELEASE-MANIFEST.json"))
        if str(manifest.get("version", "")).strip() != version:
            raise RuntimeError("RELEASE-MANIFEST.json version does not match VERSION")
        if archive.read("VERSION").decode("utf-8").strip() != version:
            raise RuntimeError("VERSION file does not match the package version")

        return names


def build_release_archive(
    root: Path = ROOT,
    output_path: Path | None = None,
    source_commit: str | None = None,
) -> dict:
    """Build a deterministic ZIP and adjacent checksum/package manifest."""
    root = root.resolve()
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not version:
        raise ValueError("VERSION must not be empty")

    manifest_path = root / "RELEASE-MANIFEST.json"
    release_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if str(release_manifest.get("version", "")).strip() != version:
        raise ValueError("RELEASE-MANIFEST.json version does not match VERSION")

    if output_path is None:
        output_dir = root / "releases"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"everguide-v{version}.zip"
    else:
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

    files = sorted(
        (
            candidate for candidate in root.rglob("*")
            if candidate.is_file() and not is_excluded(candidate, root)
        ),
        key=lambda candidate: candidate.relative_to(root).as_posix(),
    )
    members = {candidate.relative_to(root).as_posix() for candidate in files}
    missing = sorted(set(REQUIRED_FILES) - members)
    if missing:
        raise RuntimeError(f"Release source is missing required files: {missing}")

    # Fixed timestamps, stable ordering and stable file permissions make the ZIP
    # reproducible for identical source content and compression implementation.
    with ZipFile(
        output_path,
        mode="w",
        compression=ZIP_DEFLATED,
        compresslevel=COMPRESSION_LEVEL,
    ) as archive:
        archive.comment = b""
        for candidate in files:
            relative_name = candidate.relative_to(root).as_posix()
            info = ZipInfo(relative_name, date_time=ZIP_TIMESTAMP)
            info.create_system = 3
            info.compress_type = ZIP_DEFLATED
            file_mode = stat.S_IMODE(candidate.stat().st_mode)
            info.external_attr = (stat.S_IFREG | file_mode) << 16
            archive.writestr(
                info,
                candidate.read_bytes(),
                compress_type=ZIP_DEFLATED,
                compresslevel=COMPRESSION_LEVEL,
            )

    names = _validate_archive(output_path, version)
    archive_bytes = output_path.read_bytes()
    digest = hashlib.sha256(archive_bytes).hexdigest()
    checksum_path = output_path.with_name(output_path.name + ".sha256")
    checksum_path.write_text(f"{digest}  {output_path.name}\n", encoding="utf-8")

    commit = source_commit or _source_commit(root)
    package_manifest = {
        "product": "Everguide",
        "version": version,
        "archive": output_path.name,
        "source_commit": commit,
        "sha256": digest,
        "size_bytes": len(archive_bytes),
        "file_count": len(names),
        "required_files": list(REQUIRED_FILES),
        "exclusions": {
            "directories": sorted(EXCLUDED_DIRS),
            "filenames": sorted(EXCLUDED_FILES),
            "suffixes": sorted(EXCLUDED_SUFFIXES),
            "environment_files": "Only .env.example and other *.example environment templates are eligible for inclusion.",
            "symlinks": "Excluded",
        },
    }
    package_manifest_path = output_path.with_suffix(".package-manifest.json")
    package_manifest_path.write_text(
        json.dumps(package_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return {
        **package_manifest,
        "output_path": str(output_path),
        "checksum_path": str(checksum_path),
        "package_manifest_path": str(package_manifest_path),
    }


def main() -> None:
    result = build_release_archive()
    print(f"Created {result['output_path']}")
    print(f"Version: {result['version']}")
    print(f"Source commit: {result['source_commit']}")
    print(f"Files: {result['file_count']}")
    print(f"Size: {result['size_bytes']} bytes")
    print(f"SHA-256: {result['sha256']}")
    print(f"Checksum: {result['checksum_path']}")
    print(f"Package manifest: {result['package_manifest_path']}")
    print("ZIP integrity, required content and exclusion checks passed.")


if __name__ == "__main__":
    main()
