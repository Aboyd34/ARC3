"""Windows DPAPI-protected persistence for ARC3 device private keys."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import tempfile

from .identity import P256IdentityProvider


_MAGIC = b"ARC3-DPAPI-P256\x00\x01"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class KeyStoreError(RuntimeError):
    """Raised when a protected key cannot be stored or recovered safely."""


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


class WindowsDPAPI:
    """Small CryptProtectData/CryptUnprotectData adapter bound to this user."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows DPAPI is available only on Windows")
        self._crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure_functions()

    def _configure_functions(self) -> None:
        self._crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.POINTER(_DataBlob),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptProtectData.restype = wintypes.BOOL
        self._crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob), ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptUnprotectData.restype = wintypes.BOOL
        self._kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self._kernel32.LocalFree.restype = ctypes.c_void_p

    def protect(self, plaintext: bytes, entropy: bytes) -> bytes:
        return self._transform("CryptProtectData", plaintext, entropy)

    def unprotect(self, ciphertext: bytes, entropy: bytes) -> bytes:
        return self._transform("CryptUnprotectData", ciphertext, entropy)

    def _transform(self, function_name: str, value: bytes, entropy: bytes) -> bytes:
        input_blob, input_buffer = _blob(value)
        entropy_blob, entropy_buffer = _blob(entropy)
        output_blob = _DataBlob()
        # Keep both ctypes buffers alive through the native call.
        _ = (input_buffer, entropy_buffer)
        function = getattr(self._crypt32, function_name)
        if function_name == "CryptProtectData":
            success = function(
                ctypes.byref(input_blob), "ARC3 Connectivity device identity",
                ctypes.byref(entropy_blob), None, None, _CRYPTPROTECT_UI_FORBIDDEN,
                ctypes.byref(output_blob),
            )
        else:
            description = wintypes.LPWSTR()
            success = function(
                ctypes.byref(input_blob), ctypes.byref(description),
                ctypes.byref(entropy_blob), None, None, _CRYPTPROTECT_UI_FORBIDDEN,
                ctypes.byref(output_blob),
            )
            if description:
                self._kernel32.LocalFree(description)
        if not success:
            error = ctypes.get_last_error()
            raise KeyStoreError(f"Windows DPAPI operation failed with error {error}")
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            if output_blob.pbData:
                self._kernel32.LocalFree(output_blob.pbData)


class WindowsDPAPIKeyStore:
    """Load or atomically create a user-bound encrypted P-256 identity key."""

    def __init__(self, path: str | Path, dpapi: WindowsDPAPI | None = None) -> None:
        self.path = Path(path)
        self._dpapi = dpapi or WindowsDPAPI()
        self._entropy = b"ARC3 Connectivity P-256 identity v1"

    def load(self) -> P256IdentityProvider:
        try:
            content = self.path.read_bytes()
        except OSError as exc:
            raise KeyStoreError(f"unable to read protected key store: {self.path}") from exc
        if not content.startswith(_MAGIC):
            raise KeyStoreError("protected key store has an invalid format")
        protected = content[len(_MAGIC):]
        if not protected:
            raise KeyStoreError("protected key store is empty")
        try:
            private_key = self._dpapi.unprotect(protected, self._entropy)
            return P256IdentityProvider.from_private_pkcs8(private_key)
        except (OSError, ValueError) as exc:
            raise KeyStoreError("protected identity key could not be recovered") from exc

    def load_or_create(self) -> P256IdentityProvider:
        if self.path.exists():
            return self.load()
        provider = P256IdentityProvider.generate()
        protected = self._dpapi.protect(provider.export_private_pkcs8(), self._entropy)
        self._write_atomic(_MAGIC + protected)
        return provider

    def _write_atomic(self, content: bytes) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", delete=False, dir=self.path.parent,
                prefix=f".{self.path.name}.", suffix=".tmp"
            ) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                temporary_path = Path(handle.name)
            os.replace(temporary_path, self.path)
        except OSError as exc:
            raise KeyStoreError(f"unable to write protected key store: {self.path}") from exc
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()


def _blob(value: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_ubyte]]:
    raw = bytes(value)
    buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    return _DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer
