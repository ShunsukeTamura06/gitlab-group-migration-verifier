"""ローカル実機検証向けの一時OAuth認証。"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .errors import ConfigurationError


def password_grant_token(
    gitlab_url: str,
    password: str,
    *,
    username: str = "root",
    timeout_seconds: float = 30.0,
    ca_bundle: Path | None = None,
) -> str:
    """Password Grantでプロセス内だけに保持するOAuth Tokenを取得する。

    Args:
        gitlab_url: GitLabのベースURL。
        password: ローカル検証用ユーザーのパスワード。
        username: GitLabユーザー名。
        timeout_seconds: HTTPタイムアウト。
        ca_bundle: 社内CA証明書Bundleへのパス。

    Returns:
        一時OAuth Access Token。

    Raises:
        ConfigurationError: 認証失敗または不正なレスポンスの場合。
    """
    body = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "username": username,
            "password": password,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{gitlab_url.rstrip('/')}/oauth/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        context = ssl.create_default_context(
            cafile=str(ca_bundle) if ca_bundle else None
        )
        with urllib.request.urlopen(
            request,
            timeout=timeout_seconds,
            context=context,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ConfigurationError("GitLab OAuth認証に失敗しました") from exc
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise ConfigurationError("GitLab OAuthレスポンスにaccess_tokenがありません")
    return token
