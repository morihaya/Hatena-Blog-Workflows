#!/usr/bin/env python3
"""blogsync 形式の記事を静的サイトジェネレータ向けの Markdown に変換する。

やること:
  - front matter の変換 (Title/Category/Date/URL/EditURL -> title/categories/date/params)
  - `[f:id:...]` 画像記法 -> 通常の Markdown 画像 (fetch_fotolife.py の manifest を参照)
  - `[URL:embed:cite]` / `[URL:title]` -> 通常の Markdown リンク
  - `[:contents]` -> 目次ショートコード
  - はてな脚注 `((...))` -> Markdown 脚注 `[^1]`
コードフェンス・インラインコードの中身は変換しない。

出力パスは入力の階層をそのまま維持するため、URL 構造 (/entry/YYYY/MM/DD/HHMMSS)
は移行後も変わらない。

  python3 scripts/migration/convert_entries.py --dry-run
  python3 scripts/migration/convert_entries.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

FOTOLIFE_RE = re.compile(r"\[f:id:(?P<user>[^:\]]+):(?P<ts>\d{14})(?P<kind>[a-z]?):(?P<opts>[^\]]*)\]")
# はてなが画像に付ける figure ラッパ。Markdown 画像に潰して SSG 非依存にする
FIGURE_RE = re.compile(
    r"<figure[^>]*>(?P<imgs>(?:\[f:id:[^\]]*\])+)(?:<figcaption>(?P<caption>.*?)</figcaption>)?</figure>"
)
# [URL:embed:cite] [URL:embed#キャッシュされたタイトル] [URL:title] [URL:image=alt] など
HATENA_URL_RE = re.compile(
    r"\[(?P<url>https?://[^\s\]]+?):(?P<kind>embed|title|bookmark|detail|image)"
    r"(?::cite)?(?:[#=](?P<label>[^\]]*))?\]"
)
CONTENTS_RE = re.compile(r"\[:contents\]")
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")

KIND_TO_EXT = {"p": "png", "j": "jpg", "g": "gif", "": "jpg"}


@dataclass
class Stats:
    files: int = 0
    images: int = 0
    images_unresolved: list[str] = field(default_factory=list)
    external_images: list[str] = field(default_factory=list)
    links: int = 0
    links_untitled: int = 0
    contents: int = 0
    footnotes: int = 0
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# front matter
# --------------------------------------------------------------------------

def split_front_matter(text: str) -> tuple[dict[str, object], str]:
    """blogsync の front matter を辞書と本文に分解する。"""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text

    meta: dict[str, object] = {}
    key: str | None = None
    for line in text[4:end].split("\n"):
        if line.startswith("- ") and key:
            meta.setdefault(key, [])
            if isinstance(meta[key], list):
                meta[key].append(line[2:].strip())
        elif ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            meta[key] = value if value else []
    return meta, text[end + 5 :]


def yaml_scalar(value: str) -> str:
    """JSON 文字列は YAML のダブルクォート表現として妥当なので流用する。"""
    return json.dumps(value, ensure_ascii=False)


def build_front_matter(meta: dict[str, object], keep_hatena_meta: bool) -> str:
    lines = ["---"]
    lines.append(f"title: {yaml_scalar(str(meta.get('Title', '')))}")
    if meta.get("Date"):
        lines.append(f"date: {meta['Date']}")

    categories = meta.get("Category") or []
    if isinstance(categories, list) and categories:
        lines.append("categories:")
        lines.extend(f"  - {yaml_scalar(c)}" for c in categories)

    lines.append("draft: false")

    if keep_hatena_meta:
        lines.append("hatena:")
        if meta.get("URL"):
            lines.append(f"  url: {yaml_scalar(str(meta['URL']))}")
        if meta.get("EditURL"):
            lines.append(f"  edit_url: {yaml_scalar(str(meta['EditURL']))}")

    lines.append("---")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# 本文変換
# --------------------------------------------------------------------------

MASK = "\x01"


def mask_code(text: str) -> str:
    """コード領域をマスク文字で潰した複製を返す。オフセットは元テキストと一致する。

    脚注の走査はコードフェンスやインラインコードの中身を対象にしてはいけないが、
    脚注は行をまたぐことがあるため行単位では処理できない。そこで走査用に
    「コードだけ見えないテキスト」を作り、位置は元テキストと共有する。
    """
    chars = list(text)
    in_fence = False
    pos = 0
    for line in text.split("\n"):
        is_fence_marker = line.lstrip().startswith("```")
        if is_fence_marker or in_fence:
            chars[pos : pos + len(line)] = MASK * len(line)
        if is_fence_marker:
            in_fence = not in_fence
        pos += len(line) + 1

    # フェンス内は潰れているので、ここで残るのはフェンス外のインラインコードのみ
    return INLINE_CODE_RE.sub(lambda m: MASK * len(m.group(0)), "".join(chars))


def convert_footnotes(text: str, stats: Stats, source: str) -> str:
    """`((脚注))` を Markdown 脚注に変換する。入れ子の括弧を数えて終端を探す。

    コード内の `((` は脚注ではないため、走査はマスク済みテキストに対して行い、
    本文の切り出しだけを元テキストから行う。
    """
    scan = mask_code(text)
    out: list[str] = []
    notes: list[str] = []
    i = 0
    while True:
        start = scan.find("((", i)
        if start == -1:
            out.append(text[i:])
            break

        depth = 0
        j = start + 2
        end = -1
        while j < len(scan):
            ch = scan[j]
            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth > 0:
                    depth -= 1
                elif scan[j : j + 2] == "))":
                    end = j
                    break
                else:  # 対応しない `)` -> 脚注ではない
                    break
            j += 1

        if end == -1:
            stats.warnings.append(f"{source}: 閉じられていない脚注らしき `((` を無視しました (offset {start})")
            out.append(text[i : start + 2])
            i = start + 2
            continue

        notes.append(text[start + 2 : end])
        out.append(text[i:start])
        out.append(f"[^{len(notes)}]")
        i = end + 2

    if not notes:
        return text

    stats.footnotes += len(notes)
    body = "".join(out).rstrip("\n")
    defs = "\n".join(f"[^{n}]: {note}" for n, note in enumerate(notes, 1))
    return f"{body}\n\n{defs}\n"


def convert_line(line: str, manifest: dict, titles: dict, args, stats: Stats, source: str) -> str:
    def render_image(m: re.Match, alt_override: str | None = None) -> str:
        stats.images += 1
        ts, kind, opts = m.group("ts"), m.group("kind"), m.group("opts")
        key = f"f:id:{m.group('user')}:{ts}{kind}"

        record = manifest.get(key)
        if record and record.get("local"):
            ext = Path(record["local"]).suffix.lstrip(".")
        else:
            ext = KIND_TO_EXT.get(kind, "jpg")
            if key not in stats.images_unresolved:
                stats.images_unresolved.append(key)

        path = f"{args.image_prefix.rstrip('/')}/{ts}.{ext}"
        alt = alt_override or ""
        width = None
        for opt in opts.split(":"):
            if opt.startswith("alt=") and not alt_override:
                alt = opt[4:]
            elif re.fullmatch(r"w\d+", opt):
                width = opt[1:]

        if width:
            # 生 HTML は Hugo が URL を解決できないため、ショートコードで出す
            return f'{{{{< img src="{path}" alt="{alt}" width="{width}" >}}}}'
        return f"![{alt}]({path})"

    def figure(m: re.Match) -> str:
        """figure ラッパを外し、figcaption を alt に移す。"""
        caption = (m.group("caption") or "").strip()
        return "\n".join(render_image(img, caption) for img in FOTOLIFE_RE.finditer(m.group("imgs")))

    def link(m: re.Match) -> str:
        url, kind, label = m.group("url"), m.group("kind"), (m.group("label") or "").strip()

        if kind == "image":
            stats.images += 1
            stats.external_images.append(url)
            return f"![]({url})" if label in ("", url) else f"![{label}]({url})"

        stats.links += 1
        title = label or titles.get(url)
        if not title:
            stats.links_untitled += 1
            title = url
        return f"[{title}]({url})"

    def contents(_: re.Match) -> str:
        stats.contents += 1
        return args.toc

    # インラインコードは変換対象外なので退避しておく
    spans: list[str] = []

    def stash(m: re.Match) -> str:
        spans.append(m.group(0))
        return f"\x00{len(spans) - 1}\x00"

    line = INLINE_CODE_RE.sub(stash, line)
    line = FIGURE_RE.sub(figure, line)  # figure の中の f:id を先に処理する
    line = FOTOLIFE_RE.sub(render_image, line)
    line = HATENA_URL_RE.sub(link, line)
    line = CONTENTS_RE.sub(contents, line)
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], line)


def convert_body(body: str, manifest: dict, titles: dict, args, stats: Stats, source: str) -> str:
    lines: list[str] = []
    in_fence = False
    for line in body.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            lines.append(line)
            continue
        lines.append(line if in_fence else convert_line(line, manifest, titles, args, stats, source))

    if in_fence:
        stats.warnings.append(f"{source}: コードフェンスが閉じられていない可能性があります")

    return convert_footnotes("\n".join(lines), stats, source)


# --------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--entries", type=Path, default=Path("entries"))
    p.add_argument("--out", type=Path, default=Path("content"), help="出力先 (default: content)")
    p.add_argument("--manifest", type=Path, default=Path("scripts/migration/fotolife_manifest.json"))
    p.add_argument("--titles", type=Path, default=Path("scripts/migration/link_titles.json"))
    p.add_argument("--image-prefix", default="/images/fotolife", help="変換後の画像 URL の接頭辞")
    p.add_argument("--toc", default="{{< toc >}}", help="[:contents] の置換文字列")
    p.add_argument("--no-hatena-meta", action="store_true", help="元 URL を front matter に残さない")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if not args.entries.is_dir():
        print(f"error: {args.entries} が見つかりません", file=sys.stderr)
        return 1

    manifest = json.loads(args.manifest.read_text(encoding="utf-8")) if args.manifest.exists() else {}
    titles = json.loads(args.titles.read_text(encoding="utf-8")) if args.titles.exists() else {}
    if not manifest:
        print(f"note: {args.manifest} が無いため画像の拡張子は記法から推測します", file=sys.stderr)

    stats = Stats()
    for md in sorted(args.entries.rglob("*.md")):
        text = md.read_text(encoding="utf-8")
        meta, body = split_front_matter(text)
        if not meta:
            stats.warnings.append(f"{md}: front matter が読めないためスキップしました")
            continue

        # entries/<blog domain>/entry/... の blog domain を落として階層を維持する
        rel = md.relative_to(args.entries)
        rel = Path(*rel.parts[1:]) if len(rel.parts) > 1 else rel

        converted = build_front_matter(meta, not args.no_hatena_meta) + "\n" + convert_body(body.lstrip("\n"), manifest, titles, args, stats, str(md))
        stats.files += 1

        if not args.dry_run:
            dest = args.out / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(converted, encoding="utf-8")

    prefix = "[dry-run] " if args.dry_run else ""
    print(f"{prefix}変換 {stats.files} 記事 -> {args.out}")
    print(f"  画像       : {stats.images} (manifest 未解決 {len(stats.images_unresolved)} / 外部ホスト {len(stats.external_images)})")
    print(f"  リンク記法 : {stats.links} (タイトル未取得 {stats.links_untitled})")
    print(f"  目次       : {stats.contents}")
    print(f"  脚注       : {stats.footnotes}")

    if stats.images_unresolved:
        print("\n  manifest に無い画像 (fetch_fotolife.py を先に実行してください):", file=sys.stderr)
        for key in stats.images_unresolved[:10]:
            print(f"    {key}", file=sys.stderr)
    if stats.warnings:
        print(f"\n警告 {len(stats.warnings)} 件:", file=sys.stderr)
        for w in stats.warnings:
            print(f"  {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
