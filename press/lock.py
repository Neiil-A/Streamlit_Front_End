# © 2026 Neiil Apshankar. All rights reserved. Personal project — not an app, platform, or business. See NOTICE.md.
"""The reader's built-in password, kept only as a salted one-way hash (PBKDF2-SHA256, 400,000 rounds).

It can check a guess but can't be read back, so the code can sit on GitHub without a settings file.
APP_PASSWORD in the app's Secrets, if set, replaces it.
"""

from __future__ import annotations

import hashlib
import hmac

PASSWORD_SALT = "eb13cb0333d1fcfcdebea9974b8c3113"
PASSWORD_HASH = "19e63d39fe38a163e06cbe772d151dc99f337235a85876f45fef080a18513550"
ROUNDS = 400_000


def digest_of(given: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", given.encode(), bytes.fromhex(salt), ROUNDS).hex()


def matches(given: str, salt: str = PASSWORD_SALT, digest: str = PASSWORD_HASH) -> bool:
    return hmac.compare_digest(digest_of(given, salt), digest)
