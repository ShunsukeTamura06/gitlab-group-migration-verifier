"""Windows資格情報マネージャーへTokenを安全に保存する。"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


class CredentialStoreError(RuntimeError):
    """Windows資格情報マネージャーの操作失敗を表す。"""


class _CredentialW(ctypes.Structure):
    """Win32 CREDENTIALW構造体を表す。"""

    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsCredentialStore:
    """現在のWindowsユーザーの資格情報セットを操作する。"""

    def __init__(self) -> None:
        """Advapi32のCredential APIを初期化する。

        Raises:
            CredentialStoreError: Windows以外、またはAPIを利用できない場合。
        """
        if os.name != "nt":
            raise CredentialStoreError(
                "Windows資格情報マネージャーはWindowsでのみ利用できます"
            )
        try:
            win_dll = ctypes.WinDLL
            self._advapi32 = win_dll("Advapi32.dll", use_last_error=True)
        except (AttributeError, OSError) as exc:
            raise CredentialStoreError(
                "Windows資格情報マネージャーを開けません"
            ) from exc
        self._configure_api()

    def _configure_api(self) -> None:
        """Win32 APIの引数型と戻り値型を設定する。"""
        credential_pointer = ctypes.POINTER(_CredentialW)
        self._advapi32.CredWriteW.argtypes = [
            credential_pointer,
            wintypes.DWORD,
        ]
        self._advapi32.CredWriteW.restype = wintypes.BOOL
        self._advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(credential_pointer),
        ]
        self._advapi32.CredReadW.restype = wintypes.BOOL
        self._advapi32.CredDeleteW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self._advapi32.CredDeleteW.restype = wintypes.BOOL
        self._advapi32.CredFree.argtypes = [ctypes.c_void_p]
        self._advapi32.CredFree.restype = None

    def read(self, target: str) -> str | None:
        """保存済みのTokenを取得する。

        Args:
            target: 資格情報を識別するTarget名。

        Returns:
            保存済みToken。存在しない場合はNone。

        Raises:
            CredentialStoreError: 読み取りやUTF-8復号に失敗した場合。
        """
        credential_pointer = ctypes.POINTER(_CredentialW)()
        succeeded = self._advapi32.CredReadW(
            target,
            CRED_TYPE_GENERIC,
            0,
            ctypes.byref(credential_pointer),
        )
        if not succeeded:
            error_code = ctypes.get_last_error()
            if error_code == ERROR_NOT_FOUND:
                return None
            raise CredentialStoreError(
                f"Windows資格情報を読み取れません: error={error_code}"
            )
        try:
            credential = credential_pointer.contents
            token_bytes = ctypes.string_at(
                credential.CredentialBlob,
                credential.CredentialBlobSize,
            )
            try:
                return token_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise CredentialStoreError(
                    "保存済みWindows資格情報の形式が不正です"
                ) from exc
        finally:
            self._advapi32.CredFree(credential_pointer)

    def write(self, target: str, token: str) -> None:
        """Tokenを現在のWindowsユーザー用資格情報として保存する。

        Args:
            target: 資格情報を識別するTarget名。
            token: 保存するAccess Token。

        Raises:
            CredentialStoreError: Tokenが空、または保存に失敗した場合。
        """
        token_bytes = token.encode("utf-8")
        if not token_bytes:
            raise CredentialStoreError("空のTokenは保存できません")
        blob = (ctypes.c_ubyte * len(token_bytes)).from_buffer_copy(token_bytes)
        credential = _CredentialW()
        credential.Flags = 0
        credential.Type = CRED_TYPE_GENERIC
        credential.TargetName = target
        credential.Comment = "GitLab Group Migrator access token"
        credential.CredentialBlobSize = len(token_bytes)
        credential.CredentialBlob = ctypes.cast(
            blob,
            ctypes.POINTER(ctypes.c_ubyte),
        )
        credential.Persist = CRED_PERSIST_LOCAL_MACHINE
        credential.AttributeCount = 0
        credential.Attributes = None
        credential.TargetAlias = None
        credential.UserName = "gitlab-group-migrator"
        try:
            if not self._advapi32.CredWriteW(ctypes.byref(credential), 0):
                error_code = ctypes.get_last_error()
                raise CredentialStoreError(
                    f"Windows資格情報を保存できません: error={error_code}"
                )
        finally:
            ctypes.memset(blob, 0, len(token_bytes))

    def delete(self, target: str) -> bool:
        """保存済みのTokenを削除する。

        Args:
            target: 資格情報を識別するTarget名。

        Returns:
            削除した場合True、元から存在しなかった場合False。

        Raises:
            CredentialStoreError: 削除に失敗した場合。
        """
        if self._advapi32.CredDeleteW(target, CRED_TYPE_GENERIC, 0):
            return True
        error_code = ctypes.get_last_error()
        if error_code == ERROR_NOT_FOUND:
            return False
        raise CredentialStoreError(
            f"Windows資格情報を削除できません: error={error_code}"
        )
