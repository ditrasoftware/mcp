from __future__ import annotations

import os
from typing import cast

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
    Embed,
    Form,
    Heading,
    If,
    Input,
    Loader,
    Muted,
    Row,
    Separator,
    Tab,
    Tabs,
    Text,
    Textarea,
)
from prefab_ui.components.charts import BarChart, ChartSeries, PieChart
from prefab_ui.rx import ERROR, RESULT, Rx, STATE

from fastmcp import FastMCPApp

from .asl_ui import render_asl_explorer


app = FastMCPApp("FerreroMed")


def _env_truthy(name: str, default: str = "") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


"""UI provider.

This FastMCPApp intentionally contains only the UI.

All backend tools (patients_list, trips_list, asls_list, etc.) live in
`ferreromed_mcp/server.py` as `@mcp.tool()` definitions (LocalProvider). This
avoids duplicate tool names across providers and prevents warnings like:
"Duplicate list_tools component 'tool:asls_list@'".
"""


@app.ui()
def console() -> PrefabApp:
    """Render the FerreroMed interactive operations console UI."""
    with Column(gap=6, css_class="p-6 touch-manipulation max-w-6xl mx-auto") as view:
        Heading("FerreroMed")
        Muted("Interactive FerreroMed tools with forms, tables, and charts.")

        with Tabs():
            with Tab("Auth"):
                Heading("Auth", level=3)
                Muted("Use API key for service-to-service calls, or login for Bearer tokens.")

                with Row(gap=2, align="center"):
                    Badge("Mode", variant="secondary")
                    with If(Rx("dev_mode") == True):
                        Badge("Developer", variant="outline")
                    with If(Rx("dev_mode") == False):
                        Badge("Production", variant="outline")
                    with If(Rx("dev_mode") == False):
                        Button(
                            "Enable developer mode",
                            variant="outline",
                            button_type="button",
                            on_click=SetState("dev_mode", True),
                        )
                    with If(Rx("dev_mode") == True):
                        Button(
                            "Disable developer mode",
                            variant="outline",
                            button_type="button",
                            on_click=SetState("dev_mode", False),
                        )

                with If(Rx("dev_mode") == True):
                    Muted(
                        "Developer mode: intended for debugging/demo; includes power-user affordances and may surface more data."
                    )

                with Card():
                    with Form(
                        on_submit=[
                            SetState("access_token", STATE.access_token),
                            SetState("api_key", STATE.api_key),
                            SetState("refresh_token", STATE.refresh_token),
                            ShowToast("Auth values saved", variant="success"),
                        ]
                    ):
                        Input(name="access_token", placeholder="Access token (Bearer)")
                        Input(name="api_key", placeholder="API key (X-Api-Key)")
                        Input(name="refresh_token", placeholder="Refresh token (optional)")
                        Button("Save", button_type="submit")

                Separator()
                Heading("Login", level=3)
                with Form(
                    on_submit=[
                        SetState("auth_login_loading", True),
                        CallTool(
                            "auth_login",
                            arguments={
                                "email": STATE.email,
                                "password": STATE.password,
                                "provider": STATE.provider,
                            },
                            on_success=[
                                SetState("access_token", RESULT.access_token),
                                SetState("refresh_token", RESULT.refresh_token),
                                SetState("auth_login_loading", False),
                                ShowToast("Login OK", variant="success"),
                            ],
                            on_error=[
                                SetState("auth_login_loading", False),
                                ShowToast(ERROR, variant="error"),
                            ],
                        ),
                    ]
                ):
                    Input(name="email", placeholder="Email")
                    Input(name="password", placeholder="Password", input_type="password")
                    Input(name="provider", placeholder="OAuth provider (optional)")
                    with Row(gap=2, align="center"):
                        Button(
                            "Login",
                            button_type="submit",
                            disabled=Rx("auth_login_loading"),
                        )
                        with If(Rx("auth_login_loading") == True):
                            Loader(size="sm", variant="dots")

                Separator()
                Heading("Refresh", level=3)
                with Form(
                    on_submit=[
                        SetState("auth_refresh_loading", True),
                        CallTool(
                            "auth_refresh",
                            arguments={"refresh_token": STATE.refresh_token},
                            on_success=[
                                SetState("access_token", RESULT.access_token),
                                SetState("refresh_token", RESULT.refresh_token),
                                SetState("auth_refresh_loading", False),
                                ShowToast("Token refreshed", variant="success"),
                            ],
                            on_error=[
                                SetState("auth_refresh_loading", False),
                                ShowToast(ERROR, variant="error"),
                            ],
                        ),
                    ]
                ):
                    Input(name="refresh_token", placeholder="Refresh token")
                    with Row(gap=2, align="center"):
                        Button(
                            "Refresh",
                            button_type="submit",
                            disabled=Rx("auth_refresh_loading"),
                        )
                        with If(Rx("auth_refresh_loading") == True):
                            Loader(size="sm", variant="dots")

            with Tab("Patients"):
                Heading("Patients", level=3)
                with Card():
                    with Form(
                        on_submit=[
                            SetState("patients_loading", True),
                            CallTool(
                                "patients_list",
                                arguments={
                                    "tax_id": STATE.patient_tax_id,
                                    "full_name": STATE.patient_full_name,
                                    "city": STATE.patient_city,
                                    "page_size": STATE.patient_page_size,
                                },
                                on_success=[
                                    SetState("patients", RESULT),
                                    SetState("patients_loading", False),
                                    ShowToast("Patients loaded", variant="success"),
                                ],
                                on_error=[
                                    SetState("patients_loading", False),
                                    ShowToast(ERROR, variant="error"),
                                ],
                            ),
                        ]
                    ):
                        Input(name="patient_tax_id", placeholder="Tax ID (optional)")
                        Input(name="patient_full_name", placeholder="Full name (optional)")
                        Input(name="patient_city", placeholder="City (optional)")
                        Input(name="patient_page_size", placeholder="Page size", input_type="number")
                        with Row(gap=2, align="center"):
                            Button(
                                "Search",
                                button_type="submit",
                                disabled=Rx("patients_loading"),
                            )
                            with If(Rx("patients_loading") == True):
                                Loader(size="sm", variant="dots")

                Separator()
                DataTable(
                    columns=[
                        DataTableColumn(key="id", header="ID", sortable=True),
                        DataTableColumn(key="full_name", header="Full name", sortable=True),
                        DataTableColumn(key="tax_id", header="Tax ID", sortable=True),
                        DataTableColumn(key="dom_city", header="City"),
                    ],
                    rows=STATE.patients,
                    search=True,
                    paginated=True,
                    page_size=15,
                )

            with Tab("Quotations"):
                Heading("Quotations", level=3)
                with Row(gap=2, align="center"):
                    Button(
                        "Refresh list",
                        button_type="button",
                        disabled=Rx("quotations_loading"),
                        on_click=[
                            SetState("quotations_loading", True),
                            CallTool(
                                "quotations_list",
                                arguments={
                                    "asl_code": STATE.quote_asl_code,
                                },
                                on_success=[
                                    SetState("quotations", RESULT),
                                    SetState("quotations_loading", False),
                                    ShowToast("Quotations loaded", variant="success"),
                                ],
                                on_error=[
                                    SetState("quotations_loading", False),
                                    ShowToast(ERROR, variant="error"),
                                ],
                            ),
                        ],
                    )
                    with If(Rx("quotations_loading") == True):
                        Loader(size="sm", variant="dots")
                    Badge("/quotations", variant="secondary")

                with Form(
                    on_submit=[
                        SetState("quotation_counts_loading", True),
                        CallTool(
                            "quotations_status_counts",
                            arguments={
                                "asl_code": STATE.quote_asl_code,
                            },
                            on_success=[
                                SetState("quotation_counts", RESULT),
                                SetState("quotation_counts_loading", False),
                            ],
                            on_error=[
                                SetState("quotation_counts_loading", False),
                                ShowToast(ERROR, variant="error"),
                            ],
                        ),
                    ]
                ):
                    Input(name="quote_asl_code", placeholder="ASL code (optional)")
                    with Row(gap=2, align="center"):
                        Button(
                            "Update chart",
                            button_type="submit",
                            disabled=Rx("quotation_counts_loading"),
                        )
                        with If(Rx("quotation_counts_loading") == True):
                            Loader(size="sm", variant="dots")

                Separator()
                Heading("Status breakdown", level=4)
                PieChart(
                    data=STATE.quotation_counts,
                    data_key="count",
                    name_key="status",
                    show_legend=True,
                    inner_radius=60,
                )

                Separator()
                DataTable(
                    columns=[
                        DataTableColumn(key="id", header="ID", sortable=True),
                        DataTableColumn(key="quote_status", header="Status", sortable=True),
                        DataTableColumn(key="asl_code", header="ASL"),
                        DataTableColumn(key="patient_name", header="Patient"),
                    ],
                    rows=STATE.quotations,
                    search=True,
                    paginated=True,
                    page_size=15,
                )

            with Tab("Trips"):
                Heading("Trips", level=3)
                with Card():
                    with Form(
                        on_submit=[
                            SetState("trips_loading", True),
                            CallTool(
                                "trips_list",
                                arguments={
                                    "business_entity": STATE.trip_business_entity,
                                    "asl_code": STATE.trip_asl_code,
                                    "from_date": STATE.trip_from_date,
                                    "to_date": STATE.trip_to_date,
                                    "page_size": STATE.trip_page_size,
                                },
                                on_success=[
                                    SetState("trips", RESULT),
                                    SetState("trips_loading", False),
                                    ShowToast("Trips loaded", variant="success"),
                                ],
                                on_error=[
                                    SetState("trips_loading", False),
                                    ShowToast(ERROR, variant="error"),
                                ],
                            ),
                        ]
                    ):
                        Input(name="trip_business_entity", placeholder="Business entity (optional)")
                        Input(name="trip_asl_code", placeholder="ASL code (optional)")
                        Input(name="trip_from_date", placeholder="From date (YYYY-MM-DD)")
                        Input(name="trip_to_date", placeholder="To date (YYYY-MM-DD)")
                        Input(name="trip_page_size", placeholder="Page size", input_type="number")
                        with Row(gap=2, align="center"):
                            Button(
                                "Search",
                                button_type="submit",
                                disabled=Rx("trips_loading"),
                            )
                            with If(Rx("trips_loading") == True):
                                Loader(size="sm", variant="dots")

                with Row(gap=2, align="center"):
                    Button(
                        "Update status chart",
                        button_type="button",
                        disabled=Rx("trip_counts_loading"),
                        on_click=[
                            SetState("trip_counts_loading", True),
                            CallTool(
                                "trips_status_counts",
                                arguments={
                                    "business_entity": STATE.trip_business_entity,
                                    "asl_code": STATE.trip_asl_code,
                                },
                                on_success=[
                                    SetState("trip_counts", RESULT),
                                    SetState("trip_counts_loading", False),
                                ],
                                on_error=[
                                    SetState("trip_counts_loading", False),
                                    ShowToast(ERROR, variant="error"),
                                ],
                            ),
                        ],
                    )
                    with If(Rx("trip_counts_loading") == True):
                        Loader(size="sm", variant="dots")

                Separator()
                Heading("Status breakdown", level=4)
                BarChart(
                    data=STATE.trip_counts,
                    series=[ChartSeries(data_key="count", label="Trips")],
                    x_axis="status",
                    show_legend=False,
                    height=240,
                )

                Separator()
                DataTable(
                    columns=[
                        DataTableColumn(key="trip_id", header="Trip ID", sortable=True),
                        DataTableColumn(key="trip_status", header="Status", sortable=True),
                        DataTableColumn(key="trip_date", header="Date"),
                        DataTableColumn(key="orders__asl_code", header="ASL"),
                        DataTableColumn(key="orders__delivery_city", header="City"),
                    ],
                    rows=STATE.trips,
                    search=True,
                    paginated=True,
                    page_size=15,
                )

            with Tab("Lookups"):
                Heading("Lookups", level=3)
                Muted("Read-only helpers: ASLs, Products.")

                render_asl_explorer(include_spotlight=True, show_account_id=True)

                Separator()
                Heading("Products", level=4)
                with Row(gap=2, align="center"):
                    Button(
                        "List products",
                        button_type="button",
                        disabled=Rx("products_loading"),
                        on_click=[
                            SetState("products_loading", True),
                            CallTool(
                                "products_list",
                                arguments={
                                    "page_size": 25,
                                },
                                on_success=[
                                    SetState("products", RESULT),
                                    SetState("products_loading", False),
                                ],
                                on_error=[
                                    SetState("products_loading", False),
                                    ShowToast(ERROR, variant="error"),
                                ],
                            ),
                        ],
                    )
                    with If(Rx("products_loading") == True):
                        Loader(size="sm", variant="dots")

                DataTable(
                    columns=[
                        DataTableColumn(key="product_id", header="Product", sortable=True),
                        DataTableColumn(key="description", header="Description"),
                        DataTableColumn(key="brand_name", header="Brand"),
                    ],
                    rows=STATE.products,
                    search=True,
                    paginated=True,
                    page_size=15,
                )

            with Tab("Maps"):
                Heading("Maps", level=3)
                Muted("Demo mapping: list and find nearest warehouses/pharmacies. Origin accepts a known place (e.g. 'Pescara') or 'lat,lng'.")

                with Card():
                    with Row(gap=2, align="center"):
                        Badge("Kind", variant="secondary")
                        Button(
                            "Warehouses",
                            variant="outline",
                            button_type="button",
                            on_click=SetState("maps_kind", "warehouse"),
                        )
                        Button(
                            "Pharmacies",
                            variant="outline",
                            button_type="button",
                            on_click=SetState("maps_kind", "pharmacy"),
                        )
                        Badge("Mode", variant="secondary")
                        Button(
                            "All",
                            variant="outline",
                            button_type="button",
                            on_click=SetState("maps_mode", "all"),
                        )
                        Button(
                            "Nearest",
                            variant="outline",
                            button_type="button",
                            on_click=SetState("maps_mode", "nearest"),
                        )

                    with Row(gap=2, align="center"):
                        Input(name="maps_origin", placeholder="Origin (e.g. Pescara or 42.46,14.21)")
                        Input(name="maps_query", placeholder="Filter (optional)")
                        Input(name="maps_limit", placeholder="Limit", input_type="number")
                        Input(name="maps_nearest_k", placeholder="Nearest k", input_type="number")
                        Input(name="maps_max_km_value", placeholder="Max km (optional)", input_type="number")
                        Input(name="maps_zoom", placeholder="Zoom", input_type="number")

                    with Row(gap=2, align="center"):
                        Button(
                            "Build map",
                            button_type="button",
                            disabled=Rx("maps_loading"),
                            on_click=[
                                SetState("maps_loading", True),
                                CallTool(
                                    "maps_build_map",
                                    arguments={
                                        "kind": STATE.maps_kind,
                                        "mode": STATE.maps_mode,
                                        "origin": STATE.maps_origin,
                                        "query": STATE.maps_query,
                                        "limit": STATE.maps_limit,
                                        "nearest_k": STATE.maps_nearest_k,
                                        "max_km": STATE.maps_max_km_value,
                                        "zoom": STATE.maps_zoom,
                                    },
                                    on_success=[
                                        SetState("maps_title", RESULT.title),
                                        SetState("maps_origin_resolved", RESULT.origin),
                                        SetState("maps_locations", RESULT.locations),
                                        SetState("maps_map_html", RESULT.map_html),
                                        SetState("maps_loading", False),
                                        ShowToast("Map updated", variant="success"),
                                    ],
                                    on_error=[
                                        SetState("maps_loading", False),
                                        ShowToast(ERROR, variant="error"),
                                    ],
                                ),
                            ],
                        )
                        with If(Rx("maps_loading") == True):
                            Loader(size="sm", variant="dots")

                        Button(
                            "Open full map app",
                            variant="secondary",
                            button_type="button",
                            disabled=Rx("maps_loading"),
                            on_click=[
                                CallTool(
                                    "maps_show_map",
                                    arguments={
                                        "kind": STATE.maps_kind,
                                        "mode": STATE.maps_mode,
                                        "origin": STATE.maps_origin,
                                        "query": STATE.maps_query,
                                        "limit": STATE.maps_limit,
                                        "nearest_k": STATE.maps_nearest_k,
                                        "max_km": STATE.maps_max_km_value,
                                        "zoom": STATE.maps_zoom,
                                        "title": STATE.maps_title,
                                    },
                                )
                            ],
                        )

                Separator()
                Heading("Custom locations (advanced)", level=4)
                Muted("Paste a JSON array of locations and open the full-size map app. Each item should include at least name + lat + lng (or a resolvable city).")
                with Card():
                    Textarea(
                        name="maps_custom_locations_json",
                        placeholder=(
                            "Example:\n"
                            "[\n"
                            "  {\"id\": \"WH-001\", \"name\": \"Warehouse Pescara\", \"city\": \"Pescara\", \"lat\": 42.4618, \"lng\": 14.2161, \"kind\": \"warehouse\"},\n"
                            "  {\"id\": \"PH-123\", \"name\": \"Farmacia Centro\", \"city\": \"Chieti\", \"lat\": 42.3487, \"lng\": 14.1675, \"kind\": \"pharmacy\"}\n"
                            "]"
                        ),
                        rows=10,
                    )
                    with Row(gap=2, align="center"):
                        Button(
                            "Open full custom map app",
                            variant="secondary",
                            button_type="button",
                            on_click=[
                                CallTool(
                                    "maps_show_custom_locations_from_json",
                                    arguments={
                                        "locations_json": STATE.maps_custom_locations_json,
                                        "mode": STATE.maps_mode,
                                        "origin": STATE.maps_origin,
                                        "limit": STATE.maps_limit,
                                        "nearest_k": STATE.maps_nearest_k,
                                        "max_km": STATE.maps_max_km_value,
                                        "zoom": STATE.maps_zoom,
                                        "title": STATE.maps_title,
                                    },
                                )
                            ],
                        )

                Separator()
                Heading("Preview", level=4)
                Muted(
                    "ChatGPT enforces a restrictive iframe policy (frame-src 'none') inside the Prefab renderer, so inline URL previews are blocked. "
                    "Use 'Open full map app' or 'Open full custom map app' to view the interactive map."
                )

                Separator()
                Heading("Locations", level=4)
                DataTable(
                    columns=[
                        DataTableColumn(key="id", header="ID", sortable=True),
                        DataTableColumn(key="name", header="Name", sortable=True),
                        DataTableColumn(key="city", header="City", sortable=True),
                        DataTableColumn(key="kind", header="Kind"),
                        DataTableColumn(key="distance_km", header="Distance km", sortable=True),
                        DataTableColumn(key="lat", header="Lat"),
                        DataTableColumn(key="lng", header="Lng"),
                    ],
                    rows=STATE.maps_locations,
                    search=True,
                    paginated=True,
                    page_size=15,
                )

                Separator()
                Heading("HTML", level=4)
                Textarea(
                    name="maps_map_html",
                    placeholder="Click Build map to generate embed HTML...",
                    read_only=True,
                    rows=10,
                )

    return PrefabApp(
        view=view,
        state={
            "dev_mode": _env_truthy("FERREROMED_DEV_MODE"),
            "auth_login_loading": False,
            "auth_refresh_loading": False,
            "patients_loading": False,
            "quotations_loading": False,
            "quotation_counts_loading": False,
            "trips_loading": False,
            "trip_counts_loading": False,
            "products_loading": False,
            "asls_loading": False,
            "asl_spotlight_loading": False,
            "maps_loading": False,
            "access_token": "",
            "api_key": "",
            "refresh_token": "",
            "email": "",
            "password": "",
            "provider": "",
            "patient_tax_id": "",
            "patient_full_name": "",
            "patient_city": "",
            "patient_page_size": 20,
            "quote_asl_code": "",
            "asl_code": "",
            "asl_business_entity": "",
            "asl_max_rows": 300,
            "trip_business_entity": "",
            "trip_asl_code": "",
            "trip_from_date": "",
            "trip_to_date": "",
            "trip_page_size": 20,
            "patients": [],
            "quotations": [],
            "quotation_counts": [],
            "trips": [],
            "trip_counts": [],
            "asls": [],
            "asls_text": "",
            "asls_view": "table",
            "asls_counts": [],
            "asl_spotlight_code": "",
            "asl_spotlight_rows": [],
            "products": [],
            "maps_kind": "warehouse",
            "maps_mode": "all",
            "maps_origin": "Pescara",
            "maps_query": "",
            "maps_limit": 25,
            "maps_nearest_k": 10,
            "maps_max_km_value": None,
            "maps_zoom": 9,
            "maps_title": "",
            "maps_origin_resolved": None,
            "maps_locations": [],
            "maps_map_html": "",
            "maps_custom_locations_json": "",
        },
    )


def create_ferreromed_app(*_args, **_kwargs) -> FastMCPApp:
    return cast(FastMCPApp, app)
