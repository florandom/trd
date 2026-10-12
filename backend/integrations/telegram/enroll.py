"""Explicit local operator enrollment. All account credentials stay off the dashboard."""

import argparse
import asyncio
import getpass
import sys

from pydantic import SecretStr
from telethon import TelegramClient, errors
from telethon.sessions import StringSession

from backend.domain.config import CollectorSettings, load_settings
from backend.infrastructure.logging import configure_logging
from backend.integrations.telegram.session import (
    StoredSession,
    load_session,
    save_session,
    session_path,
)


async def enroll(settings: CollectorSettings, replace: bool):
    settings.require_credentials()
    if session_path(settings).exists() and not replace:
        raise ValueError("Existing session requires explicit replacement")
    client = TelegramClient(
        StringSession(),
        settings.telegram_api_id,
        settings.telegram_api_hash.get_secret_value(),
        receive_updates=False,
        request_retries=0,
        connection_retries=1,
        flood_sleep_threshold=0,
        auto_reconnect=False,
        base_logger="trd.telegram.transport",
    )

    async def call(operation):
        return await asyncio.wait_for(operation, settings.telegram_request_timeout_seconds)

    try:
        await call(client.connect())
        phone = getpass.getpass("Numero Telegram con prefisso internazionale: ")
        sent = await call(client.send_code_request(phone))
        code = getpass.getpass("Codice ricevuto su Telegram: ")
        try:
            await call(client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash))
        except errors.SessionPasswordNeededError:
            password = getpass.getpass("Password di verifica in due passaggi: ")
            await call(client.sign_in(password=password))
        me = await call(client.get_me())
        if me is None or me.bot:
            raise ValueError("A human Telegram account is required")
        save_session(
            settings, StoredSession(str(me.id), SecretStr(client.session.save())), replace=replace
        )
        print("Sessione Telegram cifrata e salvata. Nessuna credenziale è stata stampata.")
    finally:
        await client.disconnect()


def main():
    parser = argparse.ArgumentParser(description="Accesso locale protetto a Telegram")
    parser.add_argument("--replace-session", action="store_true")
    parser.add_argument("--rotate-key", action="store_true")
    args = parser.parse_args()
    if not sys.stdin.isatty():
        raise SystemExit("L’accesso a Telegram richiede un terminale interattivo locale.")
    try:
        settings = load_settings("collector")
        configure_logging(settings)
        if args.rotate_key:
            old_key = getpass.getpass("Chiave precedente della sessione cifrata: ")
            old_id = input("Identificativo della chiave precedente: ").strip()
            previous = settings.model_copy(
                update={
                    "telegram_session_encryption_key": SecretStr(old_key),
                    "telegram_session_key_id": old_id,
                }
            )
            stored = load_session(previous)
            save_session(settings, stored, replace=True)
            print("Sessione ricifrata con la chiave configurata. Nessuna chiave è stata stampata.")
        else:
            asyncio.run(enroll(settings, args.replace_session))
    except (KeyboardInterrupt, EOFError):
        raise SystemExit(
            "Operazione interrotta; riavvia il servizio solo dopo un accesso riuscito."
        ) from None
    except Exception as error:
        raise SystemExit(
            f"Accesso Telegram non completato ({type(error).__name__}). "
            "Controlla la configurazione locale."
        ) from None


if __name__ == "__main__":
    main()
