"""Thin stripe-python adapter with explicit API-version and redacted errors.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 6.5.

Context7 verification for stripe-python 15.x showed:
- instantiate ``stripe.StripeClient(api_key, stripe_version=...)``;
- use the ``client.v1`` namespace for v1 resources in SDK >= 12.5.0;
- pass per-request options such as ``idempotency_key`` and ``stripe_version`` via
  the ``options`` mapping on service calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from src.Util.billing.redaction import redact_billing_sensitive_data, sanitize_billing_sensitive_text
from src.Util.error_handler import ErrorCode, StripeFlowError
from src.Util.stripe.config import SUPPORTED_STRIPE_API_VERSION


REDACTED_STRIPE_ERROR = "Stripe provider request failed"


class StripeClientConfigurationError(RuntimeError):
    """Raised when the Stripe client cannot be safely constructed."""


@dataclass(frozen=True)
class StripeAPIError(RuntimeError):
    """Redacted Stripe provider error."""

    message: str = REDACTED_STRIPE_ERROR
    status_code: int | None = None
    retry_after_seconds: int | None = None
    code: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        if self.retry_after_seconds is not None:
            parts.append(f"retry_after_seconds={self.retry_after_seconds}")
        if self.code:
            parts.append(f"code={sanitize_billing_sensitive_text(self.code)}")
        return "; ".join(parts)


def _stripe_module():
    import stripe  # type: ignore[import-not-found]

    return stripe


def _required_text(value: Any, *, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise StripeClientConfigurationError(f"{name} is required")
    return text


def _safe_metadata(**values: Any) -> dict[str, Any]:
    cleaned = {key: value for key, value in values.items() if value is not None}
    redacted = redact_billing_sensitive_data(cleaned)
    return redacted if isinstance(redacted, dict) else {}


def _to_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if hasattr(value, "to_dict_recursive") and callable(value.to_dict_recursive):
        mapped = value.to_dict_recursive()
        if isinstance(mapped, Mapping):
            return {str(key): item for key, item in mapped.items()}
    if hasattr(value, "to_dict") and callable(value.to_dict):
        mapped = value.to_dict()
        if isinstance(mapped, Mapping):
            return {str(key): item for key, item in mapped.items()}
    try:
        return dict(value)
    except Exception:
        return {}


def _retry_after_from_error(error: BaseException) -> int | None:
    headers = getattr(error, "headers", None)
    if isinstance(headers, Mapping):
        raw = headers.get("Retry-After") or headers.get("retry-after")
        try:
            return max(1, int(float(str(raw)))) if raw is not None else None
        except (TypeError, ValueError):
            return None
    return None


def _redacted_provider_error(error: BaseException, *, operation: str) -> StripeAPIError:
    status_code = getattr(error, "http_status", None) or getattr(error, "status_code", None)
    code = getattr(error, "code", None)
    return StripeAPIError(
        status_code=int(status_code) if status_code else None,
        retry_after_seconds=_retry_after_from_error(error),
        code=str(code) if code else None,
        metadata=_safe_metadata(operation=operation),
    )


class StripeBillingClient:
    """Small Stripe SDK seam for Checkout, Portal, and source-of-truth reads."""

    def __init__(
        self,
        *,
        secret_key: str,
        api_version: str = SUPPORTED_STRIPE_API_VERSION,
        stripe_client: Any | None = None,
        max_network_retries: int = 2,
    ) -> None:
        self._secret_key = _required_text(secret_key, name="Stripe secret key")
        self.api_version = _required_text(api_version, name="Stripe API version")
        self._stripe_client = stripe_client
        self.max_network_retries = max(0, int(max_network_retries))

    @classmethod
    def from_config(cls, config: Any, *, stripe_client: Any | None = None) -> "StripeBillingClient":
        return cls(
            secret_key=getattr(config, "secret_key", None),
            api_version=getattr(config, "api_version", SUPPORTED_STRIPE_API_VERSION),
            stripe_client=stripe_client,
        )

    def __repr__(self) -> str:  # never expose the secret key in logs/tracebacks
        return f"StripeBillingClient(api_version={self.api_version!r})"

    @property
    def sdk_client(self) -> Any:
        if self._stripe_client is None:
            stripe = _stripe_module()
            self._stripe_client = stripe.StripeClient(
                self._secret_key,
                stripe_version=self.api_version,
                max_network_retries=self.max_network_retries,
            )
        return self._stripe_client

    def _options(self, *, idempotency_key: str | None = None) -> dict[str, Any]:
        options: dict[str, Any] = {"stripe_version": self.api_version}
        if idempotency_key:
            options["idempotency_key"] = idempotency_key
        return options

    def _call(self, operation: str, func: Any, *args: Any, options: Mapping[str, Any] | None = None, **params: Any) -> dict[str, Any]:
        try:
            if options is not None:
                result = func(*args, params if params else None, options=dict(options)) if args else func(params if params else None, options=dict(options))
            else:
                result = func(*args, **params)
            return _to_mapping(result)
        except StripeAPIError:
            raise
        except Exception as exc:
            # Keep provider response bodies/details out of exception strings.
            _ = sanitize_billing_sensitive_text(str(exc))
            raise _redacted_provider_error(exc, operation=operation) from exc

    def create_customer(self, *, metadata: Mapping[str, Any] | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        params = {"metadata": dict(metadata or {})}
        return self._call(
            "customer_create",
            self.sdk_client.v1.customers.create,
            options=self._options(idempotency_key=idempotency_key),
            **params,
        )

    def retrieve_customer(self, customer_id: str) -> dict[str, Any]:
        return self._call("customer_retrieve", self.sdk_client.v1.customers.retrieve, _required_text(customer_id, name="Stripe customer id"), options=self._options())

    def create_checkout_session(self, *, params: Mapping[str, Any], idempotency_key: str) -> dict[str, Any]:
        return self._call(
            "checkout_session_create",
            self.sdk_client.v1.checkout.sessions.create,
            options=self._options(idempotency_key=idempotency_key),
            **dict(params),
        )

    def create_portal_session(self, *, params: Mapping[str, Any], idempotency_key: str) -> dict[str, Any]:
        return self._call(
            "portal_session_create",
            self.sdk_client.v1.billing_portal.sessions.create,
            options=self._options(idempotency_key=idempotency_key),
            **dict(params),
        )

    def retrieve_portal_configuration(self, configuration_id: str) -> dict[str, Any]:
        return self._call(
            "portal_configuration_retrieve",
            self.sdk_client.v1.billing_portal.configurations.retrieve,
            _required_text(configuration_id, name="Stripe portal configuration id"),
            options=self._options(),
        )

    def create_product(self, *, name: str, metadata: Mapping[str, Any] | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"name": _required_text(name, name="Stripe product name")}
        if metadata:
            params["metadata"] = dict(metadata)
        return self._call(
            "product_create",
            self.sdk_client.v1.products.create,
            options=self._options(idempotency_key=idempotency_key),
            **params,
        )

    def update_product(self, product_id: str, *, active: bool | None = None, name: str | None = None, metadata: Mapping[str, Any] | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if active is not None:
            params["active"] = bool(active)
        if name is not None:
            params["name"] = name
        if metadata is not None:
            params["metadata"] = dict(metadata)
        return self._call(
            "product_update",
            self.sdk_client.v1.products.update,
            _required_text(product_id, name="Stripe product id"),
            options=self._options(idempotency_key=idempotency_key),
            **params,
        )

    def create_price(
        self,
        *,
        product: str,
        currency: str,
        unit_amount: int,
        recurring: Mapping[str, Any] | None = None,
        lookup_key: str | None = None,
        transfer_lookup_key: bool | None = None,
        metadata: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "product": _required_text(product, name="Stripe product id"),
            "currency": _required_text(currency, name="Stripe price currency"),
            "unit_amount": int(unit_amount),
        }
        if recurring:
            params["recurring"] = dict(recurring)
        if lookup_key:
            params["lookup_key"] = lookup_key
        if transfer_lookup_key is not None:
            params["transfer_lookup_key"] = bool(transfer_lookup_key)
        if metadata:
            params["metadata"] = dict(metadata)
        return self._call(
            "price_create",
            self.sdk_client.v1.prices.create,
            options=self._options(idempotency_key=idempotency_key),
            **params,
        )

    def update_price(self, price_id: str, *, active: bool | None = None, lookup_key: str | None = None, metadata: Mapping[str, Any] | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if active is not None:
            params["active"] = bool(active)
        if lookup_key is not None:
            params["lookup_key"] = lookup_key
        if metadata is not None:
            params["metadata"] = dict(metadata)
        return self._call(
            "price_update",
            self.sdk_client.v1.prices.update,
            _required_text(price_id, name="Stripe price id"),
            options=self._options(idempotency_key=idempotency_key),
            **params,
        )

    def retrieve_price(self, price_id: str) -> dict[str, Any]:
        return self._call("price_retrieve", self.sdk_client.v1.prices.retrieve, _required_text(price_id, name="Stripe price id"), options=self._options())

    def list_prices_by_lookup_key(self, lookup_key: str) -> list[dict[str, Any]]:
        result = self._call(
            "price_lookup",
            self.sdk_client.v1.prices.list,
            options=self._options(),
            lookup_keys=[_required_text(lookup_key, name="Stripe price lookup key")],
            active=True,
            limit=1,
        )
        data = result.get("data")
        return [_to_mapping(item) for item in data] if isinstance(data, list) else []

    def _iter_all(
        self,
        operation: str,
        list_func: Any,
        *,
        params: Mapping[str, Any],
        max_items: int,
    ) -> list[dict[str, Any]]:
        """Page through a Stripe list endpoint via the SDK's native auto-pagination.

        Bounded by ``max_items`` (hard cap so a runaway account can't be enumerated without
        end). Errors are redacted exactly like ``_call``.
        """
        cap = max(1, int(max_items))
        try:
            result = list_func(dict(params) if params else None, options=self._options())
            items: list[dict[str, Any]] = []
            for obj in result.auto_paging_iter():
                items.append(_to_mapping(obj))
                if len(items) >= cap:
                    break
            return items
        except StripeAPIError:
            raise
        except Exception as exc:
            _ = sanitize_billing_sensitive_text(str(exc))
            raise _redacted_provider_error(exc, operation=operation) from exc

    def list_products(self, *, active: bool | None = True, limit: int = 100, max_items: int = 1000) -> list[dict[str, Any]]:
        """List the account's Stripe products (source-of-truth read for catalog reconcile)."""
        params: dict[str, Any] = {"limit": int(limit)}
        if active is not None:
            params["active"] = bool(active)
        return self._iter_all("product_list", self.sdk_client.v1.products.list, params=params, max_items=max_items)

    def list_prices(
        self,
        *,
        active: bool | None = True,
        limit: int = 100,
        expand_product: bool = False,
        max_items: int = 2000,
    ) -> list[dict[str, Any]]:
        """List the account's Stripe prices; ``expand_product`` inlines each price's product."""
        params: dict[str, Any] = {"limit": int(limit)}
        if active is not None:
            params["active"] = bool(active)
        if expand_product:
            params["expand"] = ["data.product"]
        return self._iter_all("price_list", self.sdk_client.v1.prices.list, params=params, max_items=max_items)

    def retrieve_subscription(self, subscription_id: str) -> dict[str, Any]:
        return self._call("subscription_retrieve", self.sdk_client.v1.subscriptions.retrieve, _required_text(subscription_id, name="Stripe subscription id"), options=self._options())

    def retrieve_payment_intent(self, payment_intent_id: str) -> dict[str, Any]:
        return self._call("payment_intent_retrieve", self.sdk_client.v1.payment_intents.retrieve, _required_text(payment_intent_id, name="Stripe payment intent id"), options=self._options())

    def retrieve_charge(self, charge_id: str) -> dict[str, Any]:
        return self._call("charge_retrieve", self.sdk_client.v1.charges.retrieve, _required_text(charge_id, name="Stripe charge id"), options=self._options())

    def retrieve_dispute(self, dispute_id: str) -> dict[str, Any]:
        return self._call("dispute_retrieve", self.sdk_client.v1.disputes.retrieve, _required_text(dispute_id, name="Stripe dispute id"), options=self._options())

    def retrieve_account(self) -> dict[str, Any]:
        """Auth probe: retrieve the account that owns this secret key.

        Cheapest "is this key valid?" call — a 401/403 surfaces as ``StripeAPIError(status_code=...)``
        via ``_call``. The returned mapping includes ``id`` and ``livemode``.
        """
        return self._call("account_retrieve", self.sdk_client.v1.accounts.retrieve_current, options=self._options())


def stripe_flow_error_from_api_error(error: StripeAPIError, *, fallback_code: ErrorCode = ErrorCode.STRIPE_CHECKOUT_UNAVAILABLE) -> StripeFlowError:
    return StripeFlowError(
        error_code=fallback_code,
        status_code=429 if error.retry_after_seconds else 503,
        details=_safe_metadata(retry_after_seconds=error.retry_after_seconds, provider_status=error.status_code),
        original_error=error,
    )


__all__ = [
    "REDACTED_STRIPE_ERROR",
    "StripeAPIError",
    "StripeBillingClient",
    "StripeClientConfigurationError",
    "stripe_flow_error_from_api_error",
]
