"""Read-only MTProto port. No joins, sends, link fetching or media downloads."""

import asyncio
from dataclasses import dataclass
from datetime import datetime

from pydantic import SecretStr
from telethon import TelegramClient, errors, types, utils
from telethon.sessions import StringSession

from backend.domain.config import CollectorSettings
from backend.domain.telegram import TelegramObservation
from backend.integrations.telegram.session import StoredSession, save_session


class TelegramUnavailable(RuntimeError):
    def __init__(self, code: str, *, retry_after: int = 0):
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after


@dataclass(frozen=True)
class Peer:
    id: str
    kind: str
    access_hash: str | None = None

    def input_peer(self):
        if self.kind == "CHANNEL":
            return types.InputPeerChannel(int(self.id[4:]), int(self.access_hash))
        return types.InputPeerChat(-int(self.id))


def observation(message) -> TelegramObservation | None:
    if not isinstance(message, (types.Message, types.MessageService)):
        return None
    media = getattr(message, "media", None)
    media_kind = (
        "NONE"
        if media is None
        else (
            "PHOTO"
            if isinstance(media, types.MessageMediaPhoto)
            else "DOCUMENT"
            if isinstance(media, types.MessageMediaDocument)
            else "OTHER"
        )
    )
    return TelegramObservation(
        message_id=message.id,
        kind="EDIT" if getattr(message, "edit_date", None) else "NEW",
        body=getattr(message, "message", "") or "",
        published_at=message.date,
        observed_at=getattr(message, "edit_date", None) or message.date,
        reply_message_id=getattr(getattr(message, "reply_to", None), "reply_to_msg_id", None),
        media_kind=media_kind,
    )


class ReadOnlyTelegramClient:
    def __init__(self, settings: CollectorSettings, stored: StoredSession):
        self.settings = settings
        self.stored = stored
        self.client = TelegramClient(
            StringSession(stored.credential.get_secret_value()),
            settings.telegram_api_id,
            settings.telegram_api_hash.get_secret_value(),
            receive_updates=False,
            auto_reconnect=False,
            connection_retries=1,
            request_retries=0,
            flood_sleep_threshold=0,
            raise_last_call_error=True,
            timeout=settings.telegram_request_timeout_seconds,
            base_logger="trd.telegram.transport",
        )

    async def _call(self, operation):
        try:
            return await asyncio.wait_for(operation, self.settings.telegram_request_timeout_seconds)
        except errors.FloodWaitError as error:
            raise TelegramUnavailable("FLOOD_WAIT", retry_after=max(1, error.seconds)) from None
        except (
            errors.SessionRevokedError,
            errors.AuthKeyUnregisteredError,
            errors.UserDeactivatedError,
            errors.AuthKeyDuplicatedError,
        ):
            raise TelegramUnavailable("SESSION_REVOKED") from None
        except (
            errors.ChannelPrivateError,
            errors.ChatAdminRequiredError,
            errors.UsernameInvalidError,
            errors.UsernameNotOccupiedError,
        ):
            raise TelegramUnavailable("SOURCE_UNAVAILABLE") from None
        except (OSError, TimeoutError, ConnectionError):
            raise TelegramUnavailable("DISCONNECTED") from None
        except errors.RPCError:
            raise TelegramUnavailable("TELEGRAM_ERROR") from None

    async def connect(self):
        await self._call(self.client.connect())
        if not await self._call(self.client.is_user_authorized()):
            raise TelegramUnavailable("SESSION_REVOKED")
        me = await self._call(self.client.get_me())
        if me is None or me.bot or str(me.id) != self.stored.account_id:
            raise TelegramUnavailable("ACCOUNT_MISMATCH")

    async def disconnect(self):
        await self.client.disconnect()

    def persist_session(self):
        """Keep changed DC/auth state durable without writing a plaintext session."""
        credential = self.client.session.save()
        if credential != self.stored.credential.get_secret_value():
            updated = StoredSession(self.stored.account_id, SecretStr(credential))
            save_session(self.settings, updated, replace=True)
            self.stored = updated

    async def resolve(self, reference: str) -> Peer:
        if reference.startswith("@"):
            entity = await self._call(self.client.get_entity(reference))
        else:
            # StringSession has no durable entity cache. Resolve an explicitly requested
            # joined peer by paging at most 500 dialog metadata entries, never their text.
            entity = None

            async def find_dialog():
                async for dialog in self.client.iter_dialogs(limit=500):
                    if str(utils.get_peer_id(dialog.entity)) == reference:
                        return dialog.entity
                return None

            entity = await self._call(find_dialog())
        if isinstance(entity, types.Channel) and not getattr(entity, "left", False):
            return Peer(str(utils.get_peer_id(entity)), "CHANNEL", str(entity.access_hash))
        if isinstance(entity, types.Chat) and not getattr(entity, "deactivated", False):
            return Peer(str(utils.get_peer_id(entity)), "CHAT")
        raise TelegramUnavailable("SOURCE_UNAVAILABLE")

    async def history(
        self, peer: Peer, *, after: int, since: datetime, limit: int, newest: bool = False
    ) -> list[TelegramObservation]:
        async def collect():
            result = []
            async for message in self.client.iter_messages(
                peer.input_peer(),
                limit=limit,
                min_id=0 if newest else after,
                reverse=not newest,
                offset_date=None if newest or after else since,
            ):
                event = observation(message)
                if event is not None:
                    result.append(event)
            return result

        return await self._call(collect())

    async def check_ids(self, peer: Peer, ids: list[int]) -> dict[int, TelegramObservation | None]:
        messages = await self._call(self.client.get_messages(peer.input_peer(), ids=ids))
        return {key: observation(message) for key, message in zip(ids, messages, strict=True)}
