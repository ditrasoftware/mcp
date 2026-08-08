from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.context import Context

from ..rest_client import FerreroMedAuth, FerreroMedRestClient
from ..settings import FerreroMedSettings


def register_local_tools(
    mcp: FastMCP,
    client: FerreroMedRestClient,
    settings: FerreroMedSettings,
    *,
    _ctx_or_current: Callable[[Context | None], Context | None],
    _header_auth: Callable[[Context | None], FerreroMedAuth],
    _auth_from_args: Callable[..., FerreroMedAuth],
    _require_auth: Callable[[FerreroMedAuth], None],
    _apply_default_auth: Callable[..., FerreroMedAuth],
    _coerce_positive_int: Callable[[int | str | None], int | None],
) -> set[str]:
    @mcp.tool()
    async def auth_debug(ctx: Context | None = None) -> dict[str, Any]:
        """Return a non-sensitive view of inbound auth.

        This tool is intentionally safe to run without credentials. It helps
        diagnose whether an MCP client is actually sending auth headers.

        Returns booleans and the Authorization scheme only (never the token/key).
        """
        ctx2 = _ctx_or_current(ctx)
        if ctx2 is None or ctx2.request_context is None or ctx2.request_context.request is None:
            return {
                "has_request": False,
                "has_authorization": False,
                "authorization_scheme": None,
                "has_x_api_key": False,
                "has_x_refresh_token": False,
                "user_agent": None,
                "origin": None,
                "referer": None,
                "host": None,
                "x_forwarded_for": None,
                "x_forwarded_proto": None,
                "accept": None,
            }

        headers = ctx2.request_context.request.headers
        authorization = headers.get("authorization")
        has_authorization = bool(authorization and authorization.strip())
        scheme: str | None = None
        if has_authorization:
            scheme = authorization.strip().split(" ", 1)[0].lower()

        x_api_key = headers.get("x-api-key")
        x_refresh = headers.get("x-refresh-token")

        # Useful for identifying which host/client is calling us.
        user_agent = headers.get("user-agent")
        origin = headers.get("origin")
        referer = headers.get("referer")
        host = headers.get("host")
        x_forwarded_for = headers.get("x-forwarded-for")
        x_forwarded_proto = headers.get("x-forwarded-proto")
        accept = headers.get("accept")

        return {
            "has_request": True,
            "has_authorization": has_authorization,
            "authorization_scheme": scheme,
            "has_x_api_key": bool(x_api_key and x_api_key.strip()),
            "has_x_refresh_token": bool(x_refresh and x_refresh.strip()),
            "user_agent": user_agent,
            "origin": origin,
            "referer": referer,
            "host": host,
            "x_forwarded_for": x_forwarded_for,
            "x_forwarded_proto": x_forwarded_proto,
            "accept": accept,
        }

    @mcp.tool()
    async def auth_login(
        email: str | None = None,
        password: str | None = None,
        provider: str | None = None,
    ) -> Any:
        """Login via FerreroMed REST API.

        - For email/password: provide both `email` and `password`.
        - For OAuth: provide `provider` (e.g. "google") to get an auth URL.
        """
        return await client.request(
            "POST",
            "/auth/login",
            json={"email": email, "password": password, "provider": provider},
            auth=None,
        )

    @mcp.tool()
    async def auth_refresh(
        refresh_token: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Refresh access token using a refresh token.

        Reads refresh token from argument or from `X-Refresh-Token` header.
        """
        header_auth = _header_auth(ctx)
        arg_auth = _auth_from_args(refresh_token=refresh_token)
        effective = header_auth.merged(arg_auth)

        if not effective.refresh_token:
            raise ValueError("Missing refresh token (arg refresh_token or X-Refresh-Token header)")

        # REST endpoint supports cookie/header/body; we use body for clarity.
        return await client.request(
            "POST",
            "/auth/refresh",
            json={"refresh_token": effective.refresh_token},
            auth=None,
            extra_headers={"x-refresh-token": effective.refresh_token},
        )

    # -----------------
    # Patients
    # -----------------

    @mcp.tool()
    async def patients_list(
        tax_id: str | None = None,
        full_name: str | None = None,
        name: str | None = None,
        surname: str | None = None,
        city: str | None = None,
        zip_code: str | None = None,
        province: str | None = None,
        birth_day: str | None = None,
        page_number: int | str | None = None,
        page_size: int | str | None = None,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Search/list patients."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)

        return await client.request(
            "GET",
            "/patients",
            params={
                "tax_id": tax_id,
                "full_name": full_name,
                "name": name,
                "surname": surname,
                "city": city,
                "zip_code": zip_code,
                "province": province,
                "birth_day": birth_day,
                "page_number": _coerce_positive_int(page_number),
                "page_size": _coerce_positive_int(page_size),
            },
            auth=effective,
        )

    @mcp.tool()
    async def patients_get(
        patient_id: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Get a patient by id."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("GET", f"/patients/{patient_id}", auth=effective)

    @mcp.tool()
    async def patients_create(
        payload: dict[str, Any],
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Create a patient. Payload is passed to REST as-is."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("POST", "/patients", json=payload, auth=effective)

    @mcp.tool()
    async def patients_update(
        patient_id: str,
        payload: dict[str, Any],
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Update a patient by id. Payload is passed to REST as-is."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("PUT", f"/patients/{patient_id}", json=payload, auth=effective)

    @mcp.tool()
    async def patients_delete(
        patient_id: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Delete a patient by id."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request(
            "DELETE",
            f"/patients/{patient_id}",
            auth=effective,
            expect_json=False,
        )

    # -----------------
    # Orders
    # -----------------

    @mcp.tool()
    async def orders_list(
        unique_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        item_description: str | None = None,
        order_type: str | None = None,
        asl_code: str | None = None,
        district_id: int | None = None,
        patient_id: str | None = None,
        patient_full_name: str | None = None,
        tax_id: str | None = None,
        trip_id: str | None = None,
        auth_code: str | None = None,
        open: str | None = None,
        purchase: str | None = None,
        address: str | None = None,
        city: str | None = None,
        zip_code: str | None = None,
        province: str | None = None,
        page_number: int | None = None,
        page_size: int | None = None,
        from_page: int | None = None,
        to_page: int | None = None,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Search/list orders."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)

        return await client.request(
            "GET",
            "/orders",
            params={
                "unique_id": unique_id,
                "from_date": from_date,
                "to_date": to_date,
                "item_description": item_description,
                "order_type": order_type,
                "asl_code": asl_code,
                "district_id": district_id,
                "patient_id": patient_id,
                "patient_full_name": patient_full_name,
                "tax_id": tax_id,
                "trip_id": trip_id,
                "auth_code": auth_code,
                "open": open,
                "purchase": purchase,
                "address": address,
                "city": city,
                "zip_code": zip_code,
                "province": province,
                "page_number": page_number,
                "page_size": page_size,
                "from_page": from_page,
                "to_page": to_page,
            },
            auth=effective,
        )

    @mcp.tool()
    async def orders_get(
        order_id: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Get an order by id."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("GET", f"/orders/{order_id}", auth=effective)

    @mcp.tool()
    async def orders_create(
        payload: dict[str, Any],
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Create an order. Payload is passed to REST as-is."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("POST", "/orders", json=payload, auth=effective)

    @mcp.tool()
    async def orders_update(
        order_id: str,
        payload: dict[str, Any],
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Update an order by id. Payload is passed to REST as-is."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("PUT", f"/orders/{order_id}", json=payload, auth=effective)

    @mcp.tool()
    async def orders_delete(
        order_id: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Delete an order by id."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("DELETE", f"/orders/{order_id}", auth=effective, expect_json=False)

    # -----------------
    # Quotations
    # -----------------

    @mcp.tool()
    async def quotations_list(
        asl_code: str | None = None,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """List quotations (optionally filtered by ASL code)."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("GET", "/quotations", params={"asl_code": asl_code}, auth=effective)

    @mcp.tool()
    async def quotations_get(
        quotation_id: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Get a quotation by id."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("GET", f"/quotations/{quotation_id}", auth=effective)

    @mcp.tool()
    async def quotations_accept(
        quotation_id: str,
        user_upd: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Accept a quotation."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request(
            "POST",
            f"/quotations/{quotation_id}/accept",
            json={"user_upd": user_upd},
            auth=effective,
        )

    @mcp.tool()
    async def quotations_reject(
        quotation_id: str,
        user_upd: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Reject a quotation."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request(
            "POST",
            f"/quotations/{quotation_id}/reject",
            json={"user_upd": user_upd},
            auth=effective,
        )

    @mcp.tool()
    async def quotations_status_counts(
        asl_code: str | None = None,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> list[dict[str, int | str]]:
        """Return quotation counts grouped by quote_status (for charts)."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)

        rows = await client.request(
            "GET",
            "/quotations",
            params={"asl_code": asl_code},
            auth=effective,
        )

        counts: dict[str, int] = {}
        if isinstance(rows, list):
            for r in rows:
                if not isinstance(r, dict):
                    continue
                status = str(r.get("quote_status") or "Unknown")
                counts[status] = counts.get(status, 0) + 1

        return [{"status": k, "count": v} for k, v in sorted(counts.items())]

    # -----------------
    # Trips (exclude trips_cv)
    # -----------------

    @mcp.tool()
    async def trips_list(
        business_entity: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        asl_code: str | None = None,
        district_id: int | None = None,
        patient_id: str | None = None,
        order_id: str | None = None,
        address: str | None = None,
        city: str | None = None,
        zip_code: str | None = None,
        province: str | None = None,
        page_number: int | str | None = None,
        page_size: int | str | None = None,
        from_page: int | str | None = None,
        to_page: int | str | None = None,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Search/list trips."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)

        return await client.request(
            "GET",
            "/trips",
            params={
                "business_entity": business_entity,
                "from_date": from_date,
                "to_date": to_date,
                "asl_code": asl_code,
                "district_id": district_id,
                "patient_id": patient_id,
                "order_id": order_id,
                "address": address,
                "city": city,
                "zip_code": zip_code,
                "province": province,
                "page_number": _coerce_positive_int(page_number),
                "page_size": _coerce_positive_int(page_size),
                "from_page": _coerce_positive_int(from_page),
                "to_page": _coerce_positive_int(to_page),
            },
            auth=effective,
        )

    @mcp.tool()
    async def trips_get(
        trip_id: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Get a trip by id."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("GET", f"/trips/{trip_id}", auth=effective)

    @mcp.tool()
    async def trips_create(
        payload: dict[str, Any],
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Create a trip. Payload is passed to REST as-is."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("POST", "/trips", json=payload, auth=effective)

    @mcp.tool()
    async def trips_update(
        trip_id: str,
        payload: dict[str, Any],
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Update a trip by id. Payload is passed to REST as-is."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("PUT", f"/trips/{trip_id}", json=payload, auth=effective)

    @mcp.tool()
    async def trips_delete(
        trip_id: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Delete a trip by id."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("DELETE", f"/trips/{trip_id}", auth=effective)

    @mcp.tool()
    async def trips_status_counts(
        business_entity: str | None = None,
        asl_code: str | None = None,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> list[dict[str, int | str]]:
        """Return trip counts grouped by trip_status (for charts)."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)

        rows = await client.request(
            "GET",
            "/trips",
            params={
                "business_entity": business_entity,
                "asl_code": asl_code,
                "page_size": 250,
            },
            auth=effective,
        )

        counts: dict[str, int] = {}
        if isinstance(rows, list):
            for r in rows:
                if not isinstance(r, dict):
                    continue
                status = str(r.get("trip_status") or "Unknown")
                counts[status] = counts.get(status, 0) + 1

        return [{"status": k, "count": v} for k, v in sorted(counts.items())]

    # -----------------
    # Lookups (read-only)
    # -----------------

    @mcp.tool()
    async def asls_list(
        asl_code: str | None = None,
        business_entity: str | None = None,
        max_rows: int | str | None = None,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """List ASLs (read-only)."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        rows = await client.request(
            "GET",
            "/asls",
            params={"asl_code": asl_code, "business_entity": business_entity},
            auth=effective,
        )

        max_n = _coerce_positive_int(max_rows)
        if max_n is not None and isinstance(rows, list):
            return rows[:max_n]
        return rows

    @mcp.tool()
    async def asls_list_text(
        asl_code: str | None = None,
        business_entity: str | None = None,
        max_rows: int | str | None = None,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> str:
        """List ASLs but return as a JSON string (copy/paste friendly)."""
        rows = await asls_list(
            asl_code=asl_code,
            business_entity=business_entity,
            max_rows=max_rows,
            access_token=access_token,
            api_key=api_key,
            ctx=ctx,
        )
        try:
            import json

            return json.dumps(rows, indent=2, ensure_ascii=False)
        except TypeError:
            return str(rows)

    @mcp.tool()
    async def asls_business_counts(
        asl_code: str | None = None,
        business_entity: str | None = None,
        max_rows: int | str | None = None,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> list[dict[str, int | str]]:
        """Count ASLs grouped by business_entity (for charts)."""
        rows = await asls_list(
            asl_code=asl_code,
            business_entity=business_entity,
            max_rows=max_rows,
            access_token=access_token,
            api_key=api_key,
            ctx=ctx,
        )

        counts: dict[str, int] = {}
        if isinstance(rows, list):
            for r in rows:
                if not isinstance(r, dict):
                    continue
                key = str(r.get("business_entity") or "Unknown")
                counts[key] = counts.get(key, 0) + 1

        return [
            {"business_entity": k, "count": v}
            for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]

    @mcp.tool()
    async def products_list(
        unique_id: str | None = None,
        item_description: str | None = None,
        supplier_product_id: str | None = None,
        supplier_id: int | None = None,
        supplier_name: str | None = None,
        family_id: int | None = None,
        family_name: str | None = None,
        brand_id: int | None = None,
        brand_name: str | None = None,
        model_id: str | None = None,
        model_name: str | None = None,
        page_number: int | str | None = 1,
        page_size: int | str | None = 100,
        sort_by: str | None = "product_id",
        sort_direction: str | None = "ASC",
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """List products (read-only)."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request(
            "GET",
            "/products",
            params={
                "unique_id": unique_id,
                "item_description": item_description,
                "supplier_product_id": supplier_product_id,
                "supplier_id": supplier_id,
                "supplier_name": supplier_name,
                "family_id": family_id,
                "family_name": family_name,
                "brand_id": brand_id,
                "brand_name": brand_name,
                "model_id": model_id,
                "model_name": model_name,
                "page_number": _coerce_positive_int(page_number) or 1,
                "page_size": _coerce_positive_int(page_size) or 100,
                "sort_by": sort_by,
                "sort_direction": sort_direction,
            },
            auth=effective,
        )

    @mcp.tool()
    async def products_get(
        product_id: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Get a product by id (read-only)."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("GET", f"/products/{product_id}", auth=effective)

    @mcp.tool()
    async def inventory_list(
        product_id: str | None = None,
        warehouse_id: str | None = None,
        page_number: int | str | None = 1,
        page_size: int | str | None = 100,
        sort_by: str | None = "product_id",
        sort_direction: str | None = "ASC",
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """List inventory (read-only)."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request(
            "GET",
            "/inventory",
            params={
                "product_id": product_id,
                "warehouse_id": warehouse_id,
                "page_number": _coerce_positive_int(page_number) or 1,
                "page_size": _coerce_positive_int(page_size) or 100,
                "sort_by": sort_by,
                "sort_direction": sort_direction,
            },
            auth=effective,
        )

    @mcp.tool()
    async def inventory_get(
        product_id: str,
        warehouse_id: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Get a single inventory record by ids (read-only)."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request(
            "GET",
            f"/inventory/{product_id}/{warehouse_id}",
            auth=effective,
        )

    # -----------------
    # API Keys (admin-gated by REST API)
    # -----------------

    @mcp.tool()
    async def api_keys_create(
        name: str,
        scopes: list[str] | None = None,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Create an API key (admin only in REST)."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request(
            "POST",
            "/api-keys",
            json={"name": name, "scopes": scopes},
            auth=effective,
        )

    @mcp.tool()
    async def api_keys_list(
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """List API keys (admin only in REST)."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request("GET", "/api-keys", auth=effective)

    @mcp.tool()
    async def api_keys_revoke(
        api_key_id: str,
        access_token: str | None = None,
        api_key: str | None = None,
        ctx: Context | None = None,
    ) -> Any:
        """Revoke (soft-delete) an API key by id (admin only in REST)."""
        header_auth = _header_auth(ctx)
        effective = header_auth.merged(_auth_from_args(access_token=access_token, api_key=api_key))
        effective = _apply_default_auth(effective, default_api_key=settings.default_api_key)
        _require_auth(effective)
        return await client.request(
            "DELETE",
            f"/api-keys/{api_key_id}",
            auth=effective,
            expect_json=False,
        )


    return {
        "auth_debug",
        "auth_login",
        "auth_refresh",
        "patients_list",
        "patients_get",
        "patients_create",
        "patients_update",
        "patients_delete",
        "orders_list",
        "orders_get",
        "orders_create",
        "orders_update",
        "orders_delete",
        "quotations_list",
        "quotations_get",
        "quotations_accept",
        "quotations_reject",
        "quotations_status_counts",
        "trips_list",
        "trips_get",
        "trips_create",
        "trips_update",
        "trips_delete",
        "trips_status_counts",
        "asls_list",
        "asls_list_text",
        "asls_business_counts",
        "products_list",
        "products_get",
        "inventory_list",
        "inventory_get",
        "api_keys_create",
        "api_keys_list",
        "api_keys_revoke",
    }
