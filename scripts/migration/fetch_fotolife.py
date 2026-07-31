#!/usr/bin/env python3
"""はてなフォトライフ上の画像をローカルへ吸い出す。

entries/ 配下の `[f:id:<user>:<timestamp><ext>:...]` 記法を走査し、
実体を CDN からダウンロードして manifest を出力する。
convert_entries.py はこの manifest を読んで画像パスを書き換える。

標準ライブラリのみで動作する。

  # 何がダウンロードされるかだけ確認
  python3 scripts/migration/fetch_fotolife.py --dry-run

  # 実際に取得（既にあるファイルはスキップ）
  python3 scripts/migration/fetch_fotolife.py
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_ssl_context  # noqa: E402

# [f:id:morihaya:20220423001109p:plain] / :plain:alt=foo / :plain:w30 など
FOTOLIFE_RE = re.compile(r"\[f:id:(?P<user>[^:\]]+):(?P<ts>\d{14})(?P<kind>[a-z]?):(?P<opts>[^\]]*)\]")

# 記法末尾の 1 文字が画像フォーマットを表す
KIND_TO_EXT = {"p": "png", "j": "jpg", "g": "gif", "": "jpg"}

CDN_BASE = "https://cdn-ak.f.st-hatena.com/images/fotolife"
USER_AGENT = "hatena-blog-migration/1.0 (+local archive script)"


@dataclass
class Ref:
    """記事中の 1 画像参照。"""

    user: str
    ts: str
    kind: str

    @property
    def key(self) -> str:
        return f"f:id:{self.user}:{self.ts}{self.kind}"

    @property
    def ext(self) -> str:
        return KIND_TO_EXT.get(self.kind, "jpg")

    def url(self, ext: str | None = None) -> str:
        return f"{CDN_BASE}/{self.user[0]}/{self.user}/{self.ts[:8]}/{self.ts}.{ext or self.ext}"


@dataclass
class Result:
    key: str
    url: str
    local: str
    bytes: int
    status: str  # downloaded | cached | failed


def collect_refs(entries_dir: Path) -> dict[str, tuple[Ref, list[str]]]:
    """全記事を走査して画像参照を重複排除しつつ集める。"""
    found: dict[str, tuple[Ref, list[str]]] = {}
    for md in sorted(entries_dir.rglob("*.md")):
        text = md.read_text(encoding="utf-8")
        for m in FOTOLIFE_RE.finditer(text):
            ref = Ref(m.group("user"), m.group("ts"), m.group("kind"))
            entry = found.setdefault(ref.key, (ref, []))
            if str(md) not in entry[1]:
                entry[1].append(str(md))
    return found


def fetch(url: str, timeout: int, retries: int, ctx: "ssl.SSLContext") -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise  # 拡張子違いは呼び出し側でフォールバックする
            last = e
        except Exception as e:  # noqa: BLE001 - ネットワーク起因は一律リトライ
            last = e
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def download_one(ref: Ref, out_dir: Path, timeout: int, retries: int, ctx: "ssl.SSLContext") -> Result:
    """記法上の拡張子で取得し、404 なら他の拡張子を順に試す。"""
    candidates = [ref.ext] + [e for e in ("png", "jpg", "gif", "jpeg") if e != ref.ext]

    for ext in candidates:
        dest = out_dir / f"{ref.ts}.{ext}"
        if dest.exists() and dest.stat().st_size > 0:
            return Result(ref.key, ref.url(ext), str(dest), dest.stat().st_size, "cached")

    for ext in candidates:
        url = ref.url(ext)
        try:
            data = fetch(url, timeout, retries, ctx)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            return Result(ref.key, url, "", 0, f"failed: HTTP {e.code}")
        except Exception as e:  # noqa: BLE001
            return Result(ref.key, url, "", 0, f"failed: {e}")

        dest = out_dir / f"{ref.ts}.{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return Result(ref.key, url, str(dest), len(data), "downloaded")

    return Result(ref.key, ref.url(), "", 0, "failed: not found (all extensions 404)")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--entries", type=Path, default=Path("entries"), help="記事ディレクトリ (default: entries)")
    p.add_argument("--out", type=Path, default=Path("static/images/fotolife"), help="画像の保存先")
    p.add_argument("--manifest", type=Path, default=Path("scripts/migration/fotolife_manifest.json"))
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--ca-bundle", help="CA 証明書のパス (証明書検証に失敗する場合に指定)")
    p.add_argument("--dry-run", action="store_true", help="取得せず対象一覧だけ表示する")
    args = p.parse_args()

    if not args.entries.is_dir():
        print(f"error: {args.entries} が見つかりません", file=sys.stderr)
        return 1

    refs = collect_refs(args.entries)
    if not refs:
        print("画像参照は見つかりませんでした。")
        return 0

    total_files = len({f for _, files in refs.values() for f in files})
    print(f"{len(refs)} 件のユニークな画像参照 / {total_files} ファイル")

    if args.dry_run:
        for key, (ref, files) in sorted(refs.items()):
            print(f"  {ref.url()}  <- {len(files)} 記事")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    ctx = build_ssl_context(args.ca_bundle)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda r: download_one(r, args.out, args.timeout, args.retries, ctx), [r for r, _ in refs.values()]))

    manifest = {}
    failed: list[Result] = []
    for res in results:
        manifest[res.key] = asdict(res) | {"entries": refs[res.key][1]}
        if res.status.startswith("failed"):
            failed.append(res)

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    ok = [r for r in results if not r.status.startswith("failed")]
    size_mb = sum(r.bytes for r in ok) / 1024 / 1024
    print(f"取得済み: {len(ok)} 件 ({size_mb:.1f} MB) -> {args.out}")
    print(f"manifest: {args.manifest}")

    if failed:
        print(f"\n失敗 {len(failed)} 件:", file=sys.stderr)
        for r in failed:
            print(f"  {r.key}: {r.status}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
