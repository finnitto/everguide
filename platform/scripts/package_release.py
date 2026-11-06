from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
OUT_DIR = ROOT / "releases"
OUT_DIR.mkdir(exist_ok=True)
OUTPUT = OUT_DIR / f"everguide-v{VERSION}.zip"

EXCLUDED_DIRS = {
    ".git", ".next", "node_modules", ".venv", "venv", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
    "coverage", "htmlcov", "data", "uploads", "backups", "releases",
}
EXCLUDED_FILES = {".env", ".env.local", ".env.development", ".env.production",
                  ".DS_Store", "Thumbs.db"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".sqlite", ".db"}

def excluded(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if any(part in EXCLUDED_DIRS for part in rel.parts):
        return True
    if path.name in EXCLUDED_FILES:
        return True
    if path.name.startswith(".env.") and path.name != ".env.example":
        return True
    return path.suffix.lower() in EXCLUDED_SUFFIXES

with ZipFile(OUTPUT, "w", ZIP_DEFLATED, compresslevel=8) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file() and not excluded(path):
            archive.write(path, path.relative_to(ROOT))

print(f"Created {OUTPUT}")
print(f"Version: {VERSION}")
print("Secrets, Git metadata, dependencies, caches, build output and local data excluded.")
