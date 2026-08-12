"""FastMCP stdio server exposing exactly four stateful tools."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import Tool as MCPTool

from ..config import Settings, load_settings
from ..shared.runtime import Runtime
from .registry import load_tools
from .router import Router


class ManifestFastMCP(FastMCP):
    """FastMCP server that advertises optional tool-owned input schemas."""

    def __init__(
        self,
        *args: Any,
        tool_input_schemas: dict[str, dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._tool_input_schemas = tool_input_schemas or {}

    async def list_tools(self) -> list[MCPTool]:
        tools = await super().list_tools()
        for tool in tools:
            schema = self._tool_input_schemas.get(tool.name)
            if schema is not None:
                tool.inputSchema = schema
        return tools


def create_server(settings: Settings | None = None) -> FastMCP:
    resolved = settings or load_settings()
    tools = load_tools()
    router = Router(Runtime(resolved), tools)
    server = ManifestFastMCP(
        "NGOPilotMCP",
        instructions=(
            "Use the tool matching the file role. Start a job, then call the "
            "same tool with its returned job_id for status, review, export, "
            "or publication operations."
        ),
        log_level="ERROR",
        tool_input_schemas={
            item.manifest.name: item.manifest.input_schema
            for item in tools
            if item.manifest.input_schema is not None
        },
    )

    def make_invoker(tool_name: str):
        async def invoke(
            operation: str,
            job_id: str | None = None,
            request_id: str | None = None,
            input: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            return await router.call(
                tool_name=tool_name,
                operation=operation,
                job_id=job_id,
                request_id=request_id,
                input_payload=input,
            )

        return invoke

    for registered in tools:
        manifest = registered.manifest
        invoke = make_invoker(manifest.name)

        invoke.__name__ = manifest.name
        invoke.__doc__ = manifest.description
        server.add_tool(
            invoke,
            name=manifest.name,
            description=manifest.description,
            structured_output=True,
        )
    return server
