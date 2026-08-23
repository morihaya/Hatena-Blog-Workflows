#!/usr/bin/env python3
"""記事内で単独行になっている URL のリンクカード情報を取得する。

取得結果は data/link_cards.json に保存し、Hugo のビルド自体は外部サイトへ
アクセスしない。取得できなかった URL は既存キャッシュを残し、新規 URL は
通常のリンクとして表示される。
"""

from __future__ import annotations

import argparse
import html
import json
import re
import ssl
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path

URL_LINE_RE = re.compile(r"^https?://[^\s<>]+$")
USER_AGENT = "Mozilla/5.0 (compatible; morihaya-blog-link-card/1.0)"
MAX_BYTES = 1_000_000


class MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.metadata: dict[str, str] = {}
        self.in_title = False
        self.title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value for key, value in attrs if value is not None}
        if tag.lower() == "title":
            self.in_title = True
        elif tag.lower() == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            content = values.get("content", "")
            if key and content and key not in self.metadata:
                self.metadata[key] = content

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def collect_urls(content_dir: Path) -> list[str]:
    urls: set[str] = set()
    for markdown in content_dir.rglob("*.md"):
        in_fence = False
        for line in markdown.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("```", "~~~")):
                in_fence = not in_fence
                continue
            if not in_fence and URL_LINE_RE.fullmatch(stripped):
                urls.add(stripped)
    return sorted(urls)


def build_ssl_context(ca_bundle: str | None) -> ssl.SSLContext:
    if ca_bundle:
        return ssl.create_default_context(cafile=ca_bundle)
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def fetch_metadata(
    url: str, timeout: int, ssl_context: ssl.SSLContext
) -> tuple[str, dict[str, str] | None]:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context) as response:
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "application/xhtml+xml"}:
                return url, None
            raw = response.read(MAX_BYTES)
            charset = response.headers.get_content_charset() or "utf-8"
            final_url = response.geturl()
    except Exception as error:  # 取得不能でもサイト生成は妨げない
        print(f"取得失敗: {url} ({error})", file=sys.stderr)
        return url, None

    parser = MetadataParser()
    try:
        parser.feed(raw.decode(charset, errors="replace"))
    except (LookupError, UnicodeError):
        parser.feed(raw.decode("utf-8", errors="replace"))

    title = normalize(parser.metadata.get("og:title", "") or "".join(parser.title_parts))
    if not title:
        return url, None

    host = urllib.parse.urlsplit(final_url).hostname or urllib.parse.urlsplit(url).hostname or url
    result = {
        "title": title,
        "site_name": normalize(parser.metadata.get("og:site_name", "")) or host.removeprefix("www."),
    }
    description = normalize(
        parser.metadata.get("og:description", "") or parser.metadata.get("description", "")
    )
    if description:
        result["description"] = description[:240]
    image = normalize(parser.metadata.get("og:image", "") or parser.metadata.get("twitter:image", ""))
    if image:
        result["image"] = urllib.parse.urljoin(final_url, image)
    return url, result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content", type=Path, default=Path("content/entry"))
    parser.add_argument("--out", type=Path, default=Path("data/link_cards.json"))
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--ca-bundle", help="利用する CA 証明書バンドルのパス")
    parser.add_argument("--refresh", action="store_true", help="取得済みの URL も再取得する")
    parser.add_argument("--list", action="store_true", help="対象 URL の一覧だけを表示する")
    args = parser.parse_args()

    urls = collect_urls(args.content)
    if args.list:
        print("\n".join(urls))
        return 0

    known: dict[str, dict[str, str]] = (
        json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else {}
    )
    targets = urls if args.refresh else [url for url in urls if url not in known]
    print(f"単独 URL: {len(urls)} 件、取得対象: {len(targets)} 件")

    ssl_context = build_ssl_context(args.ca_bundle)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for url, metadata in pool.map(
            lambda value: fetch_metadata(value, args.timeout, ssl_context), targets
        ):
            if metadata:
                known[url] = metadata

    # 記事から消えた URL はキャッシュにも残さない。
    known = {url: known[url] for url in urls if url in known}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(known, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"カード情報: {len(known)} / {len(urls)} 件 -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
