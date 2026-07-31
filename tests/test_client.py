"""GitLab APIクライアントのテスト。"""

from __future__ import annotations

import unittest
import urllib.error

from gitlab_migrator.client import ApiResponse, GitLabClient
from gitlab_migrator.config import GitLabConfig
from gitlab_migrator.errors import GitLabApiError


class GitLabClientTest(unittest.TestCase):
    """リトライとエラー処理を検証する。"""

    def test_retries_server_error_and_succeeds(self) -> None:
        """一時的な5xxをリトライして成功する。"""
        responses = [
            ApiResponse(503, {}, b'{"message":"busy"}'),
            ApiResponse(200, {}, b'{"id":1}'),
        ]
        sleeps: list[float] = []

        def transport(_request: object, _timeout: float) -> ApiResponse:
            return responses.pop(0)

        client = GitLabClient(
            GitLabConfig("https://gitlab.example", "token", max_retries=1),
            transport=transport,
            sleep=sleeps.append,
        )
        self.assertEqual({"id": 1}, client.get_json("/groups/1"))
        self.assertEqual(1, len(sleeps))

    def test_retries_ssl_write_failure_with_transfer_timeout(self) -> None:
        """大容量転送の一時的なSSL write失敗を専用Timeoutで再試行する。"""
        timeouts: list[float] = []
        sleeps: list[float] = []

        def transport(_request: object, timeout: float) -> ApiResponse:
            timeouts.append(timeout)
            if len(timeouts) == 1:
                raise urllib.error.URLError(
                    "The operation did not complete (write)"
                )
            return ApiResponse(202, {}, b"{}")

        client = GitLabClient(
            GitLabConfig(
                "https://gitlab.example",
                "token",
                timeout_seconds=30,
                max_retries=1,
            ),
            transport=transport,
            sleep=sleeps.append,
        )

        response = client.request(
            "POST",
            "/projects/import",
            expected={202},
            timeout_seconds=7200,
        )

        self.assertEqual(202, response.status)
        self.assertEqual([7200, 7200], timeouts)
        self.assertEqual(1, len(sleeps))

    def test_raises_status_and_limited_body(self) -> None:
        """期待外レスポンスはステータスを保持した例外になる。"""
        client = GitLabClient(
            GitLabConfig("https://gitlab.example", "token", max_retries=0),
            transport=lambda _request, _timeout: ApiResponse(403, {}, b"forbidden"),
        )
        with self.assertRaises(GitLabApiError) as context:
            client.get_json("/groups/1")
        self.assertEqual(403, context.exception.status)
        self.assertEqual("forbidden", context.exception.body)

    def test_masks_token_in_error_body(self) -> None:
        """エラーレスポンスにTokenが含まれても外へ出さない。"""
        client = GitLabClient(
            GitLabConfig("https://gitlab.example", "do-not-leak", max_retries=0),
            transport=lambda _request, _timeout: ApiResponse(
                400,
                {},
                b'{"message":"token do-not-leak is invalid"}',
            ),
        )
        with self.assertRaises(GitLabApiError) as context:
            client.get_json("/groups/1")
        self.assertNotIn("do-not-leak", context.exception.body)
        self.assertIn("[MASKED]", context.exception.body)

    def test_uses_bearer_header_for_oauth_token(self) -> None:
        """OAuth設定ではAuthorization Bearerヘッダーを使う。"""
        captured: dict[str, str] = {}

        def transport(request: object, _timeout: float) -> ApiResponse:
            captured.update(dict(request.header_items()))  # type: ignore[attr-defined]
            return ApiResponse(200, {}, b"{}")

        client = GitLabClient(
            GitLabConfig(
                "https://gitlab.example",
                "oauth-token",
                auth_header="Authorization",
            ),
            transport=transport,
        )
        client.get_json("/groups/1")
        self.assertEqual("Bearer oauth-token", captured["Authorization"])


if __name__ == "__main__":
    unittest.main()
