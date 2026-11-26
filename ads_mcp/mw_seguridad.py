"""Mentalidad Web security hooks for the Google Ads MCP server.

This module keeps the Mentalidad Web hardening isolated from the upstream
Google code so the fork can keep merging upstream changes with minimal
conflicts. Upstream files only call into the two hooks below:

* ``forbid_server_credentials_in_remote_mode``: called from
  ``ads_mcp.utils._create_credentials`` before the Application Default
  Credentials fallback. In remote OAuth mode every request must use the
  authenticated user's token, never server credentials.
* ``build_google_provider``: called from ``ads_mcp.coordinator`` to build the
  OAuth provider. When ``GOOGLE_ADS_MCP_ALLOWED_DOMAINS`` is set it returns
  a ``GoogleProvider`` subclass that rejects users outside the
  allowed Google Workspace domains.
"""

from __future__ import annotations

import logging
import os

from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.providers.google import GoogleProvider

logger = logging.getLogger(__name__)

ALLOWED_DOMAINS_ENV_VAR = "GOOGLE_ADS_MCP_ALLOWED_DOMAINS"


class ServerCredentialsForbiddenError(PermissionError):
    """Raised when a remote request has no user token to call the API with."""


def forbid_server_credentials_in_remote_mode() -> None:
    """Blocks the Application Default Credentials fallback in remote mode.

    In local stdio mode (no OAuth client configured) this is a no-op, so the
    upstream ADC behavior stays unchanged.

    Raises:
        ServerCredentialsForbiddenError: if the server runs in remote OAuth
            mode, where only the authenticated user's token may be used.
    """
    # Imported lazily: ads_mcp.utils imports this module.
    from ads_mcp.utils import is_remote_oauth_mode

    if is_remote_oauth_mode():
        raise ServerCredentialsForbiddenError(
            "No hay un token de usuario para esta solicitud. En modo remoto "
            "el servidor no usa credenciales propias: vuelve a conectar el "
            "conector e inicia sesión con tu cuenta de Google."
        )


def get_allowed_domains() -> frozenset[str]:
    """Returns the allowed email domains from GOOGLE_ADS_MCP_ALLOWED_DOMAINS.

    The variable is a comma separated list, for example
    ``mentalidadweb.com,otrodominio.com``. Values are normalized to lower case
    and a leading ``@`` is ignored. Returns an empty set when the variable is
    unset or blank, which means no domain restriction.
    """
    raw = os.environ.get(ALLOWED_DOMAINS_ENV_VAR, "")
    domains = set()
    for item in raw.split(","):
        domain = item.strip().lower().lstrip("@")
        if domain:
            domains.add(domain)
    return frozenset(domains)


def get_verified_email(claims: dict | None) -> str | None:
    """Returns the normalized email of a verified Google identity.

    Args:
        claims: The ``AccessToken.claims`` built by FastMCP's
            ``GoogleTokenVerifier``.

    Returns:
        The email in lower case, or ``None`` when the claims are missing, the
        email is not verified (``email_verified`` must be true) or the email
        is malformed.
    """
    if not claims:
        return None

    verified = claims.get("email_verified")
    if verified is not True and str(verified).lower() != "true":
        return None

    email = claims.get("email")
    if not isinstance(email, str):
        return None
    email = email.strip().lower()
    if email.count("@") != 1 or email.startswith("@") or email.endswith("@"):
        return None
    return email


def is_identity_allowed(
    claims: dict | None, allowed_domains: frozenset[str]
) -> bool:
    """Decides whether a verified Google identity belongs to an allowed domain.

    All three checks must pass (fail closed):

    1. ``email_verified`` is true.
    2. The email domain is one of ``allowed_domains``.
    3. The Google Workspace hosted domain (``hd``) is one of
       ``allowed_domains``. Google only sets ``hd`` for accounts managed by a
       Workspace organization, so this rejects consumer Google accounts that
       merely registered an address under the domain.

    Args:
        claims: The ``AccessToken.claims`` built by FastMCP's
            ``GoogleTokenVerifier``. ``hd`` comes from the userinfo response
            stored under ``google_user_data``.
        allowed_domains: Lower case allowed domains.
    """
    if not claims or not allowed_domains:
        return False

    email = get_verified_email(claims)
    if email is None:
        return False
    email_domain = email.rsplit("@", 1)[1]
    if email_domain not in allowed_domains:
        return False

    user_data = claims.get("google_user_data") or {}
    hosted_domain = user_data.get("hd") if isinstance(user_data, dict) else None
    if not isinstance(hosted_domain, str):
        return False
    return hosted_domain.strip().lower() in allowed_domains


class DomainRestrictedGoogleProvider(GoogleProvider):
    """GoogleProvider that only accepts users from the allowed domains.

    ``verify_token`` is the method the MCP bearer authentication backend calls
    on every HTTP request, so a rejected identity gets an HTTP 401 before any
    tool, resource or listing runs.
    """

    def __init__(self, *args, allowed_domains: frozenset[str], **kwargs):
        if not allowed_domains:
            raise ValueError("allowed_domains must not be empty.")
        self._allowed_domains = frozenset(allowed_domains)
        super().__init__(*args, **kwargs)

    async def verify_token(self, token: str) -> AccessToken | None:
        access_token = await super().verify_token(token)
        if access_token is None:
            return None
        if not is_identity_allowed(access_token.claims, self._allowed_domains):
            logger.warning(
                "Rejected an authenticated user outside the allowed domains."
            )
            return None
        return access_token


def build_google_provider(
    default_provider_class: type[GoogleProvider], **provider_kwargs
) -> GoogleProvider:
    """Builds the OAuth provider, restricted by domain when configured.

    Args:
        default_provider_class: The provider class the upstream coordinator
            would use. It is used unchanged when no domain restriction is set.
        **provider_kwargs: Keyword arguments for the provider constructor.
    """
    allowed_domains = get_allowed_domains()
    if not allowed_domains:
        return default_provider_class(**provider_kwargs)
    return DomainRestrictedGoogleProvider(
        allowed_domains=allowed_domains, **provider_kwargs
    )
