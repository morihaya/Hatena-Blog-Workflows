# blog.morihaya.tech

個人ブログ「もりはやメモφ(・ω・ )」のリポジトリ。

- 公開URL: https://blog.morihaya.tech/
- 生成: [Hugo](https://gohugo.io/)（自作の最小テーマ、外部テーマへの依存なし）
- ホスティング: GitHub Pages（`main` への push で自動デプロイ）

2026年8月に、はてなブログから移行した。経緯と手順は
[はてなブログからGitHub Pagesへ移行します](https://blog.morihaya.tech/entry/2026/08/01/140733/) に書いた。

## ディレクトリ構成

| パス | 役割 |
| --- | --- |
| `content/entry/YYYY/MM/DD/HHMMSS.md` | 記事。この階層がそのまま URL になる |
| `static/images/fotolife/` | はてなフォトライフから移した画像 |
| `static/images/posts/` | 移行後に追加する画像 |
| `layouts/` | テンプレート一式 |
| `assets/css/` | テーマ CSS と Chroma のシンタックスハイライト |
| `hugo.toml` | サイト設定 |
| `entries/` | はてなブログ時代の原本（変換の入力。**参照のみで変更しない**） |
| `scripts/migration/` | はてな記法の変換スクリプト（[README](scripts/migration/README.md)） |

## 記事を書く

```bash
hugo new content entry/$(date +%Y/%m/%d/%H%M%S).md
```

`archetypes/default.md` から `draft: true` の記事が生成される。書き終えたら
`draft` を `false` にして `main` へマージすると公開される。

ローカルでの確認（`-D` で下書きも表示）:

```bash
hugo server -D
```

### 画像

`static/images/posts/<記事のファイル名>/` に置き、`/images/posts/...` の絶対パスで参照する。

```markdown
![説明](/images/posts/140955/screenshot.png)
```

VS Code の PasteImage 拡張を使う場合、`.vscode/settings.json` が上記の配置に
なるよう設定してある。貼り付けるだけで正しいパスが入る。

### 目次

はてなの `[:contents]` に相当するショートコードを用意してある。

```
{{< toc >}}
```

## URL 構造について

記事の URL は `/entry/YYYY/MM/DD/HHMMSS` で、はてなブログ時代と同一。
**既存の被リンクとはてなブックマーク数がこの URL に紐づいている**ため、
`content/` の階層構造は変えないこと。

## デプロイ

`main` への push で [deploy-pages.yaml](.github/workflows/deploy-pages.yaml) が
ビルドして GitHub Pages へデプロイする。

`baseURL` は `actions/configure-pages` の出力に追従するため、
ドメインを変えてもワークフローの修正は不要。ただし**カスタムドメインの設定を
変更した直後は一度デプロイし直す必要がある**（`baseURL` はビルド時に決まるため）。

## はてなブログ側について

Pro を解約し、無料枠でアカウントとブログ（`morihaya.hatenablog.com`）を残している。
フォトライフの画像を他所から参照している可能性があるため、アカウントは削除しない。

はてなの API を叩いていた同期用ワークフローは役目を終えたため削除した。
`entries/` と `blogsync.yaml` は移行前の原本として残してある。
