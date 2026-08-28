#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path
import stat
import zipfile

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
EXECUTABLE_PATHS = {
    Path("start-emonio-viewer.sh"),
    Path("tools/ari-emonio-acceptance.sh"),
    Path("tools/ari-emonio-publication-gate.sh"),
}
FORBIDDEN_PARTS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    ".venv",
    "recordings",
}
FORBIDDEN_ROOT_DIRS = {"dist", "build"}
FORBIDDEN_EXACT = {
    Path("config/remembered-devices.json"),
    Path("config/emonio-viewer.local.toml"),
}
FORBIDDEN_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".zip",
    ".log",
    ".sqlite",
    ".sqlite3",
    ".swp",
    ".swo",
}


def _version(root: Path) -> str:
    raw = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    return str(raw["project"]["version"])


def _is_public_file(root: Path, path: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in FORBIDDEN_PARTS for part in relative.parts):
        return False
    if relative.parts and relative.parts[0] in FORBIDDEN_ROOT_DIRS:
        return False
    if relative in FORBIDDEN_EXACT:
        return False
    if relative.parts[:2] == ("docs", "superpowers"):
        return False
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        return False
    if path.name in {".DS_Store", "Thumbs.db"}:
        return False
    if path.name.startswith(".env") and path.name != ".env.example":
        return False
    return True


def public_files(root: Path) -> list[Path]:
    root = root.resolve()
    files = [path for path in root.rglob("*") if path.is_file() and _is_public_file(root, path)]
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def build_release(root: Path, output_dir: Path) -> Path:
    root = root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    version = _version(root)
    package_name = f"ARI_Emonio_Viewer_v{version}_Candidate"
    archive_path = output_dir / f"{package_name}.zip"

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source in public_files(root):
            relative = source.relative_to(root)
            archive_name = f"{package_name}/{relative.as_posix()}"
            info = zipfile.ZipInfo(archive_name, FIXED_ZIP_TIME)
            info.create_system = 3
            mode = 0o755 if relative in EXECUTABLE_PATHS else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    archive_path.with_suffix(archive_path.suffix + ".sha256").write_text(
        f"{digest}  {archive_path.name}\n",
        encoding="ascii",
    )
    return archive_path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    archive = build_release(root, root / "dist")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    print(archive)
    print(f"SHA-256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
