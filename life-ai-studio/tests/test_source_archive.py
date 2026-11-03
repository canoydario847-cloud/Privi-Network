"""Synthetic source-artifact privacy regression tests (no customer data)."""
import importlib.util
import pathlib
import stat
import zipfile

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "tools" / "check_source_archive.py"
SPEC = importlib.util.spec_from_file_location("life_source_archive_guard", SCRIPT)
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


def make_zip(tmp_path, names, symlink=False):
    path = tmp_path / "source.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            if symlink:
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, "outside")
            else:
                archive.writestr(name, "synthetic fixture")
    return path


def test_safe_source_files_and_env_example_pass(tmp_path):
    archive = make_zip(tmp_path, ["life-ai-studio/", "life-ai-studio/app.py",
                                   "life-ai-studio/.env.example",
                                   "life-ai-studio/public/style.css"])
    assert guard.validate_archive(archive) == 4


@pytest.mark.parametrize("member", [
    "life-ai-studio/.env", "life-ai-studio/.env.production",
    "life-ai-studio/data/member.sqlite3", "life-ai-studio/keys/server.pem",
    "life-ai-studio/.npmrc", "life-ai-studio/../secrets.json",
    "outside/file.py", "life-ai-studio\\data\\private.db",
])
def test_private_or_unsafe_paths_fail_closed(tmp_path, member):
    archive = make_zip(tmp_path, [member])
    with pytest.raises(ValueError):
        guard.validate_archive(archive)


def test_symlink_entry_rejected(tmp_path):
    archive = make_zip(tmp_path, ["life-ai-studio/linked.py"], symlink=True)
    with pytest.raises(ValueError, match="unsafe file type"):
        guard.validate_archive(archive)


def test_duplicate_archive_members_rejected(tmp_path):
    archive = make_zip(tmp_path, ["life-ai-studio/App.py", "life-ai-studio/app.py"])
    with pytest.raises(ValueError, match="duplicate paths"):
        guard.validate_archive(archive)
