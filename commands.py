from collections.abc import Awaitable
from datetime import datetime, timezone
from typing import TypeVar

from nonebot import get_driver, get_plugin_config
from nonebot.adapters import Event
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot_plugin_alconna import (
    Alconna,
    AlconnaMatcher,
    Args,
    At,
    CommandMeta,
    Extension,
    Match,
    MsgTarget,
    MultiVar,
    SupportScope,
    UniMessage,
    on_alconna,
)
from nonebot_plugin_alconna.extension import OutputType

from .client import BillingApiError, BillingClient, BillingError
from .config import Config
from .event_time import EventTimestampError, event_timestamp_ms
from .models import (
    BalanceChangeResponse,
    BillResponse,
    CheckoutResponse,
    PeriodChargeResponse,
    RatePeriodRequest,
)

__plugin_meta__ = PluginMetadata(
    name="nonebot-plugin-rhythmnest-billing",
    description="RhythmNest 进出店与账单管理",
    usage=(
        "/rates\n"
        "/setrates <开始HHMM> <结束HHMM> <半小时金额> <封顶> [...]\n"
        "/login [@用户]\n"
        "/logout [@用户]\n"
        "/count\n"
        "/bill [@用户]\n"
        "/balance [@用户]\n"
        "/lastchange [@用户] [条数]\n"
        "/debts\n"
        "/addadmin @用户\n"
        "/deladmin @用户\n"
        "/addbalance @用户 <整数金额> <理由>\n"
        "/subbalance @用户 <整数金额> <理由>"
    ),
    config=Config,
)

config = get_plugin_config(Config).rhythmnest
billing_client = BillingClient(config.api_url, config.api_token)


@get_driver().on_shutdown
async def close_billing_client() -> None:
    await billing_client.aclose()


class HelpOnErrorExtension(Extension):
    command: Alconna

    @property
    def priority(self) -> int:
        return 10

    @property
    def id(self) -> str:
        return "rhythmnest.help_on_error"

    def post_init(self, alc: Alconna) -> None:
        self.command = alc

    async def output_converter(
        self, output_type: OutputType, content: str
    ) -> UniMessage:
        if output_type == "error":
            content = f"{content}\n\n{self.command.get_help()}"
        return UniMessage.text(content)


ERROR_HELP_EXTENSIONS = [HelpOnErrorExtension]
T = TypeVar("T")


async def call_api(
    matcher: type[AlconnaMatcher],
    operation: Awaitable[T],
    payment_required_message: str | UniMessage = "余额为负",
    conflict_message: str | UniMessage | None = None,
) -> T:
    try:
        return await operation
    except BillingApiError as error:
        if error.status_code == 402:
            message = payment_required_message
        elif error.status_code == 409 and conflict_message is not None:
            message = conflict_message
        else:
            message = f"请求失败: {error}"
        await matcher.finish(message)
        raise
    except BillingError as error:
        await matcher.finish(f"请求失败: {error}")
        raise


async def mentioned_user_id(
    matcher: type[AlconnaMatcher], target: At
) -> str:
    if target.flag != "user":
        await matcher.finish("请指定用户")
    return target.target


async def resolve_user_id(
    matcher: type[AlconnaMatcher], target: Match[At], event: Event
) -> str:
    if not target.available:
        return event.get_user_id()
    return await mentioned_user_id(matcher, target.result)


async def platform_timestamp_ms(
    matcher: type[AlconnaMatcher], event: Event
) -> int:
    try:
        return event_timestamp_ms(event)
    except EventTimestampError:
        await matcher.finish("无法获取消息平台发送时间")
        raise


def parse_rate_periods(values: tuple[str, ...]) -> list[RatePeriodRequest]:
    normalized = " ".join(values)
    for separator in (";", "；", "|", ",", "，"):
        normalized = normalized.replace(separator, " ")
    parts = normalized.split()
    if not parts or len(parts) % 4:
        raise ValueError("invalid rate periods")
    periods = []
    for index in range(0, len(parts), 4):
        start_minutes = rate_input_minutes(parts[index])
        end_minutes = rate_input_minutes(parts[index + 1])
        periods.append(
            RatePeriodRequest(
                start=serialize_rate_time(start_minutes),
                end=serialize_rate_time(end_minutes),
                amount_per_half_hour=int(parts[index + 2]),
                max_amount=int(parts[index + 3]),
            )
        )
    return periods


def rate_input_minutes(value: str) -> int:
    if len(value) != 4 or not value.isdigit():
        raise ValueError("invalid rate input time")
    hour = int(value[:2])
    minute = int(value[2:])
    if minute >= 60:
        raise ValueError("invalid rate input time")
    return hour * 60 + minute


def rate_time_minutes(value: str) -> int:
    raw = value.strip()
    if ":" in raw:
        components = raw.split(":")
        if len(components) != 2 or not all(
            component.isdigit() for component in components
        ):
            raise ValueError("invalid rate time")
        hour, minute = map(int, components)
    else:
        if len(raw) < 3 or not raw.isdigit():
            raise ValueError("invalid rate time")
        hour = int(raw[:-2])
        minute = int(raw[-2:])
    if minute >= 60:
        raise ValueError("invalid rate time")
    return hour * 60 + minute


def serialize_rate_time(total_minutes: int) -> str:
    hour, minute = divmod(total_minutes, 60)
    return f"{hour:02d}{minute:02d}"


def format_rate_time(value: str) -> str:
    try:
        total_minutes = rate_time_minutes(value) % (24 * 60)
    except ValueError:
        return value
    hour, minute = divmod(total_minutes, 60)
    return f"{hour:02d}:{minute:02d}"


def format_change(change: BalanceChangeResponse) -> str:
    changed_at = datetime.fromtimestamp(
        change.requested_at_ms / 1000,
        timezone.utc,
    ).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    reason = {
        "LOGOUT": "离店结账",
        "ADMIN_ADJUST": "管理员调整",
    }[change.type]
    result = (
        f"{changed_at} | {change.delta:+d} | "
        f"余额 {change.balance_after} | 原因: {reason}"
    )
    note = change.reason.strip()
    if note:
        result += f" | 备注: {note}"
    return result


def format_entered_at(entered_at_ms: int) -> str:
    return datetime.fromtimestamp(
        entered_at_ms / 1000,
        timezone.utc,
    ).astimezone().strftime("%Y-%m-%d %H:%M")


def mention_users_message(
    message_target: MsgTarget,
    header: str,
    users: list[tuple[str, str]],
) -> UniMessage:
    if message_target.extra.get("scope") == SupportScope.qq_api:
        lines = [header] if header else []
        lines.extend(f"<@{user_id}>{text}" for user_id, text in users)
        return UniMessage.style("\n".join(lines), "markdown")
    message = UniMessage.text(header) if header else UniMessage()
    for user_id, text in users:
        if message:
            message.text("\n")
        message.at(user_id).text(text)
    return message


def format_charge_details(
    title: str,
    entered_at_ms: int,
    ended_at_label: str,
    ended_at_ms: int,
    period_charges: list[PeriodChargeResponse],
    total_amount: int,
    remaining_balance: int | None = None,
) -> str:
    lines = [
        f" {title}",
        f"进店时间: {format_entered_at(entered_at_ms)}",
        f"{ended_at_label}: {format_entered_at(ended_at_ms)}",
        "计费区段:",
    ]
    if period_charges:
        lines.extend(
            f"{index}. {format_entered_at(charge.started_at_ms)} - "
            f"{format_entered_at(charge.ended_at_ms)} | "
            f"费用: {charge.amount}"
            for index, charge in enumerate(period_charges, 1)
        )
    else:
        lines.append("无")
    lines.append(f"总费用: {total_amount}")
    if remaining_balance is not None:
        lines.append(f"结账后余额: {remaining_balance}")
    return "\n".join(lines)


def format_checkout(checkout: CheckoutResponse) -> str:
    return format_charge_details(
        "结账单",
        checkout.entered_at_ms,
        "离店时间",
        checkout.exited_at_ms,
        checkout.period_charges,
        checkout.total_amount,
        checkout.remaining_balance,
    )


def format_bill(bill: BillResponse) -> str:
    return format_charge_details(
        "当前账单",
        bill.entered_at_ms,
        "计算时间",
        bill.calculated_at_ms,
        bill.period_charges,
        bill.amount,
    )


nest_rates = on_alconna(
    Alconna("rates", meta=CommandMeta(description="查看当前费率")),
    aliases={"费率"},
    auto_send_output=True,
    extensions=ERROR_HELP_EXTENSIONS,
    skip_for_unmatch=False,
)


@nest_rates.handle()
async def handle_rates() -> None:
    response = await call_api(nest_rates, billing_client.get_rates())
    lines = [f"时区: {response.time_zone}"]
    lines.extend(
        f"{format_rate_time(period.start)}-"
        f"{format_rate_time(period.end)} | 每半小时 "
        f"{period.amount_per_half_hour} | 封顶 {period.max_amount}"
        for period in response.periods
    )
    await nest_rates.finish("\n".join(lines))


nest_setrates = on_alconna(
    Alconna(
        "setrates",
        Args["periods", MultiVar(str)],
        meta=CommandMeta(
            description="替换费率",
            usage=(
                "/setrates 0900 1800 5 50 "
                "[1800 3300 8 80 ...]"
            ),
        ),
    ),
    aliases={"设置费率"},
    auto_send_output=True,
    extensions=ERROR_HELP_EXTENSIONS,
    skip_for_unmatch=False,
    permission=SUPERUSER,
)


@nest_setrates.handle()
async def handle_setrates(
    event: Event, periods: tuple[str, ...]
) -> None:
    try:
        rate_periods = parse_rate_periods(periods)
    except ValueError:
        await nest_setrates.finish(
            "格式: /setrates <开始HHMM> <结束HHMM> "
            "<每半小时金额> <封顶金额> [...]"
        )
        raise
    await call_api(
        nest_setrates,
        billing_client.replace_rates(
            rate_periods,
            event.get_user_id(),
            await platform_timestamp_ms(nest_setrates, event),
        ),
    )
    await nest_setrates.finish("费率替换成功")


nest_login = on_alconna(
    Alconna(
        "login",
        Args["target?", At],
        meta=CommandMeta(description="进店", usage="/login [@用户]"),
    ),
    aliases={"进店", "li"},
    auto_send_output=True,
    extensions=ERROR_HELP_EXTENSIONS,
    skip_for_unmatch=False,
)


@nest_login.handle()
async def handle_login(
    event: Event,
    target: Match[At],
    message_target: MsgTarget,
) -> None:
    operator_id = event.get_user_id()
    user_id = await resolve_user_id(nest_login, target, event)
    await call_api(
        nest_login,
        billing_client.login_guest(
            user_id,
            operator_id,
            await platform_timestamp_ms(nest_login, event),
        ),
        mention_users_message(
            message_target,
            "",
            [(user_id, " 余额为负，入店失败")],
        ),
    )
    await nest_login.finish(
        mention_users_message(
            message_target,
            "",
            [(user_id, " 入店成功")],
        )
    )


nest_logout = on_alconna(
    Alconna(
        "logout",
        Args["target?", At],
        meta=CommandMeta(description="离店", usage="/logout [@用户]"),
    ),
    aliases={"离店", "lo"},
    auto_send_output=True,
    extensions=ERROR_HELP_EXTENSIONS,
    skip_for_unmatch=False,
)


@nest_logout.handle()
async def handle_logout(
    event: Event,
    target: Match[At],
    message_target: MsgTarget,
) -> None:
    operator_id = event.get_user_id()
    user_id = await resolve_user_id(nest_logout, target, event)
    checkout = await call_api(
        nest_logout,
        billing_client.logout_guest(
            user_id,
            operator_id,
            await platform_timestamp_ms(nest_logout, event),
        ),
        conflict_message=mention_users_message(
            message_target,
            "",
            [(user_id, " 当前不在店")],
        ),
    )
    await nest_logout.finish(
        mention_users_message(
            message_target,
            "",
            [(user_id, format_checkout(checkout))],
        )
    )


nest_count = on_alconna(
    Alconna("count", meta=CommandMeta(description="查看当前店内人数")),
    aliases={"几人", "j"},
    auto_send_output=True,
    extensions=ERROR_HELP_EXTENSIONS,
    skip_for_unmatch=False,
)


@nest_count.handle()
async def handle_count(message_target: MsgTarget) -> None:
    response = await call_api(nest_count, billing_client.count_active_guests())
    if not response.guests:
        await nest_count.finish(f"当前店内人数为: {response.count}")
    if message_target.extra.get("scope") == SupportScope.qq_api:
        lines = [f"当前店内人数为: {response.count}"]
        lines.extend(
            f"<@{guest.user_id}> | "
            f"进店时间: {format_entered_at(guest.entered_at_ms)}"
            for guest in response.guests
        )
        await nest_count.finish(
            UniMessage.style("\n".join(lines), "markdown")
        )
    lines = [f"当前店内人数为: {response.count}"]
    lines.extend(
        f"OpenID: {guest.user_id} | "
        f"进店时间: {format_entered_at(guest.entered_at_ms)}"
        for guest in response.guests
    )
    await nest_count.finish("\n".join(lines))


nest_bill = on_alconna(
    Alconna(
        "bill",
        Args["target?", At],
        meta=CommandMeta(description="查看当前账单", usage="/bill [@用户]"),
    ),
    aliases={"账单"},
    auto_send_output=True,
    extensions=ERROR_HELP_EXTENSIONS,
    skip_for_unmatch=False,
)


@nest_bill.handle()
async def handle_bill(
    event: Event,
    target: Match[At],
    message_target: MsgTarget,
) -> None:
    operator_id = event.get_user_id()
    user_id = await resolve_user_id(nest_bill, target, event)
    response = await call_api(
        nest_bill,
        billing_client.get_bill(
            user_id,
            operator_id,
            await platform_timestamp_ms(nest_bill, event),
        ),
    )
    await nest_bill.finish(
        mention_users_message(
            message_target,
            "",
            [
                (
                    user_id,
                    format_bill(response)
                    if response is not None
                    else " 当前不在店",
                )
            ],
        )
    )


nest_balance = on_alconna(
    Alconna(
        "balance",
        Args["target?", At],
        meta=CommandMeta(description="查看当前余额", usage="/balance [@用户]"),
    ),
    aliases={"余额"},
    auto_send_output=True,
    extensions=ERROR_HELP_EXTENSIONS,
    skip_for_unmatch=False,
)


@nest_balance.handle()
async def handle_balance(
    event: Event,
    target: Match[At],
    message_target: MsgTarget,
) -> None:
    operator_id = event.get_user_id()
    user_id = await resolve_user_id(nest_balance, target, event)
    response = await call_api(
        nest_balance,
        billing_client.get_balance(
            user_id,
            operator_id,
            await platform_timestamp_ms(nest_balance, event),
        ),
    )
    await nest_balance.finish(
        mention_users_message(
            message_target,
            "",
            [(user_id, f" 当前余额为: {response.balance}")],
        )
    )


nest_last = on_alconna(
    Alconna(
        "lastchange",
        Args["target?", At]["limit?", int],
        meta=CommandMeta(
            description="查看最近余额变动",
            usage="/lastchange [@用户] [条数]",
        ),
    ),
    aliases={"最近变动"},
    auto_send_output=True,
    extensions=ERROR_HELP_EXTENSIONS,
    skip_for_unmatch=False,
)


@nest_last.handle()
async def handle_last(
    event: Event,
    target: Match[At],
    limit: Match[int],
    message_target: MsgTarget,
) -> None:
    operator_id = event.get_user_id()
    user_id = await resolve_user_id(nest_last, target, event)
    response = await call_api(
        nest_last,
        billing_client.get_balance_changes(
            user_id,
            operator_id,
            await platform_timestamp_ms(nest_last, event),
            limit.result if limit.available else None,
        ),
    )
    if not response.changes:
        await nest_last.finish(
            mention_users_message(
                message_target,
                "",
                [(user_id, " 最近没有余额变动")],
            )
        )
    lines = "\n".join(format_change(change) for change in response.changes)
    await nest_last.finish(
        mention_users_message(
            message_target,
            "",
            [(user_id, f" 最近余额变动:\n{lines}")],
        )
    )


nest_debts = on_alconna(
    Alconna("debts", meta=CommandMeta(description="查看欠款列表")),
    aliases={"欠款列表"},
    auto_send_output=True,
    extensions=ERROR_HELP_EXTENSIONS,
    skip_for_unmatch=False,
    permission=SUPERUSER,
)


@nest_debts.handle()
async def handle_debts(
    event: Event, message_target: MsgTarget
) -> None:
    response = await call_api(
        nest_debts,
        billing_client.get_debts(
            event.get_user_id(),
            await platform_timestamp_ms(nest_debts, event),
        ),
    )
    if not response.balances:
        await nest_debts.finish("当前没有欠款")
    await nest_debts.finish(
        mention_users_message(
            message_target,
            f"欠款人数: {response.count}",
            [
                (balance.user_id, f" | 余额: {balance.balance}")
                for balance in response.balances
            ],
        )
    )


nest_addadmin = on_alconna(
    Alconna(
        "addadmin",
        Args["target", At],
        meta=CommandMeta(description="添加管理员", usage="/addadmin @用户"),
    ),
    aliases={"添加管理员"},
    auto_send_output=True,
    extensions=ERROR_HELP_EXTENSIONS,
    skip_for_unmatch=False,
    permission=SUPERUSER,
)


@nest_addadmin.handle()
async def handle_addadmin(event: Event, target: At) -> None:
    user_id = await mentioned_user_id(nest_addadmin, target)
    await call_api(
        nest_addadmin,
        billing_client.add_administrator(
            user_id,
            event.get_user_id(),
            await platform_timestamp_ms(nest_addadmin, event),
        ),
    )
    await nest_addadmin.finish("添加管理员成功")


nest_deladmin = on_alconna(
    Alconna(
        "deladmin",
        Args["target", At],
        meta=CommandMeta(description="删除管理员", usage="/deladmin @用户"),
    ),
    aliases={"删除管理员"},
    auto_send_output=True,
    extensions=ERROR_HELP_EXTENSIONS,
    skip_for_unmatch=False,
    permission=SUPERUSER,
)


@nest_deladmin.handle()
async def handle_deladmin(event: Event, target: At) -> None:
    user_id = await mentioned_user_id(nest_deladmin, target)
    await call_api(
        nest_deladmin,
        billing_client.delete_administrator(
            user_id,
            event.get_user_id(),
            await platform_timestamp_ms(nest_deladmin, event),
        ),
    )
    await nest_deladmin.finish("删除管理员成功")


nest_addbalance = on_alconna(
    Alconna(
        "addbalance",
        Args["target", At]["amount", int]["reason", MultiVar(str)],
        meta=CommandMeta(
            description="增加余额",
            usage="/addbalance @用户 <整数金额> <理由>",
        ),
    ),
    aliases={"增加余额"},
    auto_send_output=True,
    extensions=ERROR_HELP_EXTENSIONS,
    skip_for_unmatch=False,
    permission=SUPERUSER,
)


@nest_addbalance.handle()
async def handle_addbalance(
    event: Event,
    target: At,
    amount: int,
    reason: tuple[str, ...],
    message_target: MsgTarget,
) -> None:
    if amount <= 0:
        await nest_addbalance.finish("金额必须为正整数")
    user_id = await mentioned_user_id(nest_addbalance, target)
    await call_api(
        nest_addbalance,
        billing_client.adjust_balance(
            user_id,
            event.get_user_id(),
            amount,
            " ".join(reason),
            await platform_timestamp_ms(nest_addbalance, event),
        ),
    )
    await nest_addbalance.finish(
        mention_users_message(
            message_target,
            "",
            [(user_id, " 增加余额成功")],
        )
    )


nest_subbalance = on_alconna(
    Alconna(
        "subbalance",
        Args["target", At]["amount", int]["reason", MultiVar(str)],
        meta=CommandMeta(
            description="减少余额",
            usage="/subbalance @用户 <整数金额> <理由>",
        ),
    ),
    aliases={"减少余额"},
    auto_send_output=True,
    extensions=ERROR_HELP_EXTENSIONS,
    skip_for_unmatch=False,
    permission=SUPERUSER,
)


@nest_subbalance.handle()
async def handle_subbalance(
    event: Event,
    target: At,
    amount: int,
    reason: tuple[str, ...],
    message_target: MsgTarget,
) -> None:
    if amount <= 0:
        await nest_subbalance.finish("金额必须为正整数")
    user_id = await mentioned_user_id(nest_subbalance, target)
    await call_api(
        nest_subbalance,
        billing_client.adjust_balance(
            user_id,
            event.get_user_id(),
            -amount,
            " ".join(reason),
            await platform_timestamp_ms(nest_subbalance, event),
        ),
    )
    await nest_subbalance.finish(
        mention_users_message(
            message_target,
            "",
            [(user_id, " 减少余额成功")],
        )
    )
