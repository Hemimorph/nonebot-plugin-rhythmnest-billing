from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        strict=True,
    )


class RatePeriodResponse(ApiModel):
    start: str
    end: str
    amount_per_half_hour: int
    max_amount: int


class RatesResponse(ApiModel):
    time_zone: str
    periods: list[RatePeriodResponse]


class ApiError(ApiModel):
    error: str


class ActiveGuestResponse(ApiModel):
    user_id: str
    entered_at_ms: int


class GuestCountResponse(ApiModel):
    count: int
    guests: list[ActiveGuestResponse]


class OperationRequest(ApiModel):
    note: str | None = None


class PeriodChargeResponse(ApiModel):
    started_at_ms: int
    ended_at_ms: int
    amount: int


class CheckoutResponse(ApiModel):
    user_id: str
    entered_at_ms: int
    exited_at_ms: int
    period_charges: list[PeriodChargeResponse]
    total_amount: int
    remaining_balance: int


class BillResponse(ApiModel):
    user_id: str
    entered_at_ms: int
    calculated_at_ms: int
    period_charges: list[PeriodChargeResponse]
    amount: int


class BalanceResponse(ApiModel):
    user_id: str
    balance: int


class BalanceChangeResponse(ApiModel):
    requested_at_ms: int
    operator_id: str
    type: Literal["LOGOUT", "ADMIN_ADJUST"]
    delta: int
    balance_after: int
    reason: str


class BalanceChangesResponse(ApiModel):
    user_id: str
    changes: list[BalanceChangeResponse]


class RatePeriodRequest(ApiModel):
    start: str
    end: str
    amount_per_half_hour: int
    max_amount: int


class RatesUpdateRequest(ApiModel):
    periods: list[RatePeriodRequest]
    note: str | None = None


class DebtResponse(ApiModel):
    user_id: str
    balance: int


class DebtsResponse(ApiModel):
    count: int
    balances: list[DebtResponse]


class BalanceAdjustmentRequest(ApiModel):
    delta: int
    reason: str


class BalanceAdjustmentResponse(ApiModel):
    requested_at_ms: int
    operator_id: str
    user_id: str
    delta: int
    balance_after: int
    reason: str


__all__ = (
    "ActiveGuestResponse",
    "ApiError",
    "BalanceAdjustmentRequest",
    "BalanceAdjustmentResponse",
    "BalanceChangeResponse",
    "BalanceChangesResponse",
    "BalanceResponse",
    "BillResponse",
    "CheckoutResponse",
    "DebtResponse",
    "DebtsResponse",
    "GuestCountResponse",
    "OperationRequest",
    "PeriodChargeResponse",
    "RatePeriodRequest",
    "RatePeriodResponse",
    "RatesResponse",
    "RatesUpdateRequest",
)
