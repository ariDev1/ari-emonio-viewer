from __future__ import annotations

import importlib.util
from pathlib import Path
import stat
import zipfile


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "build-release.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("ari_release_builder", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_builder_is_byte_deterministic_and_excludes_local_debris(tmp_path: Path) -> None:
    module = _load_tool()
    first = module.build_release(ROOT, tmp_path / "a")
    second = module.build_release(ROOT, tmp_path / "b")

    assert first.name == "ARI_Emonio_Viewer_v0.4.6_Candidate.zip"
    assert first.read_bytes() == second.read_bytes()

    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert all(name.startswith("ARI_Emonio_Viewer_v0.4.6_Candidate/") for name in names)
        forbidden = (
            "/.git/",
            "/.pytest_cache/",
            "/__pycache__/",
            "/.venv/",
            "/recordings/",
            "/docs/superpowers/",
            "/config/remembered-devices.json",
            "/config/emonio-viewer.local.toml",
        )
        assert all(not any(token in f"/{name}" for token in forbidden) for name in names)
        assert all(not name.endswith((".pyc", ".zip", ".log", ".sqlite", ".sqlite3")) for name in names)

        for script in ("start-emonio-viewer.sh", "tools/ari-emonio-acceptance.sh", "tools/ari-emonio-publication-gate.sh"):
            info = archive.getinfo(f"ARI_Emonio_Viewer_v0.4.6_Candidate/{script}")
            mode = (info.external_attr >> 16) & 0o777
            assert mode == 0o755


def test_release_builder_writes_matching_sha256_file(tmp_path: Path) -> None:
    import hashlib

    module = _load_tool()
    archive = module.build_release(ROOT, tmp_path)
    digest_file = archive.with_suffix(archive.suffix + ".sha256")
    expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert digest_file.read_text(encoding="ascii") == f"{expected}  {archive.name}\n"


def test_release_builder_excludes_root_build_output_directories(tmp_path: Path) -> None:
    module = _load_tool()
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "test"\nversion = "0.3.5"\n',
        encoding="utf-8",
    )
    (root / "source.txt").write_text("source\n", encoding="utf-8")
    (root / "dist").mkdir()
    (root / "dist" / "old.zip.sha256").write_text("stale\n", encoding="utf-8")
    (root / "build").mkdir()
    (root / "build" / "temporary.txt").write_text("temporary\n", encoding="utf-8")

    archive = module.build_release(root, root / "dist")

    with zipfile.ZipFile(archive) as release:
        names = release.namelist()
        assert all("/dist/" not in f"/{name}" for name in names)
        assert all("/build/" not in f"/{name}" for name in names)
