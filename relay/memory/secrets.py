"""Secure key storage using Windows DPAPI (Data Protection API).
This module uses `ctypes` to encrypt and decrypt secrets so they are protected by the current user's Windows login, meaning no other user on the machine can decrypt them.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
from pathlib import Path


# DPAPI Structures
class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]

def _protect_data(data: bytes, entropy: bytes = b"") -> bytes:
    try:
        crypt32 = ctypes.windll.crypt32
    except AttributeError:
        return data  # Not on Windows or crypt32 unavailable
    
    blob_in = DATA_BLOB(len(data), ctypes.cast(ctypes.c_char_p(data), ctypes.POINTER(ctypes.c_char)))
    blob_entropy = None
    if entropy:
        blob_entropy = DATA_BLOB(len(entropy), ctypes.cast(ctypes.c_char_p(entropy), ctypes.POINTER(ctypes.c_char)))
    
    blob_out = DATA_BLOB()
    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    
    if crypt32.CryptProtectData(ctypes.byref(blob_in), None, 
                                ctypes.byref(blob_entropy) if blob_entropy else None, 
                                None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out)):
        result = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return result
    return b""

def _unprotect_data(data: bytes, entropy: bytes = b"") -> bytes:
    try:
        crypt32 = ctypes.windll.crypt32
    except AttributeError:
        return data  
    
    blob_in = DATA_BLOB(len(data), ctypes.cast(ctypes.c_char_p(data), ctypes.POINTER(ctypes.c_char)))
    blob_entropy = None
    if entropy:
        blob_entropy = DATA_BLOB(len(entropy), ctypes.cast(ctypes.c_char_p(entropy), ctypes.POINTER(ctypes.c_char)))
        
    blob_out = DATA_BLOB()
    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    
    if crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, 
                                  ctypes.byref(blob_entropy) if blob_entropy else None, 
                                  None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out)):
        result = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return result
    return b""


def _get_secrets_file() -> Path:
    from relay.config import user_data_dir
    return user_data_dir() / "secrets.bin"

def save_secret(key: str, value: str) -> None:
    """Encrypt and save a secret."""
    import json
    f = _get_secrets_file()
    
    secrets = {}
    if f.exists():
        try:
            decrypted = _unprotect_data(f.read_bytes())
            if decrypted:
                secrets = json.loads(decrypted.decode("utf-8"))
        except Exception:
            pass
            
    secrets[key] = value
    encrypted = _protect_data(json.dumps(secrets).encode("utf-8"))
    if encrypted:
        f.write_bytes(encrypted)

def get_secret(key: str, default: str = "") -> str:
    """Retrieve and decrypt a secret."""
    import json
    f = _get_secrets_file()
    if not f.exists():
        return default
        
    try:
        decrypted = _unprotect_data(f.read_bytes())
        if not decrypted:
            return default
        secrets = json.loads(decrypted.decode("utf-8"))
        return secrets.get(key, default)
    except Exception:
        return default

def delete_secret(key: str) -> None:
    import json
    f = _get_secrets_file()
    if not f.exists():
        return
        
    try:
        decrypted = _unprotect_data(f.read_bytes())
        if decrypted:
            secrets = json.loads(decrypted.decode("utf-8"))
            if key in secrets:
                del secrets[key]
                encrypted = _protect_data(json.dumps(secrets).encode("utf-8"))
                if encrypted:
                    f.write_bytes(encrypted)
    except Exception:
        pass
