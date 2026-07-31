#!/usr/bin/env python3
"""`[URL:embed:cite]` 記法のリンク先ページタイトルを収集する (任意)。

はてなの埋め込み記法はタイトルを本文に持たないため、そのまま変換すると
リンクテキストが URL のままになる。このスクリプトで link_titles.json を
作っておくと convert_entries.py がタイトル付きリンクに変換する。

外部サイトへ HTTP アクセスするため、実行は任意。失敗した URL は
単に JSON に載らず、変換時は URL がそのままリンクテキストになる。

  python3 scripts/migration/fetch_link_titles.py --list      # 対象 URL の一覧
  python3 scripts/migration/fetch_link_titles.py             # 取得して JSON 更新
"""

from __future__ import annotations

import argparse
import html
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_ssl_context  # noqa: E402

EMBED_RE = re.compile(r"\[(?P<url>https?://[^\s\]]+?):(?:embed:cite|embed|title|bookmark|detail)\]")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
CHARSET_RE = re.compile(rb'charset=["\']?([\w-]+)', re.IGNORECASE)

USER_AGENT = "Mozilla/5.0 (compatible; hatena-blog-migration/1.0)"


def collect_urls(entries_dir: Path) -> list[str]:
    urls: list[str] = []
    for md in sorted(entries_dir.rglob("*.md")):
        for m in EMBED_RE.finditer(md.read_text(encoding="utf-8")):
            if m.group("url") not in urls:
                urls.append(m.group("url"))
    return urls


def fetch_title(url: str, timeout: int, ctx: ssl.SSLContext) -> tuple[str, str | None]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read(200_000)
            charset = resp.headers.get_content_charset()
    except Exception:  # noqa: BLE001 - 取得できないリンクは黙って諦める
        return url, None

    if not charset:
        m = CHARSET_RE.search(raw)
        charset = m.group(1).decode("ascii", "ignore") if m else "utf-8"

    text = raw.decode(charset, errors="replace")
    m = TITLE_RE.search(text)
    if not m:
        return url, None
    return url, re.sub(r"\s+", " ", html.unescape(m.group(1))).strip() or None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--entries", type=Path, default=Path("entries"))
    p.add_argument("--out", type=Path, default=Path("scripts/migration/link_titles.json"))
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--timeout", type=int, default=15)
    p.add_argument("--ca-bundle", help="CA 証明書のパス (証明書検証に失敗する場合に指定)")
    p.add_argument("--list", action="store_true", help="取得せず対象 URL を表示する")
    args = p.parse_args()

    urls = collect_urls(args.entries)
    print(f"{len(urls)} 件のリンク記法")

    if args.list:
        print("\n".join(f"  {u}" for u in urls))
        return 0

    known: dict[str, str] = json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else {}
    todo = [u for u in urls if u not in known]
    print(f"未取得 {len(todo)} 件を取得します")

    ctx = build_ssl_context(args.ca_bundle)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for url, title in pool.map(lambda u: fetch_title(u, args.timeout, ctx), todo):
            if title:
                known[url] = title

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(known, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    missing = [u for u in urls if u not in known]
    print(f"タイトル取得済み: {len(urls) - len(missing)} / {len(urls)} -> {args.out}")
    if missing:
        print(f"取得できなかった {len(missing)} 件は URL がそのままリンクテキストになります:", file=sys.stderr)
        for u in missing[:10]:
            print(f"  {u}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
