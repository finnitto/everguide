from pathlib import Path

changes = {
    "apps/api/app/routers/discovery.py": [
        (
            "def start_discovery(db: Session = Depends(get_db)):\n",
            "def start_discovery(db: Session = Depends(get_db)):\n"
            '    raise HTTPException(status_code=410, detail="Google Places discovery is disabled. Overture is the sole source of initial discovery candidates.")\n'
        ),
    ],
    "apps/api/app/routers/companies_house.py": [
        (
            "def start_import(db: Session = Depends(get_db)):\n",
            "def start_import(db: Session = Depends(get_db)):\n"
            '    raise HTTPException(status_code=410, detail="Independent Companies House candidate discovery is disabled. Overture is the sole source of initial discovery candidates.")\n'
        ),
        (
            "def start_profile_enrichment(db: Session = Depends(get_db)):\n",
            "def start_profile_enrichment(db: Session = Depends(get_db)):\n"
            '    raise HTTPException(status_code=410, detail="Independent Companies House enrichment is disabled pending the Overture-led workflow.")\n'
        ),
    ],
    "apps/api/app/routers/company_websites.py": [
        (
            "def start_run(db: Session = Depends(get_db)):\n",
            "def start_run(db: Session = Depends(get_db)):\n"
            '    raise HTTPException(status_code=410, detail="Independent company website discovery is disabled pending the Overture-led workflow.")\n'
        ),
        (
            "def resume_run(run_id: int, db: Session = Depends(get_db)):\n",
            "def resume_run(run_id: int, db: Session = Depends(get_db)):\n"
            '    raise HTTPException(status_code=410, detail="Legacy company website discovery runs cannot be resumed.")\n'
        ),
    ],
    "apps/api/app/routers/website_discovery.py": [
        (
            "def start_run():\n",
            "def start_run():\n"
            '    raise HTTPException(status_code=410, detail="Independent regional website discovery is disabled. Overture is the sole source of initial discovery candidates.")\n'
        ),
        (
            "def start_verification_run(db: Session = Depends(get_db)):\n",
            "def start_verification_run(db: Session = Depends(get_db)):\n"
            '    raise HTTPException(status_code=410, detail="Legacy website candidate verification is disabled pending the Overture-led workflow.")\n'
        ),
    ],
}

for filename, replacements in changes.items():
    path = Path(filename)
    original = path.read_text(encoding="utf-8")
    updated = original

    for old, new in replacements:
        if updated.count(old) != 1:
            raise SystemExit(
                f"STOP: expected exactly one occurrence in {filename}: {old.splitlines()[0]}"
            )
        updated = updated.replace(old, new, 1)

    path.write_text(updated, encoding="utf-8")
    print(f"Patched: {filename}")

print("API route guards applied.")
