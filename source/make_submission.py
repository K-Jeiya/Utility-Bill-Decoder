"""Build the submission ZIP (output/ + source/ + demo/) and run safety checks.

  python make_submission.py

Excludes: .env, .venv, caches, logs, __pycache__, data/. Refuses to create the ZIP if
a secret-looking string is found or the size would exceed 15 MB. Never uploads anything.
"""
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 15 * 1024 * 1024
EXCLUDE_DIRS = {".venv", "venv", "__pycache__", "logs", ".git", ".pytest_cache", ".mypy_cache"}
EXCLUDE_NAMES = {".env", "Thumbs.db", ".DS_Store", ".gitkeep"}
SECRET_RE = re.compile(r"AIza[0-9A-Za-z_\-]{30,}|sk-[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9\-_]{20,}")
REQUIRED = ["output/level1.csv", "output/level2.csv", "source/README.md", "source/.env.example",
            "source/requirements.txt", "source/main.py"]


def collect() -> list[Path]:
    files = []
    for top in ("output", "source", "demo"):
        for p in sorted((ROOT / top).rglob("*")):
            if p.is_file() and not (set(p.relative_to(ROOT).parts) & EXCLUDE_DIRS) and p.name not in EXCLUDE_NAMES \
                    and p.suffix != ".pyc":
                files.append(p)
    return files


def main() -> int:
    files = collect()
    rels = {p.relative_to(ROOT).as_posix() for p in files}
    problems = [f"missing required file: {r}" for r in REQUIRED if r not in rels]
    for p in files:
        if p.suffix in {".py", ".md", ".txt", ".csv", ".example", ".json"} or p.name == ".env.example":
            if SECRET_RE.search(p.read_text(encoding="utf-8", errors="ignore")):
                problems.append(f"possible API key inside {p.relative_to(ROOT)}")
    if problems:
        print("NOT building ZIP:\n  " + "\n  ".join(problems))
        return 1
    target = ROOT / "submission.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, p.relative_to(ROOT).as_posix())
    size = target.stat().st_size
    print(f"Created {target} ({size / 1024 / 1024:.2f} MB, limit 15 MB)")
    with zipfile.ZipFile(target) as zf:
        for name in zf.namelist():
            print("  ", name)
    if size > LIMIT:
        print("ZIP IS TOO LARGE - shrink the demo video before submitting.")
        return 1
    print("Open the ZIP yourself and check it before uploading. Nothing was uploaded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
