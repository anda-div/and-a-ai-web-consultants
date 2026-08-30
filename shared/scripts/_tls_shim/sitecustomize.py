# -*- coding: utf-8 -*-
"""Python の起動時に自動で読まれ、証明書の検証を Windows 側へ任せる。

このフォルダを PYTHONPATH に入れた状態で python を起動すると効く。
自分のコードに手を入れられない相手（gcloud）へ対処を届けるために使う。
説明は shared/TLS_INSPECTION.md を参照。
"""
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass
