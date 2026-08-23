from __future__ import annotations

import json
from typing import Any, cast

from fastmcp import FastMCPApp
from prefab_ui.actions import SetState, ShowToast
from prefab_ui.actions.mcp import CallTool
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    Badge,
    Button,
    Card,
    Column,
    DataTable,
    DataTableColumn,
    Heading,
    If,
    Loader,
    Muted,
    Row,
    Separator,
    Tab,
    Tabs,
    Textarea,
)
from prefab_ui.rx import ERROR, RESULT, Rx, STATE

from ..settings import AnticaFarmaciaSettings

app = FastMCPApp("AnticaFarmacia")


def _default_initial_state() -> dict[str, Any]:
    return {
        "console_loading": False,
        "registry_loading": False,
        "overall_status": "Unknown",
        "local_mcp_status": "Unknown",
        "google_workspace_status": "Unknown",
        "authentication_status": "Unknown",
        "last_checked": "Not checked",
        "gateway_backends": {"mounted": []},
        "gateway_backends_mounted": [],
        "gateway_health": {"summary": ""},
        "gateway_health_rows": [],
        "gateway_auth": {"results": []},
        "gateway_auth_rows": [],
        "registry_overview": "Click 'Refresh Status' to load operational summary.",
        "registry_summary": (
            "Startup summary:\n"
            "- App loaded successfully\n"
            "- Click 'Refresh Status' for live data\n"
            "- Connected services are shown immediately"
        ),
    }


_INITIAL_STATE: dict[str, Any] = _default_initial_state()


def _build_initial_state(settings: AnticaFarmaciaSettings | None) -> dict[str, Any]:
    state = _default_initial_state()
    if settings is None:
        return state

    configured_rows = [
        {
            "name": remote.name,
            "namespace": remote.namespace,
            "url": remote.url,
        }
        for remote in settings.gateway.remotes
    ]

    state["gateway_backends"] = {
        "mode": settings.gateway.mode,
        "route_policy": settings.gateway.route_policy,
        "mounted": configured_rows,
    }
    state["gateway_backends_mounted"] = configured_rows
    state["gateway_health_rows"] = [
        {
            "name": row["name"],
            "reachable": "unknown",
            "circuit_state": "unknown",
            "failure_count": 0,
            "latency_ms": "-",
            "error": "Click 'Refresh Remote Health' to run live probe",
        }
        for row in configured_rows
    ]
    state["gateway_auth_rows"] = [
        {
            "remote_name": row["name"],
            "configured": "unknown",
            "auth_state": "Status unavailable",
            "runtime_access_token_present": False,
            "runtime_refresh_token_present": False,
            "refresh_flow_configured": "unknown",
            "error": "Click 'Check Authentication' to run live probe",
        }
        for row in configured_rows
    ]

    summary = {
        "local": {
            "apps": {"names": ["AnticaFarmacia"]},
        },
        "remote": {
            "mode": settings.gateway.mode,
            "route_policy": settings.gateway.route_policy,
            "configured": configured_rows,
        },
        "note": "Click refresh buttons for live runtime details.",
    }
    state["registry_summary"] = json.dumps(summary, indent=2)
    state["registry_overview"] = (
        "Local App: AnticaFarmacia\n"
        f"Connected Services: {', '.join(r['name'] for r in configured_rows) if configured_rows else 'none'}\n"
        f"Routing: {settings.gateway.route_policy}"
    )
    return state


@app.ui()
def anticafarmacia_console():
    with Column(gap=4, css_class="p-6 max-w-5xl mx-auto") as view:
        Heading("AnticaFarmacia MCP Console")
        Muted("Operational view for connections, authentication, and capabilities.")

        with Row(gap=2, align="center"):
            Badge(f"Overall: {STATE.overall_status}", variant="secondary")
            Badge(f"Local MCP: {STATE.local_mcp_status}", variant="outline")
            Badge(f"Google Workspace: {STATE.google_workspace_status}", variant="outline")
            Badge(f"Authentication: {STATE.authentication_status}", variant="outline")

        Muted(f"Last checked: {STATE.last_checked}")

        with Row(gap=2, align="center"):
            Button(
                "Refresh Status",
                button_type="button",
                disabled=Rx("console_loading"),
                on_click=[
                    SetState("console_loading", True),
                    CallTool(
                        "gateway_console_status",
                        on_success=[
                            SetState("overall_status", RESULT.overall_status),
                            SetState("local_mcp_status", RESULT.local_mcp_status),
                            SetState("google_workspace_status", RESULT.google_workspace_status),
                            SetState("authentication_status", RESULT.authentication_status),
                            SetState("last_checked", RESULT.last_checked),
                            SetState("gateway_backends_mounted", RESULT.connected_services),
                            SetState("gateway_health_rows", RESULT.connection_health),
                            SetState("gateway_auth_rows", RESULT.authentication_rows),
                            SetState("registry_overview", RESULT.registry_overview),
                            SetState("registry_summary", RESULT.registry_json),
                            SetState("console_loading", False),
                            ShowToast("Status updated", variant="success"),
                        ],
                        on_error=[
                            SetState("console_loading", False),
                            ShowToast(ERROR, variant="error"),
                        ],
                    ),
                ],
            )
            with If(Rx("console_loading") == True):
                Loader(size="sm", variant="dots")

        with Tabs():
            with Tab("Connections"):
                with Row(gap=2, align="center"):
                    Badge("Connected Services", variant="secondary")
                    Button(
                        "Refresh Backends",
                        button_type="button",
                        disabled=Rx("console_loading"),
                        on_click=[
                            SetState("console_loading", True),
                            CallTool(
                                "gateway_list_backends",
                                on_success=[
                                    SetState("gateway_backends", RESULT),
                                    SetState("gateway_backends_mounted", RESULT.mounted),
                                    SetState("console_loading", False),
                                    ShowToast("Gateway backends loaded", variant="success"),
                                ],
                                on_error=[
                                    SetState("console_loading", False),
                                    ShowToast(ERROR, variant="error"),
                                ],
                            ),
                        ],
                    )
                    Button(
                        "Check Connection Health",
                        variant="secondary",
                        button_type="button",
                        disabled=Rx("console_loading"),
                        on_click=[
                            SetState("console_loading", True),
                            CallTool(
                                "gateway_console_status",
                                on_success=[
                                    SetState("overall_status", RESULT.overall_status),
                                    SetState("local_mcp_status", RESULT.local_mcp_status),
                                    SetState("google_workspace_status", RESULT.google_workspace_status),
                                    SetState("authentication_status", RESULT.authentication_status),
                                    SetState("last_checked", RESULT.last_checked),
                                    SetState("gateway_backends_mounted", RESULT.connected_services),
                                    SetState("gateway_health_rows", RESULT.connection_health),
                                    SetState("console_loading", False),
                                    ShowToast("Remote health updated", variant="success"),
                                ],
                                on_error=[
                                    SetState("console_loading", False),
                                    ShowToast(ERROR, variant="error"),
                                ],
                            ),
                        ],
                    )
                    with If(Rx("console_loading") == True):
                        Loader(size="sm", variant="dots")

                Separator()
                Heading("Connected Services", level=3)
                DataTable(
                    columns=[
                        DataTableColumn(key="name", header="Name", sortable=True),
                        DataTableColumn(key="namespace", header="Namespace", sortable=True),
                        DataTableColumn(key="url", header="URL"),
                    ],
                    rows=STATE.gateway_backends_mounted,
                    search=False,
                    paginated=True,
                    page_size=10,
                )

                Separator()
                Heading("Connection Health", level=3)
                DataTable(
                    columns=[
                        DataTableColumn(key="name", header="Name", sortable=True),
                        DataTableColumn(key="service_state", header="Status", sortable=True),
                        DataTableColumn(key="reachable", header="Reachable", sortable=True),
                        DataTableColumn(key="circuit_state", header="Circuit", sortable=True),
                        DataTableColumn(key="failure_count", header="Failures", sortable=True),
                        DataTableColumn(key="latency_ms", header="Latency ms", sortable=True),
                        DataTableColumn(key="error", header="Error"),
                    ],
                    rows=STATE.gateway_health_rows,
                    search=False,
                    paginated=True,
                    page_size=10,
                )

            with Tab("Authentication"):
                with Row(gap=2, align="center"):
                    Badge("Auth", variant="secondary")
                    Button(
                        "Check Authentication",
                        button_type="button",
                        disabled=Rx("console_loading"),
                        on_click=[
                            SetState("console_loading", True),
                            CallTool(
                                "gateway_console_status",
                                on_success=[
                                    SetState("overall_status", RESULT.overall_status),
                                    SetState("local_mcp_status", RESULT.local_mcp_status),
                                    SetState("google_workspace_status", RESULT.google_workspace_status),
                                    SetState("authentication_status", RESULT.authentication_status),
                                    SetState("last_checked", RESULT.last_checked),
                                    SetState("gateway_auth_rows", RESULT.authentication_rows),
                                    SetState("console_loading", False),
                                    ShowToast("Remote auth status updated", variant="success"),
                                ],
                                on_error=[
                                    SetState("console_loading", False),
                                    ShowToast(ERROR, variant="error"),
                                ],
                            ),
                        ],
                    )
                    with If(Rx("console_loading") == True):
                        Loader(size="sm", variant="dots")

                Separator()
                Heading("Authentication Runtime", level=3)
                DataTable(
                    columns=[
                        DataTableColumn(key="remote_name", header="Remote", sortable=True),
                        DataTableColumn(key="auth_state", header="Auth Status", sortable=True),
                        DataTableColumn(key="configured", header="Configured", sortable=True),
                        DataTableColumn(key="runtime_access_token_present", header="Runtime Access", sortable=True),
                        DataTableColumn(key="runtime_refresh_token_present", header="Runtime Refresh", sortable=True),
                        DataTableColumn(key="refresh_flow_configured", header="Refresh Flow", sortable=True),
                        DataTableColumn(key="error", header="Error"),
                    ],
                    rows=STATE.gateway_auth_rows,
                    search=False,
                    paginated=True,
                    page_size=10,
                )

            with Tab("Capabilities"):
                with Row(gap=2, align="center"):
                    Badge("Capabilities", variant="secondary")
                    Button(
                        "Refresh Registry Summary",
                        variant="secondary",
                        button_type="button",
                        disabled=Rx("registry_loading"),
                        on_click=[
                            SetState("registry_loading", True),
                            CallTool(
                                "registry_summary_text",
                                on_success=[
                                    SetState("registry_summary", RESULT),
                                    SetState("registry_loading", False),
                                    ShowToast("Registry summary loaded", variant="success"),
                                ],
                                on_error=[
                                    SetState("registry_loading", False),
                                    ShowToast(ERROR, variant="error"),
                                ],
                            ),
                        ],
                    )
                    with If(Rx("registry_loading") == True):
                        Loader(size="sm", variant="dots")

                Separator()
                Heading("Capability Overview", level=3)
                with Card():
                    Textarea(
                        name="registry_overview",
                        read_only=True,
                        rows=6,
                        value=STATE.registry_overview,
                    )

                Separator()
                Heading("Raw Registry JSON (Advanced)", level=3)
                with Card():
                    Textarea(
                        name="registry_json",
                        read_only=True,
                        rows=18,
                        value=STATE.registry_summary,
                        placeholder="Click 'Refresh Registry Summary' to load.",
                    )

    return PrefabApp(
        view=view,
        state=_INITIAL_STATE,
    )


def create_anticafarmacia_app(*_args, **_kwargs) -> FastMCPApp:
    settings = None
    if len(_args) >= 2:
        candidate = _args[1]
        if isinstance(candidate, AnticaFarmaciaSettings):
            settings = candidate

    global _INITIAL_STATE
    _INITIAL_STATE = _build_initial_state(settings)
    return cast(FastMCPApp, app)
