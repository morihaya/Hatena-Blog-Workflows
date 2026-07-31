# はてなブログ -> 静的サイト 移行スクリプト

`entries/` にある blogsync 形式の記事を、静的サイトジェネレータ (Hugo を想定) 向けの
Markdown に変換するための一式。すべて Python 3 標準ライブラリのみで動作する。

## 実行順

```bash
# 1. フォトライフ上の画像をローカルへ吸い出す (解約前に必ず実行)
python3 scripts/migration/fetch_fotolife.py --dry-run   # 対象確認
python3 scripts/migration/fetch_fotolife.py             # 取得

# 2. リンク記法のタイトルを収集する (任意・外部サイトへアクセスする)
python3 scripts/migration/fetch_link_titles.py

# 3. 記事を変換する
python3 scripts/migration/convert_entries.py --dry-run
python3 scripts/migration/convert_entries.py
```

`entries/` は一切変更せず、`content/` と `static/images/fotolife/` に出力する。
何度実行しても結果は同じ (冪等)。

## 各スクリプト

| スクリプト | 役割 | 出力 |
| --- | --- | --- |
| `fetch_fotolife.py` | `[f:id:...]` の実体を CDN から取得 | `static/images/fotolife/`, `fotolife_manifest.json` |
| `fetch_link_titles.py` | `[URL:embed:cite]` のリンク先タイトルを取得 | `link_titles.json` |
| `convert_entries.py` | front matter と本文記法の変換 | `content/` |

`fotolife_manifest.json` と `link_titles.json` はコミットしておくと、変換をやり直しても
ネットワークアクセスなしで同じ結果が得られる。

## 変換内容

| はてな | 変換後 |
| --- | --- |
| `Title:` / `Date:` / `Category:` | `title:` / `date:` / `categories:` |
| `URL:` / `EditURL:` | `hatena.url` / `hatena.edit_url` (参照用に保持) |
| `<figure ...>[f:id:...]<figcaption>X</figcaption></figure>` | `![X](/images/fotolife/<ts>.png)` |
| `[f:id:...:w30]` | `<img src="..." width="30">` |
| `[URL:embed:cite]` / `[URL:title]` | `[タイトル](URL)` |
| `[URL:embed#テキスト]` | `[テキスト](URL)` |
| `[URL:image=alt]` | `![alt](URL)` |
| `[:contents]` | `{{< toc >}}` (`--toc` で変更可) |
| `((脚注))` | `[^1]` + 末尾に定義 |

コードフェンス (```) とインラインコードの中身は変換しない。

## URL 構造

出力パスは `content/entry/YYYY/MM/DD/HHMMSS.md` となる。Hugo はデフォルトで
コンテンツの階層をそのまま URL にするため、追加設定なしで
`/entry/YYYY/MM/DD/HHMMSS/` となり、はてな時代の URL と一致する。

被リンクとはてなブックマーク数 (URL 単位で紐づく) を維持するため、この構造は変えないこと。
末尾スラッシュの有無が気になる場合は `uglyurls` ではなくリダイレクトで吸収する。

## 既知の注意点

- **記事側の記法ミス**: `entry/2023/12/30/232801.md` に閉じ括弧が 1 つ足りない
  `((...)` がある。はてな上でも脚注にならず素のテキストとして表示されているため、
  変換でもそのまま残している (警告として表示される)。
- **外部ホストの画像**: 本文に `img.esa.io` の生 `<img>` タグと、`:image=` 記法による
  外部サイト直リンク画像が含まれる。これらははてなとは無関係だが、リンク切れの
  リスクは残る。必要ならローカルへ取り込むこと。
- **生 HTML**: 記事に `<img>` などの生 HTML が含まれるため、Hugo では
  `markup.goldmark.renderer.unsafe = true` が必要。
