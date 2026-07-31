"""移行スクリプト共通のユーティリティ。"""

from __future__ import annotations

import ssl
from pathlib import Path

# python.org 配布の Python は CA バンドルを同梱せず、
# "Install Certificates.command" を実行するまで証明書検証に失敗する。
# 検証を無効化する代わりに、利用可能な CA バンドルを順に探す。
CA_BUNDLE_CANDIDATES = ("/etc/ssl/cert.pem", "/usr/local/etc/openssl/cert.pem", "/opt/homebrew/etc/ca-certificates/cert.pem")


def build_ssl_context(ca_bundle: str | None = None) -> ssl.SSLContext:
    """証明書検証を有効にしたまま使える SSLContext を返す。"""
    if ca_bundle:
        return ssl.create_default_context(cafile=ca_bundle)

    ctx = ssl.create_default_context()
    if ctx.cert_store_stats()["x509_ca"] > 0:
        return ctx

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass

    for path in CA_BUNDLE_CANDIDATES:
        if Path(path).is_file():
            return ssl.create_default_context(cafile=path)

    raise RuntimeError(
        "CA 証明書が見つかりません。--ca-bundle でパスを指定するか、"
        "'/Applications/Python 3.x/Install Certificates.command' を実行してください"
    )
