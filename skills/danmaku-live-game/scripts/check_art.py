#!/usr/bin/env python3
"""Check that every game image went through the art pipeline (manifest → generate → key/resize).

A raw generated image dropped straight into the game (1254×1254, ~1 MB, drawn at 28 px, seven
at once) made the first frame that showed it take 50–120 ms. This script catches that class of
mistake without running the engine.

    python3 check_art.py <art_dir> <manifest.json> [--max-side 2048] [--max-kb 2048]

Reports:
  - oversize: an image whose actual height is larger than the manifest's `height` (default 256),
    or a background whose size differs from its `cover` (default 1080×1920);
  - unlisted: a PNG in <art_dir> that no manifest entry produces (split entries produce
    name_0, name_1, …);
  - huge: any PNG whose longest side or file size passes the hard limits.
Exit code 1 when anything is reported.
"""
import argparse
import json
import struct
import sys
from pathlib import Path

DEFAULT_HEIGHT = 256
DEFAULT_COVER = [1080, 1920]


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    width, height = struct.unpack(">II", header[16:24])
    return width, height


def expected_outputs(asset: dict) -> list[str]:
    parts = int(asset.get("split", 1))
    if parts > 1:
        return [f"{asset['name']}_{i}" for i in range(parts)]
    return [asset["name"]]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("art_dir")
    parser.add_argument("manifest")
    parser.add_argument("--max-side", type=int, default=2048)
    parser.add_argument("--max-kb", type=int, default=2048)
    args = parser.parse_args()
    art_dir = Path(args.art_dir)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    listed: set[str] = set()
    oversize: list[str] = []
    for asset in manifest.get("assets", []):
        for name in expected_outputs(asset):
            listed.add(name)
            path = art_dir / f"{name}.png"
            if not path.exists():
                continue
            width, height = png_size(path)
            is_background = asset.get("key") is None and not asset.get("preserve_alpha", False)
            if is_background:
                cover = asset.get("cover", DEFAULT_COVER)
                if [width, height] != [int(cover[0]), int(cover[1])]:
                    oversize.append(f"{name}: {width}×{height}, cover {cover[0]}×{cover[1]}")
            elif height > int(asset.get("height", DEFAULT_HEIGHT)) + 1:
                oversize.append(f"{name}: {width}×{height}, manifest height {asset.get('height', DEFAULT_HEIGHT)}")
    unlisted: list[str] = []
    huge: list[str] = []
    for path in sorted(art_dir.glob("*.png")):
        if path.stem not in listed:
            unlisted.append(path.name)
        width, height = png_size(path)
        kilobytes = path.stat().st_size // 1024
        if max(width, height) > args.max_side or kilobytes > args.max_kb:
            huge.append(f"{path.name}: {width}×{height}, {kilobytes} KB")
    print(json.dumps({"oversize": len(oversize), "unlisted": len(unlisted), "huge": len(huge)}, ensure_ascii=False))
    for label, lines in (("oversize", oversize), ("unlisted", unlisted), ("huge", huge)):
        for line in lines:
            print(f"  {label}: {line}")
    return 1 if oversize or unlisted or huge else 0


if __name__ == "__main__":
    sys.exit(main())
