"""Mentalidad Web write access allowlist for the Google Ads MCP server.

Write tools stay hidden and blocked for everyone except the verified emails
listed in ``GOOGLE_ADS_MCP_WRITE_ALLOWED_EMAILS``. Read-only tools keep working
for every authenticated user.

A tool counts as read-only only when it declares the MCP annotation
``readOnlyHint=True``. Every other tool, including any future upstream tool
without annotations, is treated as a write tool (fail closed).

The check runs through FastMCP's ``AuthMiddleware``, which filters
``tools/list`` per user and rejects ``tools/call`` for tools the user may not
use. FastMCP skips these checks on the stdio transport, where there is no
OAuth identity and the single local user owns the credentials.

The upstream coordinator only calls ``install_write_access_middleware``.
"""

from __future__ import annotations

import logging
import os

from fastmcp import FastMCP
from fastmcp.server.middleware import AuthMiddleware
from fastmcp.tools.base import Tool
from fastmcp.utilities.authorization import AuthContext

from ads_mcp.mw_seguridad import get_verified_email

logger = logging.getLogger(__name__)

WRITE_ALLOWED_EMAILS_ENV_VAR = "GOOGLE_ADS_MCP_WRITE_ALLOWED_EMAILS"


def get_write_allowed_emails() -> frozenset[str]:
    """Returns the emails allowed to use write tools.

    Reads ``GOOGLE_ADS_MCP_WRITE_ALLOWED_EMAILS``, a comma separated list such
    as ``ana@mentalidadweb.com,juan@mentalidadweb.com``. Values are trimmed and
    lower cased; blank or malformed entries are ignored with a warning. An
    unset or blank variable returns an empty set, which blocks write tools for
    everyone.
    """
    raw = os.environ.get(WRITE_ALLOWED_EMAILS_ENV_VAR, "")
    emails = set()
    for item in raw.split(","):
        email = item.strip().lower()
        if not email:
            continue
        local_part, _, domain = email.partition("@")
        if not local_part or not domain or "@" in domain:
            logger.warning(
                "Ignoring malformed entry in %s.", WRITE_ALLOWED_EMAILS_ENV_VAR
            )
            continue
        emails.add(email)
    return frozenset(emails)


def is_read_only_tool(tool: Tool) -> bool:
    """Returns True only when the tool declares ``readOnlyHint=True``.

    Reads the MCP SDK v2 field name ``read_only_hint``; the camelCase
    ``readOnlyHint`` attribute only exists as a deprecated FastMCP alias.
    """
    read_only_hint = getattr(tool.annotations, "read_only_hint", None)
    return read_only_hint is True


class WriteAccessCheck:
    """FastMCP auth check that limits write tools to an email allowlist.

    Instances are callables compatible with FastMCP's ``AuthCheck`` type.
    """

    def __init__(self, allowed_emails: frozenset[str]):
        self._allowed_emails = frozenset(allowed_emails)

    def __call__(self, ctx: AuthContext) -> bool:
        component = ctx.component
        if not isinstance(component, Tool):
            # Resources and prompts are read-only.
            return True
        if is_read_only_tool(component):
            return True
        if ctx.token is None:
            return False
        email = get_verified_email(ctx.token.claims)
        return email is not None and email in self._allowed_emails


def create_write_access_middleware() -> AuthMiddleware:
    """Builds the middleware that enforces the write allowlist."""
    allowed_emails = get_write_allowed_emails()
    logger.info(
        "Write tools allowlist loaded with %d email(s).", len(allowed_emails)
    )
    return AuthMiddleware(auth=WriteAccessCheck(allowed_emails))


def install_write_access_middleware(server: FastMCP) -> bool:
    """Adds the write allowlist middleware when running in remote OAuth mode.

    Local stdio mode has no OAuth identity, so the allowlist does not apply
    there and the upstream behavior stays unchanged.

    Returns:
        True when the middleware was installed, otherwise False.
    """
    # Imported lazily to keep this module free of upstream import cycles.
    from ads_mcp.utils import is_remote_oauth_mode

    if not is_remote_oauth_mode():
        return False
    server.add_middleware(create_write_access_middleware())
    return True
