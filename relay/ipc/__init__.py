"""Authenticated local IPC (HTTP + SSE) for the optional accessible panel.
The panel mirrors engine state and can send narrow, safety-gated commands; it is
never required by the core and closing it doesn't stop RELAY."""

from .server import IpcServer, command_allowed, host_ok, token_ok

__all__ = ["IpcServer", "command_allowed", "host_ok", "token_ok"]
