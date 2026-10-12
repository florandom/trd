"""Pure checks for full close and risk-reducing protection on synthetic positions."""

from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal, localcontext

from backend.domain.bridge import PaperPositionCommand, PaperProfile, PaperSnapshot, ProtocolError


def position_preflight(command, snapshot, profile, safety_epoch, *, now=None):
    with localcontext() as context:
        context.prec = 80
        try:
            return _position_preflight(command, snapshot, profile, safety_epoch, now=now)
        except ProtocolError:
            raise
        except (ValueError, ArithmeticError, TypeError):
            raise ProtocolError("INVALID_POSITION_INPUT") from None


def _position_preflight(command, snapshot, profile, safety_epoch, *, now=None):
    now = now or datetime.now(UTC)
    command = PaperPositionCommand.model_validate(command.model_dump())
    snapshot = PaperSnapshot.model_validate(snapshot.model_dump())
    profile = PaperProfile.model_validate(profile.model_dump())
    if (
        command.account != profile.account
        or command.account_id != profile.account_id
        or command.bridge_id != profile.bridge_id
        or command.instance_id != profile.instance_id
        or command.generation != profile.generation
        or command.profile_hash != profile.digest
        or command.safety_epoch != safety_epoch
        or command.expires_at <= now
        or snapshot.account != profile.account
        or snapshot.currency != "USD"
        or not snapshot.history_complete
        or not snapshot.portfolio_complete
        or not 0 <= (now - snapshot.observed_at).total_seconds() < 15
    ):
        raise ProtocolError("POSITION_IDENTITY_OR_FRESHNESS")
    position = next(
        (p for p in snapshot.positions if p.broker_identifier == command.position_identifier), None
    )
    if position is None or (
        position.command_id,
        position.symbol,
        position.side,
        position.volume,
        position.entry_price,
        position.stop_loss,
        position.take_profit,
    ) != (
        command.opening_command_id,
        command.symbol,
        command.side,
        command.volume,
        command.entry_price,
        command.previous_stop_loss,
        command.previous_take_profit,
    ):
        raise ProtocolError("POSITION_STATE_CHANGED")
    instrument = next((i for i in snapshot.instruments if i.symbol == command.symbol), None)
    reviewed = next((i for i in profile.instruments if i.symbol == command.symbol), None)
    quote = next((q for q in snapshot.quotes if q.symbol == command.symbol), None)
    if (
        instrument is None
        or reviewed is None
        or quote is None
        or (
            instrument.model_dump(exclude={"snapshot_id", "observed_at"})
            != reviewed.model_dump(exclude={"snapshot_id", "observed_at"})
            or instrument.quote_currency != snapshot.currency
            or not 0 <= (now - instrument.observed_at).total_seconds() < 60
            or not 0 <= (now - quote.observed_at).total_seconds() < 5
            or not quote.market_open
            or not profile.calendar.is_open(now)
        )
    ):
        raise ProtocolError("POSITION_MARKET_UNAVAILABLE")
    price = quote.bid if command.side == "BUY" else quote.ask
    low, high = command.price_band_low, command.price_band_high
    if (
        low > high
        or not low <= price <= high
        or high - low
        > 2 * min(command.max_deviation_points, profile.max_deviation_points) * instrument.point
        or (quote.ask - quote.bid) / instrument.point
        > min(command.max_spread_points, profile.max_spread_points)
        or command.volume % instrument.volume_step
        or command.volume < instrument.volume_min
        or price % instrument.tick_size
    ):
        raise ProtocolError("POSITION_PRICE_OR_VOLUME")
    if command.action == "MODIFY_STOPS":
        if (
            not instrument.attached_stops_supported
            or command.stop_loss % instrument.tick_size
            or command.take_profit % instrument.tick_size
            or (command.side == "BUY" and command.stop_loss < command.previous_stop_loss)
            or (command.side == "SELL" and command.stop_loss > command.previous_stop_loss)
        ):
            raise ProtocolError("POSITION_RISK_INCREASE")
        distance = (
            min(quote.bid - command.stop_loss, command.take_profit - quote.ask)
            if command.side == "BUY"
            else min(command.stop_loss - quote.ask, quote.bid - command.take_profit)
        )
        if (
            distance <= 0
            or distance < instrument.stops_level_points * instrument.point
            or (
                instrument.freeze_level_points
                and distance <= instrument.freeze_level_points * instrument.point
            )
        ):
            raise ProtocolError("POSITION_PROTECTION_INVALID")
    elif (command.stop_loss, command.take_profit) != (
        command.previous_stop_loss,
        command.previous_take_profit,
    ):
        raise ProtocolError("CLOSE_CANNOT_CHANGE_PROTECTION")
    return price


def realized_pnl(command, price, instrument):
    """Synthetic USD/profit-currency Forex round-trip P&L, including reviewed fees."""
    if instrument.quote_currency != "USD" or command.symbol != instrument.symbol:
        raise ProtocolError("POSITION_VALUATION_UNSUPPORTED")
    with localcontext() as context:
        context.prec = 80
        direction = Decimal(1) if command.side == "BUY" else Decimal(-1)
        result = (
            (price * command.volume - command.entry_value) * direction * instrument.contract_size
            - instrument.commission_per_lot_account * command.volume
        )
        return result.quantize(Decimal("0.0000000001"), rounding=ROUND_FLOOR)
