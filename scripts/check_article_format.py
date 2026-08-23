#!/usr/bin/env python3
"""新規記事のパスとフロントマターを簡易チェックする。"""

from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path


ARTICLE_PATH = re.compile(
    r"^content/entry/(?P<year>\d{4})/(?P<month>\d{2})/"
    r"(?P<day>\d{2})/(?P<time>\d{6})\.md$"
)
DATE = re.compile(
    r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})T"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(?P<timezone>Z|[+-]\d{2}:\d{2})$"
)


def read_front_matter(path: Path) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        return {}, ["先頭に YAML フロントマター (`---`) がありません"]

    try:
        end = lines.index("---", 1)
    except ValueError:
        return {}, ["フロントマターを閉じる `---` がありません"]

    values: dict[str, object] = {}
    current_list: str | None = None
    for line in lines[1:end]:
        list_item = re.match(r'^\s+-\s+"?(.+?)"?\s*$', line)
        if list_item and current_list:
            assert isinstance(values[current_list], list)
            values[current_list].append(list_item.group(1))
            continue

        field = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?$", line)
        if not field:
            current_list = None
            continue
        key, raw_value = field.groups()
        raw_value = (raw_value or "").strip()
        if raw_value == "" or raw_value == "[]":
            values[key] = []
            current_list = key
        else:
            values[key] = raw_value.strip('"')
            current_list = None

    if end == len(lines) - 1 or not any(line.strip() for line in lines[end + 1 :]):
        errors.append("記事本文が空です")
    return values, errors


def check(path: Path) -> list[str]:
    errors: list[str] = []
    match = ARTICLE_PATH.fullmatch(path.as_posix())
    if not match:
        errors.append("パスは content/entry/YYYY/MM/DD/HHMMSS.md の形式にしてください")

    try:
        values, front_matter_errors = read_front_matter(path)
    except (OSError, UnicodeError) as error:
        return [f"ファイルを読み込めません: {error}"]
    errors.extend(front_matter_errors)

    title = values.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append("title を空でない文字列で設定してください")

    date_value = values.get("date")
    date_match = DATE.fullmatch(date_value) if isinstance(date_value, str) else None
    if not date_match:
        errors.append("date は ISO 8601 形式（例: 2026-08-23T12:06:21+09:00）で設定してください")
    else:
        try:
            dt.datetime.fromisoformat(date_value.replace("Z", "+00:00"))
        except ValueError:
            errors.append("date に実在する日時を設定してください")
        if match:
            date_parts = date_match.groupdict()
            path_parts = match.groupdict()
            date_in_path = (
                date_parts["year"],
                date_parts["month"],
                date_parts["day"],
                date_parts["hour"] + date_parts["minute"] + date_parts["second"],
            )
            path_date = (
                path_parts["year"],
                path_parts["month"],
                path_parts["day"],
                path_parts["time"],
            )
            if date_in_path != path_date:
                errors.append("date の日時と記事パスの YYYY/MM/DD/HHMMSS が一致していません")

    categories = values.get("categories")
    if not isinstance(categories, list) or not categories:
        errors.append("categories を1つ以上設定してください")

    if values.get("draft") not in {"true", "false"}:
        errors.append("draft は true または false で設定してください")

    return errors


def main() -> int:
    if len(sys.argv) == 1:
        print("チェック対象の新規記事はありません")
        return 0

    failed = False
    for filename in sys.argv[1:]:
        errors = check(Path(filename))
        if errors:
            failed = True
            print(f"::error file={filename}::{'; '.join(errors)}")
        else:
            print(f"OK: {filename}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
