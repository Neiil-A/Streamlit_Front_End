# © 2026 Neiil Apshankar. All rights reserved. Personal project — not an app, platform, or business. See NOTICE.md.
"""The market findings, sealed with the site password so they can sit in a public repository.

The home machine seals the findings with the reader's password (PRESS_PASSWORD in its .env) before pushing
them to the reader's repository; the reader opens them with the password typed at the lock screen. Without the
password the file is unreadable: Fernet (AES-128-CBC with an HMAC-SHA256 check), keyed by PBKDF2-SHA256 over
the password with a fresh random salt each time. A wrong password or a changed file opens to nothing.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os

from cryptography.fernet import Fernet, InvalidToken

ROUNDS = 400_000


def _fernet(password: str, salt: bytes, rounds: int) -> Fernet:
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return Fernet(base64.urlsafe_b64encode(key))


def seal(data: dict, password: str, rounds: int = ROUNDS) -> dict:
    if not password:
        raise ValueError("no password to seal with")
    salt = os.urandom(16)
    token = _fernet(password, salt, rounds).encrypt(json.dumps(data, separators=(",", ":")).encode())
    return {"sealed": 1, "salt": salt.hex(), "rounds": rounds, "token": token.decode()}


def unseal(blob: dict, password: str) -> dict | None:
    """The findings, or None for a wrong password or a damaged file."""
    try:
        f = _fernet(password or "", bytes.fromhex(blob["salt"]), int(blob["rounds"]))
        return json.loads(f.decrypt(blob["token"].encode()))
    except (InvalidToken, KeyError, ValueError, TypeError):
        return None
