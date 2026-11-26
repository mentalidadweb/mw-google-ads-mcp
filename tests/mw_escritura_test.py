"""Tests for the Mentalidad Web write tools email allowlist."""

import importlib
import os
import pathlib
import unittest
from unittest.mock import MagicMock, patch

from fastmcp import Client, FastMCP
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.middleware import AuthMiddleware
from fastmcp.tools.base import Tool
from fastmcp.utilities.authorization import AuthContext
from mcp.types import ToolAnnotations

from ads_mcp import mw_escritura
from ads_mcp.coordinator import initialize_and_mount_tools
from ads_mcp.tools import assets_mcp
from ads_mcp.tools.labels import labels_mcp

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_WRITE_CONFIG = _REPO_ROOT / "tools_config_escritura.yaml"

_ALLOWED_EMAIL = "editora@mentalidadweb.com"
_OTHER_EMAIL = "lectora@mentalidadweb.com"

_READ_TOOLS = [
    "customers_list_accessible_customers",
    "metadata_get_resource_metadata",
    "search_search",
]
_WRITE_TOOLS = [
    "assets_create_asset",
    "labels_manage_label_associations",
    "labels_manage_labels",
]

# FastMCP's AuthMiddleware reads the token through this module attribute.
_TOKEN_TARGET = "fastmcp.server.middleware.authorization.get_access_token"


def _token(email=_ALLOWED_EMAIL, email_verified="true"):
    return AccessToken(
        token="t",
        client_id="c",
        scopes=[],
        claims={"email": email, "email_verified": email_verified},
    )


def _restore(components, snapshot):
    components.clear()
    components.update(snapshot)


def _tool(read_only_hint):
    annotations = (
        None
        if read_only_hint is None
        else ToolAnnotations(readOnlyHint=read_only_hint)
    )

    def sample() -> str:
        return "ok"

    return Tool.from_function(sample, annotations=annotations)


class GetWriteAllowedEmailsTest(unittest.TestCase):
    def test_parses_trims_and_lowercases(self):
        env = {
            "GOOGLE_ADS_MCP_WRITE_ALLOWED_EMAILS": (
                " Ana@MentalidadWeb.com , juan@mentalidadweb.com,,"
            )
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                mw_escritura.get_write_allowed_emails(),
                frozenset({"ana@mentalidadweb.com", "juan@mentalidadweb.com"}),
            )

    def test_ignores_malformed_entries(self):
        env = {
            "GOOGLE_ADS_MCP_WRITE_ALLOWED_EMAILS": (
                "mentalidadweb.com,@mentalidadweb.com,ana@,a@b@c,ok@mw.com"
            )
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertLogs(mw_escritura.logger, level="WARNING"):
                emails = mw_escritura.get_write_allowed_emails()
        self.assertEqual(emails, frozenset({"ok@mw.com"}))

    def test_unset_or_blank_is_empty(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                mw_escritura.get_write_allowed_emails(), frozenset()
            )
        with patch.dict(
            os.environ,
            {"GOOGLE_ADS_MCP_WRITE_ALLOWED_EMAILS": " , "},
            clear=True,
        ):
            self.assertEqual(
                mw_escritura.get_write_allowed_emails(), frozenset()
            )


class IsReadOnlyToolTest(unittest.TestCase):
    def test_only_explicit_read_only_hint_counts(self):
        self.assertTrue(mw_escritura.is_read_only_tool(_tool(True)))
        self.assertFalse(mw_escritura.is_read_only_tool(_tool(False)))
        self.assertFalse(mw_escritura.is_read_only_tool(_tool(None)))


class WriteAccessCheckTest(unittest.TestCase):
    def setUp(self):
        self.check = mw_escritura.WriteAccessCheck(frozenset({_ALLOWED_EMAIL}))

    def _allowed(self, token, component):
        return self.check(AuthContext(token=token, component=component))

    def test_read_only_tool_is_allowed_for_everyone(self):
        self.assertTrue(self._allowed(None, _tool(True)))
        self.assertTrue(self._allowed(_token(_OTHER_EMAIL), _tool(True)))

    def test_write_tool_rules(self):
        cases = {
            "allowlisted email": (_token(), True),
            "allowlisted email, other case": (
                _token("Editora@MentalidadWeb.com"),
                True,
            ),
            "verified as bool": (_token(email_verified=True), True),
            "email not in allowlist": (_token(_OTHER_EMAIL), False),
            "email not verified": (_token(email_verified="false"), False),
            "no token": (None, False),
        }
        for name, (token, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(self._allowed(token, _tool(False)), expected)

    def test_tool_without_annotations_is_treated_as_write(self):
        self.assertTrue(self._allowed(_token(), _tool(None)))
        self.assertFalse(self._allowed(_token(_OTHER_EMAIL), _tool(None)))

    def test_empty_allowlist_blocks_every_write_tool(self):
        check = mw_escritura.WriteAccessCheck(frozenset())
        ctx = AuthContext(token=_token(), component=_tool(False))
        self.assertFalse(check(ctx))

    def test_non_tool_components_are_allowed(self):
        self.assertTrue(self._allowed(None, MagicMock(spec=[])))


class WriteAllowlistIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """End to end through FastMCP with the write tools configuration."""

    def setUp(self):
        # initialize_and_mount_tools removes disabled tools from the shared
        # module-level sub-servers. Restore them so other tests are unaffected.
        for sub_server in (assets_mcp, labels_mcp):
            components = sub_server.local_provider._components
            snapshot = dict(components)
            self.addCleanup(_restore, components, snapshot)

        env = {
            "GOOGLE_ADS_MCP_TOOLS_CONFIG": str(_WRITE_CONFIG),
            "GOOGLE_ADS_MCP_WRITE_ALLOWED_EMAILS": _ALLOWED_EMAIL,
        }
        with patch.dict(os.environ, env):
            self.server = FastMCP("write-allowlist-test")
            initialize_and_mount_tools(self.server)
            self.server.add_middleware(
                mw_escritura.create_write_access_middleware()
            )

    async def _list_tool_names(self, token):
        with patch(_TOKEN_TARGET, return_value=token):
            async with Client(self.server) as client:
                return sorted(t.name for t in await client.list_tools())

    async def test_allowlisted_user_sees_read_and_write_tools(self):
        names = await self._list_tool_names(_token())
        self.assertEqual(names, sorted(_READ_TOOLS + _WRITE_TOOLS))

    async def test_other_user_sees_only_read_tools(self):
        names = await self._list_tool_names(_token(_OTHER_EMAIL))
        self.assertEqual(names, _READ_TOOLS)

    async def test_upload_video_is_never_exposed(self):
        names = await self._list_tool_names(_token())
        self.assertNotIn("assets_upload_video_asset", names)

    async def test_other_user_cannot_call_write_tool(self):
        with patch(_TOKEN_TARGET, return_value=_token(_OTHER_EMAIL)):
            with patch("ads_mcp.utils.get_googleads_client") as get_client:
                async with Client(self.server) as client:
                    with self.assertRaisesRegex(
                        Exception, "Authorization failed"
                    ):
                        await client.call_tool(
                            "labels_manage_labels",
                            {"customer_id": "123", "operation": "CREATE"},
                        )
        get_client.assert_not_called()

    async def test_allowlisted_user_reaches_write_tool(self):
        with patch(_TOKEN_TARGET, return_value=_token()):
            with patch(
                "ads_mcp.utils.get_googleads_client",
                side_effect=RuntimeError("tool reached"),
            ) as get_client:
                async with Client(self.server) as client:
                    with self.assertRaisesRegex(Exception, "tool reached"):
                        await client.call_tool(
                            "labels_manage_labels",
                            {
                                "customer_id": "123",
                                "operation": "CREATE",
                                "name": "Prueba",
                            },
                        )
        get_client.assert_called_once()


class InstallWriteAccessMiddlewareTest(unittest.TestCase):
    _OAUTH_ENV = {
        "GOOGLE_ADS_MCP_OAUTH_CLIENT_ID": "test-client-id",
        "GOOGLE_ADS_MCP_OAUTH_CLIENT_SECRET": "test-client-secret",
    }

    def _write_middlewares(self, server):
        return [
            mw
            for mw in server.middleware
            if isinstance(mw, AuthMiddleware)
            and isinstance(mw.auth, mw_escritura.WriteAccessCheck)
        ]

    def test_installs_in_remote_oauth_mode(self):
        server = FastMCP("remote")
        with patch.dict(os.environ, self._OAUTH_ENV, clear=True):
            self.assertTrue(
                mw_escritura.install_write_access_middleware(server)
            )
        self.assertEqual(len(self._write_middlewares(server)), 1)

    def test_skips_in_local_mode(self):
        server = FastMCP("local")
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(
                mw_escritura.install_write_access_middleware(server)
            )
        self.assertEqual(self._write_middlewares(server), [])

    def test_coordinator_installs_allowlist_in_remote_mode(self):
        import ads_mcp.coordinator as coord

        env = {
            **self._OAUTH_ENV,
            "GOOGLE_ADS_MCP_JWT_SIGNING_KEY": "test-signing-key",
            "GOOGLE_ADS_MCP_STORAGE_TYPE": "memory",
        }
        # Cleanups run last in, first out: restore env, then reload.
        self.addCleanup(lambda: importlib.reload(coord))
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        importlib.reload(coord)

        self.assertEqual(len(self._write_middlewares(coord.mcp)), 1)


if __name__ == "__main__":
    unittest.main()
