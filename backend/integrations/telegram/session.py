"""Authenticated session envelope; no plaintext session is written to disk."""

import json
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

from backend.domain.config import CollectorSettings
from backend.domain.telegram import valid_account


class SessionError(ValueError):
    pass


@dataclass(frozen=True, repr=False)
class StoredSession:
    account_id: str
    credential: SecretStr


def session_path(settings: CollectorSettings) -> Path:
    return settings.telegram_session_path or settings.data_dir / "telegram.session.enc"


def _metadata(settings: CollectorSettings, account_id: str) -> dict:
    if not valid_account(account_id):
        raise SessionError("Invalid enrolled Telegram account")
    return {
        "schema": 1,
        "environment": settings.environment_id,
        "collector": settings.telegram_collector_identity,
        "account": account_id,
        "key_id": settings.telegram_session_key_id,
    }


def _aad(metadata: dict) -> bytes:
    return json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()


def save_session(settings: CollectorSettings, stored: StoredSession, *, replace: bool = False):
    settings.require_credentials()
    path = session_path(settings)
    if path.is_symlink() or (path.exists() and not replace):
        raise SessionError("Existing session requires explicit rotation or re-enrollment")
    credential = stored.credential.get_secret_value()
    if not 1 <= len(credential) <= 8192:
        raise SessionError("Invalid session boundary")
    metadata = _metadata(settings, stored.account_id)
    nonce = secrets.token_bytes(12)
    cipher = AESGCM(bytes.fromhex(settings.telegram_session_encryption_key.get_secret_value()))
    envelope = {
        **metadata,
        "nonce": nonce.hex(),
        "ciphertext": cipher.encrypt(nonce, credential.encode(), _aad(metadata)).hex(),
    }
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".new")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(envelope, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
        if hasattr(os, "O_DIRECTORY"):
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def load_session(settings: CollectorSettings) -> StoredSession:
    settings.require_credentials()
    path = session_path(settings)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 20_000:
            raise ValueError
        if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ValueError
        envelope = json.loads(path.read_text(encoding="utf-8"))
        if set(envelope) != {
            "schema",
            "environment",
            "collector",
            "account",
            "key_id",
            "nonce",
            "ciphertext",
        }:
            raise ValueError
        metadata = _metadata(settings, envelope["account"])
        if any(envelope[key] != value for key, value in metadata.items()):
            raise ValueError
        nonce = bytes.fromhex(envelope["nonce"])
        if len(nonce) != 12:
            raise ValueError
        cipher = AESGCM(bytes.fromhex(settings.telegram_session_encryption_key.get_secret_value()))
        credential = cipher.decrypt(nonce, bytes.fromhex(envelope["ciphertext"]), _aad(metadata))
        if not 1 <= len(credential) <= 8192:
            raise ValueError
        return StoredSession(metadata["account"], SecretStr(credential.decode()))
    except Exception:
        raise SessionError("Telegram session missing, unsafe or authentication failed") from None
