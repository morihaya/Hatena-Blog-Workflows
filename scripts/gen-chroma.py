#!/usr/bin/env python3
"""assets/css/chroma.css を生成する。

`hugo gen chromastyles` の出力をそのまま使うと、ダーク用のスタイルを
`@media (prefers-color-scheme: dark)` で囲むしかない。それだとヘッダーの
テーマ切り替え (`<html data-theme="light|dark">`) に追従できないため、
ダーク側のセレクタに `:root[data-theme=...]` を付けた 2 組を並べて出力する。

    python3 scripts/gen-chroma.py

スタイルを変えたいときは下の LIGHT_STYLE / DARK_STYLE を書き換えて実行する
(選べる名前は `hugo gen chromastyles --help` を参照)。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

LIGHT_STYLE = "github"
DARK_STYLE = "github-dark"
OUT = Path(__file__).resolve().parent.parent / "assets" / "css" / "chroma.css"

RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
COMMENT = re.compile(r"/\*.*?\*/", re.S)


def chromastyles(style: str) -> str:
    return subprocess.run(
        ["hugo", "gen", "chromastyles", "--style", style],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def parse(css: str) -> list[tuple[str, str, str]]:
    """(コメント, セレクタ, 宣言) の並びに分解する。"""
    rules = []
    for m in RULE.finditer(css):
        head, decls = m.group(1), m.group(2).strip()
        comment_match = COMMENT.search(head)
        comment = comment_match.group(0) if comment_match else ""
        selector = " ".join(COMMENT.sub("", head).split())
        if selector:
            rules.append((comment, selector, decls))
    return rules


def render(rules: list[tuple[str, str, str]], prefix: str = "", indent: str = "") -> str:
    lines = []
    for comment, selector, decls in rules:
        if prefix:
            selector = ", ".join(f"{prefix} {s.strip()}" for s in selector.split(","))
        head = f"{comment} " if comment else ""
        lines.append(f"{indent}{head}{selector} {{ {decls} }}")
    return "\n".join(lines)


def main() -> None:
    light = parse(chromastyles(LIGHT_STYLE))
    dark = parse(chromastyles(DARK_STYLE))

    out = f"""/* Chroma シンタックスハイライト
   scripts/gen-chroma.py で生成している。直接編集しないこと。
   ライト: {LIGHT_STYLE} / ダーク: {DARK_STYLE} */

{render(light)}

/* ここから下はダーク。OS 設定に追従する分と、ヘッダーのトグルで
   手動選択したときの分の 2 組を置いている (assets/css/main.css と同じ方針)。 */

@media (prefers-color-scheme: dark) {{
{render(dark, ':root:not([data-theme="light"])', "  ")}
}}

{render(dark, ':root[data-theme="dark"]')}
"""
    OUT.write_text(out, encoding="utf-8")
    print(f"wrote {OUT} ({len(light)} light rules, {len(dark)} dark rules x2)")


if __name__ == "__main__":
    main()
