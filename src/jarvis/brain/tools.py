from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    tool: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    ok: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)


AVAILABLE_TOOLS = [
    "resolve_folder",
    "open_folder",
    "search_files",
    "open_result",
    "open_file",
    "open_url",
    "open_app",
    "play_music",
    "stop_music",
    "check_service",
    "scan_folders",
    "ask_user",
    "remember_alias",
    "respond",
]
