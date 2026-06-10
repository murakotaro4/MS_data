"""raw snapshot artifact から cache/reports を復元する。"""

from __future__ import annotations

import argparse
import shutil
import tarfile
from pathlib import Path


def _safe_member_path(output_dir: Path, member_name: str) -> Path:
    if member_name.startswith("/"):
        raise ValueError(f"absolute path is not allowed in snapshot: {member_name}")
    target = (output_dir / member_name).resolve()
    output_root = output_dir.resolve()
    if target != output_root and output_root not in target.parents:
        raise ValueError(f"path traversal is not allowed in snapshot: {member_name}")
    return target


def restore_snapshot(snapshot_path: Path, output_dir: Path) -> list[str]:
    restored: list[str] = []
    output_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(snapshot_path, "r:*") as archive:
        for member in archive.getmembers():
            target = _safe_member_path(output_dir, member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError(f"snapshot file cannot be read: {member.name}")
                with source, target.open("wb") as f:
                    shutil.copyfileobj(source, f)
            else:
                raise ValueError(f"unsupported snapshot entry: {member.name}")
            restored.append(member.name)
    return restored


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("."))
    args = parser.parse_args(argv)

    restored = restore_snapshot(args.snapshot, args.out_dir)
    for name in restored:
        print(name)
    print(f"restored: {len(restored)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
