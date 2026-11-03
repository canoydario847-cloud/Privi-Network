"""Synthetic regression coverage for LIFE source artifact size limits."""
import importlib.util
from pathlib import Path
import zipfile

import pytest

SPEC = importlib.util.spec_from_file_location(
    "life_source_archive", Path(__file__).resolve().parents[1] / "tools" / "check_source_archive.py"
)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


@pytest.mark.parametrize("sizes, accepted", [
    ([1024], True),
    ([21 * 1024 * 1024], False),
    ([18 * 1024 * 1024] * 6, False),
])
def test_uncompressed_archive_limits(tmp_path, sizes, accepted):
    archive_path = tmp_path / "source.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, size in enumerate(sizes):
            archive.writestr(f"life-ai-studio/synthetic-{index}.txt", b"x" * size)
    if accepted:
        assert checker.validate_archive(archive_path) == len(sizes)
    else:
        with pytest.raises(ValueError, match="size|oversized"):
            checker.validate_archive(archive_path)
