from datetime import datetime, timezone

from nonebot.adapters import Event


class EventTimestampError(ValueError):
    pass


def event_timestamp_ms(event: Event) -> int:
    event_module = type(event).__module__
    try:
        if event_module.startswith("nonebot.adapters.feishu"):
            return int(event.event.message.create_time)
        if event_module.startswith("nonebot.adapters.telegram"):
            return int(event.date) * 1000
        if event_module.startswith("nonebot.adapters.qq"):
            value = event.timestamp
            if not isinstance(value, datetime):
                value = datetime.fromisoformat(
                    str(value).replace("Z", "+00:00")
                )
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return int(value.timestamp() * 1000)
    except (
        AttributeError,
        TypeError,
        ValueError,
        OverflowError,
        OSError,
    ) as error:
        raise EventTimestampError(
            "invalid platform message timestamp"
        ) from error
    raise EventTimestampError("unsupported event adapter")


__all__ = ("EventTimestampError", "event_timestamp_ms")
