"""Windows secure storage helpers for sensitive local secrets."""

from __future__ import annotations

import base64
import ctypes
import sys
from ctypes import wintypes


class SecureStorageError(RuntimeError):
    """Raised when secure storage operations fail."""


if sys.platform == "win32":
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    CRYPTPROTECT_UI_FORBIDDEN = 0x01

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]


def _build_blob(data: bytes) -> tuple[DATA_BLOB, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data)
    blob = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    return blob, buffer


class SecureStorage:
    """Encrypt and decrypt secrets using Windows DPAPI."""

    ENTROPY = b"AssistIM.AuthTokens"

    @classmethod
    def encrypt_text(cls, value: str) -> str:
        if not value:
            return ""
        if sys.platform != "win32":
            raise SecureStorageError("Windows DPAPI is required for token encryption")

        plaintext = value.encode("utf-8")
        input_blob, _ = _build_blob(plaintext)
        entropy_blob, _ = _build_blob(cls.ENTROPY)
        output_blob = DATA_BLOB()

        success = crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            "AssistIM",
            ctypes.byref(entropy_blob),
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )
        if not success:
            raise SecureStorageError("Failed to encrypt secret with Windows DPAPI")

        try:
            encrypted = ctypes.string_at(output_blob.pbData, output_blob.cbData)
            return base64.b64encode(encrypted).decode("ascii")
        finally:
            kernel32.LocalFree(output_blob.pbData)

    @classmethod
    def decrypt_text(cls, value: str) -> str:
        if not value:
            return ""
        if sys.platform != "win32":
            raise SecureStorageError("Windows DPAPI is required for token decryption")

        ciphertext = base64.b64decode(value.encode("ascii"))
        input_blob, _ = _build_blob(ciphertext)
        entropy_blob, _ = _build_blob(cls.ENTROPY)
        output_blob = DATA_BLOB()

        success = crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            ctypes.byref(entropy_blob),
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )
        if not success:
            raise SecureStorageError("Failed to decrypt secret with Windows DPAPI")

        try:
            decrypted = ctypes.string_at(output_blob.pbData, output_blob.cbData)
            return decrypted.decode("utf-8")
        finally:
            kernel32.LocalFree(output_blob.pbData)


__all__ = ["SecureStorage", "SecureStorageError"]
