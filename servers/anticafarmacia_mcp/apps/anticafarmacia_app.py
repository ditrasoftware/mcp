from __future__ import annotations

from typing import cast

from fastmcp import FastMCPApp
from prefab_ui.actions import SetState
from prefab_ui.actions.mcp import CallTool
from prefab_ui.components import Button, Card, Column, DataTable, DataTableColumn, Heading, Muted, Row, Separator, Textarea
from prefab_ui.rx import RESULT, STATE

app = FastMCPApp("AnticaFarmacia")


@app.ui()
def anticafarmacia_console():
    with Column(gap=4, css_class="p-6 max-w-5xl mx-auto") as view:
        Heading("AnticaFarmacia MCP Console")
        Muted("Local diagnostics and gateway inspection tools.")

        with Row(gap=2, align="center"):
            Button(
                "Refresh Gateway Backends",
                button_type="button",
                on_click=[
                    CallTool(
                        "gateway_list_backends",
                        on_success=[SetState("gateway_backends", RESULT)],
                    )
                ],
            )
            Button(
                "Refresh Registry Summary",
                variant="secondary",
                button_type="button",
                on_click=[
                    CallTool(
                        "registry_summary",
                        on_success=[SetState("registry_summary", RESULT)],
                    )
                ],
            )

        Separator()
        Heading("Mounted Remote Backends", level=3)
        DataTable(
            columns=[
                DataTableColumn(key="name", header="Name", sortable=True),
                DataTableColumn(key="namespace", header="Namespace", sortable=True),
                DataTableColumn(key="url", header="URL"),
            ],
            rows=STATE.gateway_backends.mounted,
            search=True,
            paginated=True,
            page_size=10,
        )

        Separator()
        Heading("Registry JSON", level=3)
        with Card():
            Textarea(
                name="registry_json",
                read_only=True,
                rows=16,
                value=STATE.registry_summary,
                placeholder="Click 'Refresh Registry Summary' to load.",
            )

    return view


def create_anticafarmacia_app(*_args, **_kwargs) -> FastMCPApp:
    return cast(FastMCPApp, app)
