#!/usr/bin/env python3
"""Check a danmaku game's theme files against its code.

Finds every theme lookup in the source and reports keys the theme does not have, then
loads each theme (following "extends") and reports strings whose {placeholders} did not fill.
Also warns (without failing) when two different name tables use the same or overlapping words,
e.g. a gift tier called 合伙人 while a job rank is also 合伙人: viewers cannot tell which one a
badge means. Tables ending in _alias and the numeral table are skipped.

    python3 check_theme.py <project_dir> [--src scripts] [--config config] [--ext .gd]

Lookups recognised (the Words API from assets/words.gd; adjust LOOKUP for another engine):
    Words.text("a.b"), Words.key("verb"), Words.keys("verb"), Words.name("group", …),
    Words.names("group"), Words.term("word"), and any bare "prefix.name" string whose prefix
    is a prefix used in the theme's text keys (so keys picked by `if/else` are checked too).
Exit code 1 when anything is missing.
"""
import argparse
import json
import re
import sys
from pathlib import Path

LOOKUP = re.compile(r'Words\.(key|keys|name|names|term)\(\s*"([a-z0-9_]+)"')
TEXT_LITERAL = re.compile(r'"([a-z_]+)\.([a-z0-9_]+)"')
TOKEN = re.compile(r"\{([a-z_]+)(?:\.([a-z0-9_]+))?\}")
SECTION = {"key": "commands", "keys": "commands", "name": "names", "names": "names", "term": "terms"}


def load_theme(config: Path, theme_id: str) -> dict:
    data = json.loads((config / f"theme_{theme_id}.json").read_text(encoding="utf-8"))
    base = data.get("extends")
    return merge(load_theme(config, base), data) if base else data


def merge(base: dict, over: dict) -> dict:
    result = dict(base)
    for key, value in over.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


def fill(value, theme: dict):
    if isinstance(value, str):
        def replace(match):
            group, ident = match.group(1), match.group(2)
            if ident is None:
                found = theme.get("terms", {}).get(group)
            elif group == "cmd":
                words = theme.get("commands", {}).get(ident, [])
                found = words[0] if words else None
            else:
                table = theme.get("names", {}).get(group)
                if isinstance(table, list) and ident.isdigit() and int(ident) < len(table):
                    found = table[int(ident)]
                elif isinstance(table, dict):
                    found = table.get(ident)
                else:
                    found = None
            return found if isinstance(found, str) else match.group(0)
        return TOKEN.sub(replace, value)
    if isinstance(value, list):
        return [fill(v, theme) for v in value]
    if isinstance(value, dict):
        return {k: fill(v, theme) for k, v in value.items()}
    return value


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)


def overlaps(theme: dict) -> list[str]:
    items = []
    for table, value in theme.get("names", {}).items():
        if table.endswith("_alias") or table == "numeral":
            continue
        values = value.values() if isinstance(value, dict) else value
        for text in values:
            if isinstance(text, str) and len(text) >= 2 and "{" not in text:
                items.append((table, text))
    found = []
    for index, (table_a, text_a) in enumerate(items):
        for table_b, text_b in items[index + 1:]:
            if table_a != table_b and (text_a in text_b or text_b in text_a):
                found.append(f"{table_a}.{text_a} ~ {table_b}.{text_b}")
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--src", default="scripts")
    parser.add_argument("--config", default="config")
    parser.add_argument("--ext", default=".gd")
    parser.add_argument("--base", default=None, help="theme the code is checked against (default: game.json 'theme' or xianxia)")
    args = parser.parse_args()
    root = Path(args.project)
    config = root / args.config
    base_id = args.base
    if base_id is None:
        game = config / "game.json"
        base_id = json.loads(game.read_text(encoding="utf-8")).get("theme", "xianxia") if game.exists() else "xianxia"
    base = load_theme(config, base_id)
    prefixes = {key.split(".")[0] for key in base.get("text", {})}
    missing = []
    for path in sorted((root / args.src).rglob(f"*{args.ext}")):
        source = path.read_text(encoding="utf-8")
        for match in LOOKUP.finditer(source):
            section = SECTION[match.group(1)]
            if match.group(2) not in base.get(section, {}):
                missing.append(f"{path.relative_to(root)}: {match.group(0)}")
        for match in TEXT_LITERAL.finditer(source):
            key = f"{match.group(1)}.{match.group(2)}"
            if match.group(1) in prefixes and key not in base.get("text", {}):
                missing.append(f"{path.relative_to(root)}: \"{key}\"")
    unfilled = []
    for theme_file in sorted(config.glob("theme_*.json")):
        theme_id = theme_file.stem[len("theme_"):]
        theme = load_theme(config, theme_id)
        for _ in range(3):
            for section in ("terms", "names", "text"):
                theme[section] = fill(theme.get(section, {}), theme)
        for section in ("terms", "names", "text"):
            for text in strings(theme.get(section, {})):
                if TOKEN.search(text):
                    unfilled.append(f"{theme_id}: {text[:60]}")
    shared = overlaps(base)
    print(json.dumps({"base_theme": base_id, "missing_keys": len(missing), "unfilled_placeholders": len(unfilled), "name_overlaps": len(shared)}, ensure_ascii=False))
    for line in missing + unfilled:
        print("  " + line)
    for line in shared:
        print("  overlap (warning): " + line)
    return 1 if missing or unfilled else 0


if __name__ == "__main__":
    sys.exit(main())
