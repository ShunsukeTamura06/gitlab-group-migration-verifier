"""移行処理で使用する例外。"""


class MigratorError(Exception):
    """移行処理の基底例外。"""


class ConfigurationError(MigratorError):
    """設定値が不足または不正な場合の例外。"""


class GitLabApiError(MigratorError):
    """GitLab APIが期待外の応答を返した場合の例外。"""

    def __init__(self, message: str, *, status: int | None = None, body: str = "") -> None:
        """例外を初期化する。

        Args:
            message: 利用者向けのエラーメッセージ。
            status: HTTPステータスコード。
            body: 秘密情報を含まない範囲のレスポンス本文。
        """
        super().__init__(message)
        self.status = status
        self.body = body


class ExportTimeoutError(MigratorError):
    """Exportファイル生成が時間内に終わらない場合の例外。"""


class ArchiveValidationError(MigratorError):
    """Exportアーカイブが不正な場合の例外。"""


class ExistingGroupError(MigratorError):
    """移行先に同一パスのGroupが存在する場合の例外。"""


class HierarchyError(MigratorError):
    """Group階層に循環や重複がある場合の例外。"""


class TreeVerificationError(MigratorError):
    """GroupまたはProjectツリーの必須検証に失敗した場合の例外。"""
