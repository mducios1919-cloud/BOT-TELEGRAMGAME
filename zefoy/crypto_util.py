"""CryptoJS-compatible AES helpers used by zefoy.com captcha_encoded field."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any, Mapping, Union

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

# Hardcoded passphrase from site JS (obfuscated string parts concatenated)
AES_PASSPHRASE = "43fdda1192dde7f8ffff7161e13580d7"


def evp_bytes_to_key(
    password: bytes,
    salt: bytes,
    key_len: int = 32,
    iv_len: int = 16,
) -> tuple[bytes, bytes]:
    """OpenSSL EVP_BytesToKey (MD5) — CryptoJS default KDF for passphrase keys."""
    derived = b""
    block = b""
    while len(derived) < key_len + iv_len:
        block = hashlib.md5(block + password + salt).digest()
        derived += block
    return derived[:key_len], derived[key_len : key_len + iv_len]


def encrypt_cryptojs_json(
    plaintext: Union[str, Mapping[str, Any]],
    passphrase: str = AES_PASSPHRASE,
) -> str:
    """
    Encrypt like: CryptoJS.AES.encrypt(msg, pass, {format: CryptoJSAesJson}).toString()

    Returns JSON string: {"ct":"...","iv":"...","s":"..."}
    """
    if not isinstance(plaintext, str):
        plaintext = json.dumps(plaintext, separators=(",", ":"), ensure_ascii=False)

    salt = os.urandom(8)
    key, iv = evp_bytes_to_key(passphrase.encode("utf-8"), salt)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    ciphertext = cipher.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))
    payload = {
        "ct": base64.b64encode(ciphertext).decode("ascii"),
        "iv": iv.hex(),
        "s": salt.hex(),
    }
    return json.dumps(payload, separators=(",", ":"))


def decrypt_cryptojs_json(
    blob: Union[str, Mapping[str, Any]],
    passphrase: str = AES_PASSPHRASE,
) -> str:
    """Decrypt a CryptoJSAesJson payload back to plaintext string."""
    data = json.loads(blob) if isinstance(blob, str) else dict(blob)
    ct = base64.b64decode(data["ct"])
    salt = bytes.fromhex(data["s"])
    key, iv_kdf = evp_bytes_to_key(passphrase.encode("utf-8"), salt)

    candidates = [iv_kdf]
    if data.get("iv"):
        candidates.append(bytes.fromhex(data["iv"]))

    last_err: Exception | None = None
    for iv in candidates:
        try:
            cipher = AES.new(key, AES.MODE_CBC, iv)
            return unpad(cipher.decrypt(ct), AES.block_size).decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    raise ValueError(f"Failed to decrypt captcha_encoded: {last_err}")
