"""Create a reviewable ZIP without environments, caches or git metadata."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parent
files = [root / name for name in ("README.md", "requirements.txt", "requirements-lock.txt", "package_submission.py")]
for folder in ("tool_sample", "docs", "examples", "tests"):
    files.extend(path for path in (root / folder).rglob("*")
                 if path.is_file() and "__pycache__" not in path.parts
                 and path.suffix in (".py", ".md", ".json", ".csv", ".parquet"))
archive = root / "submission_glm_catalog.zip"
with ZipFile(archive, "w", ZIP_DEFLATED) as out:
    for path in sorted(files):
        out.write(path, path.relative_to(root).as_posix())
with ZipFile(archive) as out:
    assert out.testzip() is None
    print(f"{archive.name}: {len(out.namelist())} files, {archive.stat().st_size:,} bytes; CRC passed")
