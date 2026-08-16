from types import TracebackType
from typing import Any, TypeVar
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ValidationError

from .models import (
    ApiError,
    BalanceAdjustmentRequest,
    BalanceAdjustmentResponse,
    BalanceChangesResponse,
    BalanceResponse,
    BillResponse,
    CheckoutResponse,
    DebtsResponse,
    GuestCountResponse,
    OperationRequest,
    RatePeriodRequest,
    RatesResponse,
    RatesUpdateRequest,
)


ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class BillingError(Exception):
    pass


class BillingApiError(BillingError):
    def __init__(
        self,
        status_code: int,
        error: str,
        response: httpx.Response,
    ) -> None:
        self.status_code = status_code
        self.error = error
        self.response = response
        super().__init__(f"{status_code}: {error}")


class BillingTransportError(BillingError):
    pass


class BillingResponseError(BillingError):
    pass


class BillingClient:
    def __init__(
        self,
        api_url: str,
        api_token: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        normalized_url = api_url.strip().rstrip("/")
        if not normalized_url:
            raise ValueError("api_url must not be empty")
        self._api_url = normalized_url
        self._api_token = api_token
        self._owns_http_client = http_client is None
        self._http_client = (
            http_client
            if http_client is not None
            else httpx.AsyncClient(timeout=timeout)
        )

    async def __aenter__(self) -> "BillingClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()

    def _url(self, path: str) -> str:
        return f"{self._api_url}/{path.lstrip('/')}"

    def _headers(
        self,
        authenticated: bool,
        operator_id: str | None = None,
        request_timestamp: int | None = None,
    ) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if authenticated:
            if not self._api_token:
                raise BillingError(
                    "api_token is required for this operation"
                )
            headers["Authorization"] = f"Bearer {self._api_token}"
        if operator_id is not None:
            headers["X-Operator-Id"] = operator_id
        if request_timestamp is not None:
            headers["X-Request-Timestamp"] = str(request_timestamp)
        return headers

    def _api_error(self, response: httpx.Response) -> BillingApiError:
        try:
            error = ApiError.model_validate(response.json()).error
        except (ValueError, TypeError, ValidationError):
            error = response.text.strip() or response.reason_phrase
        if not error:
            error = "Billing API request failed"
        return BillingApiError(response.status_code, error, response)

    async def _request(
        self,
        method: str,
        path: str,
        expected_status: int | tuple[int, ...],
        authenticated: bool,
        operator_id: str | None = None,
        request_timestamp: int | None = None,
        json: Any = None,
        params: dict[str, int] | None = None,
    ) -> httpx.Response:
        try:
            response = await self._http_client.request(
                method,
                self._url(path),
                headers=self._headers(
                    authenticated,
                    operator_id,
                    request_timestamp,
                ),
                json=json,
                params=params,
            )
        except httpx.HTTPError as exc:
            raise BillingTransportError(str(exc)) from exc
        expected_statuses = (
            (expected_status,)
            if isinstance(expected_status, int)
            else expected_status
        )
        if response.status_code not in expected_statuses:
            raise self._api_error(response)
        return response

    def _response_model(
        self,
        response: httpx.Response,
        model: type[ResponseModel],
    ) -> ResponseModel:
        try:
            payload = response.json()
        except ValueError as exc:
            raise BillingResponseError(
                f"Billing API returned invalid JSON for {model.__name__}"
            ) from exc
        try:
            return model.model_validate(
                payload,
                by_alias=True,
                by_name=False,
            )
        except ValidationError as exc:
            raise BillingResponseError(
                f"Billing API returned invalid {model.__name__}"
            ) from exc

    async def get_rates(self) -> RatesResponse:
        response = await self._request(
            "GET",
            "admin/rates",
            200,
            authenticated=False,
        )
        return self._response_model(response, RatesResponse)

    async def replace_rates(
        self,
        periods: list[RatePeriodRequest],
        operator_id: str,
        request_timestamp: int,
        note: str | None = None,
    ) -> None:
        request = RatesUpdateRequest(periods=periods, note=note)
        await self._request(
            "PUT",
            "admin/rates",
            204,
            authenticated=True,
            operator_id=operator_id,
            request_timestamp=request_timestamp,
            json=request.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            ),
        )

    async def count_active_guests(self) -> GuestCountResponse:
        response = await self._request(
            "GET",
            "guest/count",
            200,
            authenticated=True,
        )
        return self._response_model(response, GuestCountResponse)

    async def login_guest(
        self,
        user_id: str,
        operator_id: str,
        request_timestamp: int,
        note: str | None = None,
    ) -> None:
        request = OperationRequest(note=note)
        encoded_user_id = quote(user_id, safe="")
        await self._request(
            "PUT",
            f"guest/{encoded_user_id}/login",
            204,
            authenticated=True,
            operator_id=operator_id,
            request_timestamp=request_timestamp,
            json=request.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            ),
        )

    async def logout_guest(
        self,
        user_id: str,
        operator_id: str,
        request_timestamp: int,
        note: str | None = None,
    ) -> CheckoutResponse:
        request = OperationRequest(note=note)
        encoded_user_id = quote(user_id, safe="")
        response = await self._request(
            "PUT",
            f"guest/{encoded_user_id}/logout",
            200,
            authenticated=True,
            operator_id=operator_id,
            request_timestamp=request_timestamp,
            json=request.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            ),
        )
        return self._response_model(response, CheckoutResponse)

    async def get_bill(
        self,
        user_id: str,
        operator_id: str,
        request_timestamp: int,
    ) -> BillResponse | None:
        encoded_user_id = quote(user_id, safe="")
        response = await self._request(
            "GET",
            f"guest/{encoded_user_id}/bill",
            (200, 204),
            authenticated=True,
            operator_id=operator_id,
            request_timestamp=request_timestamp,
        )
        if response.status_code == 204:
            return None
        return self._response_model(response, BillResponse)

    async def get_balance(
        self,
        user_id: str,
        operator_id: str,
        request_timestamp: int,
    ) -> BalanceResponse:
        encoded_user_id = quote(user_id, safe="")
        response = await self._request(
            "GET",
            f"guest/{encoded_user_id}/balance",
            200,
            authenticated=True,
            operator_id=operator_id,
            request_timestamp=request_timestamp,
        )
        return self._response_model(response, BalanceResponse)

    async def get_balance_changes(
        self,
        user_id: str,
        operator_id: str,
        request_timestamp: int,
        limit: int | None = None,
    ) -> BalanceChangesResponse:
        encoded_user_id = quote(user_id, safe="")
        params = None if limit is None else {"limit": limit}
        response = await self._request(
            "GET",
            f"guest/{encoded_user_id}/changes",
            200,
            authenticated=True,
            operator_id=operator_id,
            request_timestamp=request_timestamp,
            params=params,
        )
        return self._response_model(response, BalanceChangesResponse)

    async def get_debts(
        self,
        operator_id: str,
        request_timestamp: int,
    ) -> DebtsResponse:
        response = await self._request(
            "GET",
            "admin/debts",
            200,
            authenticated=True,
            operator_id=operator_id,
            request_timestamp=request_timestamp,
        )
        return self._response_model(response, DebtsResponse)

    async def add_administrator(
        self,
        user_id: str,
        operator_id: str,
        request_timestamp: int,
        note: str | None = None,
    ) -> None:
        request = OperationRequest(note=note)
        encoded_user_id = quote(user_id, safe="")
        await self._request(
            "PUT",
            f"admin/{encoded_user_id}",
            204,
            authenticated=True,
            operator_id=operator_id,
            request_timestamp=request_timestamp,
            json=request.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            ),
        )

    async def delete_administrator(
        self,
        user_id: str,
        operator_id: str,
        request_timestamp: int,
        note: str | None = None,
    ) -> None:
        request = OperationRequest(note=note)
        encoded_user_id = quote(user_id, safe="")
        await self._request(
            "DELETE",
            f"admin/{encoded_user_id}",
            204,
            authenticated=True,
            operator_id=operator_id,
            request_timestamp=request_timestamp,
            json=request.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            ),
        )

    async def adjust_balance(
        self,
        user_id: str,
        operator_id: str,
        delta: int,
        reason: str,
        request_timestamp: int,
    ) -> BalanceAdjustmentResponse:
        request = BalanceAdjustmentRequest(delta=delta, reason=reason)
        encoded_user_id = quote(user_id, safe="")
        response = await self._request(
            "POST",
            f"admin/{encoded_user_id}/balance",
            201,
            authenticated=True,
            operator_id=operator_id,
            request_timestamp=request_timestamp,
            json=request.model_dump(mode="json", by_alias=True),
        )
        return self._response_model(response, BalanceAdjustmentResponse)


__all__ = (
    "BillingApiError",
    "BillingClient",
    "BillingError",
    "BillingResponseError",
    "BillingTransportError",
)
