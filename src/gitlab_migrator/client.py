"""依存ライブラリを持たないGitLab APIクライアント。"""

from __future__ import annotations

import json
import mimetypes
import random
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import GitLabConfig
from .errors import GitLabApiError


@dataclass(frozen=True, slots=True)
class ApiResponse:
    """GitLab APIレスポンス。"""

    status: int
    headers: Mapping[str, str]
    body: bytes

    def json(self) -> Any:
        """レスポンス本文をJSONとして返す。"""
        if not self.body:
            return {}
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitLabApiError(
                "GitLab APIレスポンスをJSONとして解析できません",
                status=self.status,
            ) from exc


Transport = Callable[[urllib.request.Request, float], ApiResponse]


class GitLabClient:
    """タイムアウトと限定的なリトライを備えたGitLab APIクライアント。"""

    def __init__(
        self,
        config: GitLabConfig,
        *,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """クライアントを初期化する。

        Args:
            config: GitLab接続設定。
            transport: テスト用のHTTP送信関数。
            sleep: リトライ待機関数。
        """
        self.config = config
        self._ssl_context = ssl.create_default_context(
            cafile=str(config.ca_bundle) if config.ca_bundle else None
        )
        self._transport = transport or self._urlopen_transport
        self._sleep = sleep

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        expected: set[int] | None = None,
        timeout_seconds: float | None = None,
    ) -> ApiResponse:
        """GitLab APIへHTTPリクエストを送信する。

        Args:
            method: HTTPメソッド。
            path: `/groups`から始まるAPI相対パス。
            params: クエリパラメータ。
            data: リクエスト本文。
            headers: 追加HTTPヘッダー。
            expected: 正常として扱うHTTPステータス。
            timeout_seconds: このリクエスト専用の通信Timeout。

        Returns:
            APIレスポンス。

        Raises:
            GitLabApiError: APIが期待外のレスポンスを返した場合。
        """
        expected_statuses = expected or {200}
        request_timeout = (
            self.config.timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        if request_timeout <= 0:
            raise ValueError("通信Timeoutは正数で指定してください")
        query = urllib.parse.urlencode(params or {}, doseq=True)
        api_path = path if path.startswith("/") else f"/{path}"
        url = f"{self.config.url}/api/v4{api_path}"
        if query:
            url = f"{url}?{query}"
        auth_value = (
            f"Bearer {self.config.token}"
            if self.config.auth_header.lower() == "authorization"
            else self.config.token
        )
        request_headers = {self.config.auth_header: auth_value, "Accept": "application/json"}
        request_headers.update(headers or {})
        request = urllib.request.Request(url, data=data, headers=request_headers, method=method)

        response: ApiResponse | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self._transport(request, request_timeout)
            except (TimeoutError, urllib.error.URLError) as exc:
                if attempt >= self.config.max_retries:
                    raise GitLabApiError(
                        "GitLab APIへの接続に失敗しました"
                        f"（{attempt + 1}回試行、通信Timeout={request_timeout:g}秒）: "
                        f"{exc}"
                    ) from exc
                self._sleep(self._retry_delay(attempt))
                continue
            if response.status in expected_statuses:
                return response
            if (
                response.status == 429 or response.status >= 500
            ) and attempt < self.config.max_retries:
                retry_after = response.headers.get("Retry-After")
                delay = (
                    float(retry_after)
                    if retry_after and retry_after.isdigit()
                    else self._retry_delay(attempt)
                )
                self._sleep(delay)
                continue
            break

        assert response is not None
        body = self._safe_error_body(response.body)
        raise GitLabApiError(
            f"GitLab APIがHTTP {response.status}を返しました: {method} {api_path}",
            status=response.status,
            body=body,
        )

    def get_json(self, path: str, *, params: Mapping[str, Any] | None = None) -> Any:
        """GETリクエストを送りJSONを返す。"""
        return self.request("GET", path, params=params).json()

    def list_all(self, path: str, *, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """ページネーションされたAPIを最後まで取得する。"""
        page = 1
        result: list[dict[str, Any]] = []
        while True:
            page_params = dict(params or {})
            page_params.update({"page": page, "per_page": 100})
            response = self.request("GET", path, params=page_params)
            payload = response.json()
            if not isinstance(payload, list):
                raise GitLabApiError(f"一覧APIが配列以外を返しました: {path}", status=response.status)
            result.extend(item for item in payload if isinstance(item, dict))
            next_page = response.headers.get("X-Next-Page", "")
            if next_page:
                page = int(next_page)
            elif len(payload) == 100:
                page += 1
            else:
                break
        return result

    def post_form(
        self,
        path: str,
        fields: Mapping[str, Any],
        *,
        expected: set[int] | None = None,
    ) -> ApiResponse:
        """URLエンコードしたフォームをPOSTする。"""
        body = urllib.parse.urlencode(fields).encode("utf-8")
        return self.request(
            "POST",
            path,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            expected=expected or {200, 201, 202},
        )

    def put_form(
        self,
        path: str,
        fields: Mapping[str, Any],
        *,
        expected: set[int] | None = None,
    ) -> ApiResponse:
        """URLエンコードしたフォームをPUTする。"""
        body = urllib.parse.urlencode(fields, doseq=True).encode("utf-8")
        return self.request(
            "PUT",
            path,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            expected=expected or {200},
        )

    def post_multipart(
        self,
        path: str,
        fields: Mapping[str, Any],
        *,
        file_field: str,
        file_path: Path,
        expected: set[int] | None = None,
        timeout_seconds: float | None = None,
    ) -> ApiResponse:
        """ファイルをmultipart/form-dataとしてPOSTする。

        Args:
            path: API相対パス。
            fields: Form項目。
            file_field: Upload FileのForm項目名。
            file_path: UploadするFile。
            expected: 正常として扱うHTTPステータス。
            timeout_seconds: Upload専用の通信Timeout。

        Returns:
            APIレスポンス。
        """
        boundary = f"----gitlab-migrator-{uuid.uuid4().hex}"
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                    str(value).encode("utf-8"),
                    b"\r\n",
                ]
            )
        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{file_field}"; '
                    f'filename="{file_path.name}"\r\n'
                ).encode(),
                f"Content-Type: {mime_type}\r\n\r\n".encode(),
                file_path.read_bytes(),
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )
        return self.request(
            "POST",
            path,
            data=b"".join(chunks),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            expected=expected or {200, 201, 202},
            timeout_seconds=timeout_seconds,
        )

    @staticmethod
    def encode_id(value: int | str) -> str:
        """Group IDまたはFull PathをURL用にエンコードする。"""
        return urllib.parse.quote(str(value), safe="")

    def _urlopen_transport(
        self, request: urllib.request.Request, timeout: float
    ) -> ApiResponse:
        """urllibを使ってHTTPリクエストを送信する。"""
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout,
                context=self._ssl_context,
            ) as response:
                return ApiResponse(response.status, dict(response.headers.items()), response.read())
        except urllib.error.HTTPError as exc:
            return ApiResponse(exc.code, dict(exc.headers.items()), exc.read())

    @staticmethod
    def _retry_delay(attempt: int) -> float:
        """ジッター付き指数バックオフ時間を返す。"""
        return min(8.0, (2**attempt) + random.uniform(0.0, 0.25))

    def _safe_error_body(self, body: bytes) -> str:
        """Tokenをマスクし、長すぎるエラーレスポンスを切り詰める。"""
        text = body.decode("utf-8", errors="replace")
        if self.config.token:
            text = text.replace(self.config.token, "[MASKED]")
        return text[:1000]
