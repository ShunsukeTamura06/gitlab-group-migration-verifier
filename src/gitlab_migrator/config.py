"""環境変数からGitLab接続設定を読み込む。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class GitLabConfig:
    """GitLab API接続設定。"""

    url: str
    token: str
    timeout_seconds: float = 30.0
    max_retries: int = 3
    auth_header: str = "PRIVATE-TOKEN"
    ca_bundle: Path | None = None

    @classmethod
    def from_env(cls, prefix: str) -> "GitLabConfig":
        """指定した接頭辞の環境変数から設定を生成する。

        Args:
            prefix: `SOURCE`または`DESTINATION`などの接頭辞。

        Returns:
            検証済みの接続設定。

        Raises:
            ConfigurationError: URLまたはTokenが未設定の場合。
        """
        url = os.getenv(f"{prefix}_GITLAB_URL", "").strip().rstrip("/")
        token = os.getenv(f"{prefix}_GITLAB_TOKEN", "").strip()
        missing = [
            name
            for name, value in (
                (f"{prefix}_GITLAB_URL", url),
                (f"{prefix}_GITLAB_TOKEN", token),
            )
            if not value
        ]
        if missing:
            raise ConfigurationError(f"必須環境変数が未設定です: {', '.join(missing)}")
        parsed_url = urlparse(url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ConfigurationError(
                f"{prefix}_GITLAB_URLはhttp(s)の絶対URLで指定してください"
            )
        ca_bundle_value = os.getenv(f"{prefix}_GITLAB_CA_BUNDLE", "").strip()
        ca_bundle = Path(ca_bundle_value).expanduser() if ca_bundle_value else None
        if ca_bundle is not None and not ca_bundle.is_file():
            raise ConfigurationError(
                f"{prefix}_GITLAB_CA_BUNDLEが見つかりません: {ca_bundle}"
            )
        return cls(
            url=url,
            token=token,
            timeout_seconds=float(os.getenv("GITLAB_API_TIMEOUT", "30")),
            max_retries=int(os.getenv("GITLAB_API_MAX_RETRIES", "3")),
            auth_header="PRIVATE-TOKEN",
            ca_bundle=ca_bundle,
        )
