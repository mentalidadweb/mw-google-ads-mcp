"""Tests for the Mentalidad Web read-only and security hardening."""

import importlib
import os
import pathlib
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastmcp import FastMCP
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.providers.google import GoogleProvider

from ads_mcp import mw_seguridad, utils
from ads_mcp.coordinator import initialize_and_mount_tools

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_READ_ONLY_CONFIG = _REPO_ROOT / "tools_config.yaml"

_OAUTH_ENV = {
    "GOOGLE_ADS_MCP_OAUTH_CLIENT_ID": "test-client-id",
    "GOOGLE_ADS_MCP_OAUTH_CLIENT_SECRET": "test-client-secret",
}

_WRITE_TOOL_NAMES = (
    "manage_labels",
    "manage_label_associations",
    "create_asset",
    "upload_video",
)


def _claims(
    email="persona@mentalidadweb.com",
    email_verified="true",
    hd="mentalidadweb.com",
):
    user_data = {"email": email}
    if hd is not None:
        user_data["hd"] = hd
    return {
        "sub": "123",
        "aud": "test-client-id",
        "email": email,
        "email_verified": email_verified,
        "google_user_data": user_data,
    }


class ReadOnlyToolsConfigTest(unittest.IsolatedAsyncioTestCase):
    """The repository tools_config.yaml must expose only read tools."""

    async def test_read_only_config_registers_no_write_tools(self):
        with patch.dict(
            os.environ,
            {"GOOGLE_ADS_MCP_TOOLS_CONFIG": str(_READ_ONLY_CONFIG)},
        ):
            parent = FastMCP("read-only-test")
            initialize_and_mount_tools(parent)
            tool_names = sorted(t.name for t in await parent.list_tools())

        self.assertEqual(
            tool_names,
            [
                "customers_list_accessible_customers",
                "metadata_get_resource_metadata",
                "search_search",
            ],
        )
        for write_tool in _WRITE_TOOL_NAMES:
            for name in tool_names:
                self.assertNotIn(write_tool, name)


class ServerCredentialsTest(unittest.TestCase):
    """_create_credentials never uses ADC in remote OAuth mode."""

    @patch("fastmcp.server.dependencies.get_access_token", return_value=None)
    @patch("google.auth.default")
    def test_remote_mode_without_user_token_raises(self, mock_default, _):
        with patch.dict(os.environ, _OAUTH_ENV, clear=True):
            with self.assertRaises(
                mw_seguridad.ServerCredentialsForbiddenError
            ) as ctx:
                utils._create_credentials()

        mock_default.assert_not_called()
        self.assertIn("token de usuario", str(ctx.exception))

    @patch("fastmcp.server.dependencies.get_access_token")
    @patch("google.auth.default")
    def test_remote_mode_with_user_token_uses_user_token(
        self, mock_default, mock_get_token
    ):
        mock_get_token.return_value = MagicMock(token="user-token")
        with patch.dict(os.environ, _OAUTH_ENV, clear=True):
            credentials = utils._create_credentials()

        mock_default.assert_not_called()
        self.assertEqual(credentials.token, "user-token")

    @patch("fastmcp.server.dependencies.get_access_token", return_value=None)
    @patch("google.auth.default")
    def test_local_mode_without_user_token_keeps_adc(self, mock_default, _):
        adc_credentials = MagicMock()
        mock_default.return_value = (adc_credentials, "project")
        with patch.dict(os.environ, {}, clear=True):
            credentials = utils._create_credentials()

        mock_default.assert_called_once_with(scopes=[utils._ADS_SCOPE])
        self.assertIs(credentials, adc_credentials)


class AllowedDomainsTest(unittest.TestCase):
    """Parsing of GOOGLE_ADS_MCP_ALLOWED_DOMAINS and identity checks."""

    def test_get_allowed_domains_parses_list(self):
        env = {
            "GOOGLE_ADS_MCP_ALLOWED_DOMAINS": " MentalidadWeb.com, @otro.cl ,,"
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                mw_seguridad.get_allowed_domains(),
                frozenset({"mentalidadweb.com", "otro.cl"}),
            )

    def test_get_allowed_domains_unset_or_blank_is_empty(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(mw_seguridad.get_allowed_domains(), frozenset())
        with patch.dict(
            os.environ, {"GOOGLE_ADS_MCP_ALLOWED_DOMAINS": " , "}, clear=True
        ):
            self.assertEqual(mw_seguridad.get_allowed_domains(), frozenset())

    def test_is_identity_allowed(self):
        allowed = frozenset({"mentalidadweb.com"})
        cases = {
            "workspace user": (_claims(), True),
            "verified as bool": (_claims(email_verified=True), True),
            "upper case email": (
                _claims(
                    email="Persona@MentalidadWeb.com", hd="MentalidadWeb.com"
                ),
                True,
            ),
            "other domain": (
                _claims(email="persona@gmail.com", hd=None),
                False,
            ),
            "consumer account under domain (no hd)": (_claims(hd=None), False),
            "hd from other workspace": (_claims(hd="otra.com"), False),
            "email not verified": (_claims(email_verified="false"), False),
            "subdomain is not the domain": (
                _claims(
                    email="persona@sub.mentalidadweb.com",
                    hd="sub.mentalidadweb.com",
                ),
                False,
            ),
            "lookalike suffix": (
                _claims(
                    email="persona@evilmentalidadweb.com",
                    hd="evilmentalidadweb.com",
                ),
                False,
            ),
            "missing email": (_claims(email=None), False),
            "no claims": (None, False),
        }
        for name, (claims, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(
                    mw_seguridad.is_identity_allowed(claims, allowed), expected
                )

    def test_is_identity_allowed_without_domains_rejects(self):
        self.assertFalse(
            mw_seguridad.is_identity_allowed(_claims(), frozenset())
        )


class DomainRestrictedProviderTest(unittest.IsolatedAsyncioTestCase):
    """The OAuth provider rejects tokens from users outside allowed domains."""

    def _provider(self):
        return mw_seguridad.DomainRestrictedGoogleProvider(
            allowed_domains=frozenset({"mentalidadweb.com"}),
            client_id="test-client-id",
            client_secret="test-client-secret",
            base_url="http://localhost:8080",
            jwt_signing_key="test-signing-key",
        )

    async def test_verify_token_accepts_allowed_user(self):
        token = AccessToken(
            token="t", client_id="c", scopes=[], claims=_claims()
        )
        with patch.object(
            GoogleProvider, "verify_token", AsyncMock(return_value=token)
        ):
            self.assertIs(await self._provider().verify_token("t"), token)

    async def test_verify_token_rejects_other_domain(self):
        token = AccessToken(
            token="t",
            client_id="c",
            scopes=[],
            claims=_claims(email="alguien@gmail.com", hd=None),
        )
        with patch.object(
            GoogleProvider, "verify_token", AsyncMock(return_value=token)
        ):
            self.assertIsNone(await self._provider().verify_token("t"))

    async def test_verify_token_keeps_invalid_token_rejected(self):
        with patch.object(
            GoogleProvider, "verify_token", AsyncMock(return_value=None)
        ):
            self.assertIsNone(await self._provider().verify_token("t"))

    def test_empty_allowed_domains_is_an_error(self):
        with self.assertRaises(ValueError):
            mw_seguridad.DomainRestrictedGoogleProvider(
                allowed_domains=frozenset(),
                client_id="test-client-id",
                client_secret="test-client-secret",
            )

    def test_build_google_provider_without_domains_uses_default_class(self):
        default_class = MagicMock()
        with patch.dict(os.environ, {}, clear=True):
            result = mw_seguridad.build_google_provider(default_class, a=1)
        default_class.assert_called_once_with(a=1)
        self.assertIs(result, default_class.return_value)


class CoordinatorDomainWiringTest(unittest.TestCase):
    """coordinator.mcp uses the restricted provider when domains are set."""

    def _reload_coordinator(self, extra_env):
        import ads_mcp.coordinator as coord

        env = {
            **_OAUTH_ENV,
            "GOOGLE_ADS_MCP_JWT_SIGNING_KEY": "test-signing-key",
            "GOOGLE_ADS_MCP_STORAGE_TYPE": "memory",
            **extra_env,
        }
        # Cleanups run last in, first out: restore env, then reload.
        self.addCleanup(lambda: importlib.reload(coord))
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        importlib.reload(coord)
        return coord

    def test_allowed_domains_set_uses_restricted_provider(self):
        coord = self._reload_coordinator(
            {"GOOGLE_ADS_MCP_ALLOWED_DOMAINS": "mentalidadweb.com"}
        )
        self.assertIsInstance(
            coord.mcp.auth, mw_seguridad.DomainRestrictedGoogleProvider
        )

    def test_allowed_domains_unset_keeps_upstream_provider(self):
        coord = self._reload_coordinator({})
        self.assertIs(type(coord.mcp.auth), GoogleProvider)


if __name__ == "__main__":
    unittest.main()
