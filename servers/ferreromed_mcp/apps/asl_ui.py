from __future__ import annotations

from prefab_ui.actions import SetState, ShowToast
from prefab_ui.actions.mcp import CallTool
from prefab_ui.components import (
    Badge,
    Button,
    DataTable,
    DataTableColumn,
    ForEach,
    Form,
    Heading,
    If,
    Input,
    Loader,
    Muted,
    Row,
    Separator,
    Text,
    Textarea,
)
from prefab_ui.components.charts import BarChart, ChartSeries, PieChart
from prefab_ui.rx import ERROR, RESULT, Rx, STATE


SUGGESTED_ASL_PROMPTS = (
    "Try MCP prompts: ferreromed_asl_lookup_helper, ferreromed_asl_business_summary, ferreromed_asl_data_quality_check, ferreromed_maps_gather_and_map."
)


def _auth_args() -> dict:
    # Keep console calls transparent by default: let server-side auth/header
    # handling decide credentials instead of forcing UI state auth values.
    return {}


def _load_asls_table_actions() -> list:
    return [
        SetState("asls_loading", True),
        CallTool(
            "asls_list",
            arguments={
                **_auth_args(),
                "asl_code": STATE.asl_code,
                "business_entity": STATE.asl_business_entity,
                "max_rows": STATE.asl_max_rows,
            },
            on_success=[
                SetState("asls", RESULT),
                SetState("asls_view", "table"),
                SetState("asls_loading", False),
                ShowToast("ASLs loaded", variant="success"),
            ],
            on_error=[
                SetState("asls_loading", False),
                ShowToast(ERROR, variant="error"),
            ],
        ),
    ]


def _load_asls_text_actions() -> list:
    return [
        SetState("asls_loading", True),
        CallTool(
            "asls_list_text",
            arguments={
                **_auth_args(),
                "asl_code": STATE.asl_code,
                "business_entity": STATE.asl_business_entity,
                "max_rows": STATE.asl_max_rows,
            },
            on_success=[
                SetState("asls_text", RESULT),
                SetState("asls_view", "text"),
                SetState("asls_loading", False),
                ShowToast("ASLs loaded (text)", variant="success"),
            ],
            on_error=[
                SetState("asls_loading", False),
                ShowToast(ERROR, variant="error"),
            ],
        ),
    ]


def _load_asls_counts_actions() -> list:
    return [
        SetState("asls_loading", True),
        CallTool(
            "asls_business_counts",
            arguments={
                **_auth_args(),
                "asl_code": STATE.asl_code,
                "business_entity": STATE.asl_business_entity,
                "max_rows": STATE.asl_max_rows,
            },
            on_success=[
                SetState("asls_counts", RESULT),
                SetState("asls_loading", False),
            ],
            on_error=[
                SetState("asls_loading", False),
                ShowToast(ERROR, variant="error"),
            ],
        ),
    ]


def render_asl_explorer(*, include_spotlight: bool, show_account_id: bool = False) -> None:
    """Render the ASLs explorer UI.

    Relies on these state keys:
      - asl_code, asl_business_entity, asl_max_rows
      - asls_view, asls, asls_text, asls_counts

    If include_spotlight=True, also expects:
      - asl_spotlight_code, asl_spotlight_rows
    """

    Heading("ASLs", level=4)
    Muted("Filter, view as table, or fall back to raw text.")

    Text("Suggested prompts")
    Muted(SUGGESTED_ASL_PROMPTS)

    with Row(gap=2, align="center"):
        Input(name="asl_code", placeholder="ASL code (optional)")
        Input(name="asl_business_entity", placeholder="Business entity (optional)")
        Input(name="asl_max_rows", placeholder="Max rows", input_type="number")

    with Row(gap=2, align="center"):
        Button(
            "Table view",
            button_type="button",
            disabled=Rx("asls_loading"),
            on_click=_load_asls_table_actions(),
        )
        Button(
            "Text view",
            variant="secondary",
            button_type="button",
            disabled=Rx("asls_loading"),
            on_click=_load_asls_text_actions(),
        )
        Button(
            "Update chart",
            variant="outline",
            button_type="button",
            disabled=Rx("asls_loading"),
            on_click=_load_asls_counts_actions(),
        )
        with If(Rx("asls_loading") == True):
            Loader(size="sm", variant="dots")

    if include_spotlight:
        Separator()
        Heading("ASL spotlight", level=4)
        Muted("Enter an ASL code to spotlight key fields.")

        with Row(gap=2, align="center"):
            Input(name="asl_spotlight_code", placeholder="ASL code")
            Button(
                "Spotlight",
                variant="secondary",
                button_type="button",
                disabled=Rx("asl_spotlight_loading"),
                on_click=[
                    SetState("asl_spotlight_loading", True),
                    CallTool(
                        "asls_list",
                        arguments={
                            **_auth_args(),
                            "asl_code": STATE.asl_spotlight_code,
                            "max_rows": 1,
                        },
                        on_success=[
                            SetState("asl_spotlight_rows", RESULT),
                            SetState("asl_spotlight_loading", False),
                            ShowToast("Spotlight updated", variant="success"),
                        ],
                        on_error=[
                            SetState("asl_spotlight_loading", False),
                            ShowToast(ERROR, variant="error"),
                        ],
                    ),
                ],
            )
            with If(Rx("asl_spotlight_loading") == True):
                Loader(size="sm", variant="dots")

        with ForEach("asl_spotlight_rows") as asl:
            with Row(gap=2, align="center"):
                Badge("Code", variant="secondary")
                Badge(asl.id, variant="outline")
                Badge("Name", variant="secondary")
                Badge(asl.name, variant="outline")
                Badge("Business", variant="secondary")
                Badge(asl.business_entity, variant="outline")
                Badge("Account", variant="secondary")
                Badge(asl.account_id, variant="outline")

    Separator()
    with If(Rx("asls_view") == "table"):
        columns = [
            DataTableColumn(key="id", header="Code", sortable=True),
            DataTableColumn(key="name", header="Name", sortable=True),
            DataTableColumn(key="business_entity", header="Business", sortable=True),
        ]
        if show_account_id:
            columns.append(DataTableColumn(key="account_id", header="Account"))

        DataTable(
            columns=columns,
            rows=STATE.asls,
            search=True,
            paginated=True,
            page_size=15,
        )

    with If(Rx("asls_view") == "text"):
        Text("Raw output")
        Textarea(
            name="asls_text",
            placeholder="Click Text view to load...",
            read_only=True,
            rows=18,
        )

    Separator()
    Heading("Business breakdown", level=4)
    PieChart(
        data=STATE.asls_counts,
        data_key="count",
        name_key="business_entity",
        show_legend=True,
        inner_radius=55,
    )
    BarChart(
        data=STATE.asls_counts,
        series=[ChartSeries(data_key="count", label="ASLs")],
        x_axis="business_entity",
        show_legend=False,
        height=220,
    )
