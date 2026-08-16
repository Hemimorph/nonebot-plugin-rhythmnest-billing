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


class GuestCountResponse(ApiModel):
    count: int


class OperationRequest(ApiModel):
    note: str | None = None


class BillResponse(ApiModel):
    user_id: str
    active: bool
    entered_at_ms: int | None = None
    calculated_at_ms: int
    amount: int


class BalanceResponse(ApiModel):
    user_id: str
    balance: int


class BalanceChangeResponse(ApiModel):
    requested_at_ms: int
    operator_id: str
    type: str
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
    "ApiError",
    "BalanceAdjustmentRequest",
    "BalanceAdjustmentResponse",
    "BalanceChangeResponse",
    "BalanceChangesResponse",
    "BalanceResponse",
    "BillResponse",
    "DebtResponse",
    "DebtsResponse",
    "GuestCountResponse",
    "OperationRequest",
    "RatePeriodRequest",
    "RatePeriodResponse",
    "RatesResponse",
    "RatesUpdateRequest",
)
