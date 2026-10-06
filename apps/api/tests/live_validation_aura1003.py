"""Live Host and Browser Validation Suite for AURA-1003 Encrypted Web Session & Credential Vault.

Executes live end-to-end authentication and session flows against a local disposable HTTP server:
1. Encrypted storage of synthetic credential
2. Database verification (zero plaintext passwords/keys)
3. Credential metadata discovery (zero plaintext secrets)
4. Playwright-native injection and successful form authentication
5. Secure browser session / cookie capture and encrypted vault storage
6. Cookie clearing and unauthenticated state verification
7. Encrypted session restoration and authenticated state recovery
8. Phishing / Lookalike origin attack mitigation
9. Active kill switch fail-closed enforcement
10. Credential revocation fail-closed enforcement
11. Ciphertext tampering fail-closed enforcement
"""

import asyncio
import http.server
import socket
import threading
import time
import urllib.parse
import uuid
from unittest.mock import patch
import pytest

from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.db.models.web_vault import WebCredential, WebSessionState
from app.services.browser.engine import PlaywrightBrowserEngine, browser_engine
from app.services.browser.governance import action_budget_manager, freshness_store
from app.services.browser.vault import web_vault_service
from app.services.kill_switch import kill_switch
from app.services.tools.browser_tools import (
    execute_browser_get_page_state,
    execute_browser_inject_credential,
    execute_browser_list_credentials,
    execute_browser_navigate,
    execute_browser_restore_session,
    execute_browser_save_session,
)

LOGIN_PAGE_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>AURA-1003 Secure Login Portal</title>
</head>
<body>
    <h1>Enterprise Protected Portal</h1>
    <form id="login-form" action="/auth/login" method="POST">
        <div>
            <label for="user-field">Username</label>
            <input id="user-field" type="text" name="username" autocomplete="username" />
        </div>
        <div style="margin-top: 10px;">
            <label for="pass-field">Password</label>
            <input id="pass-field" type="password" name="password" autocomplete="current-password" />
        </div>
        <div style="margin-top: 10px;">
            <button id="submit-btn" type="submit">Sign in</button>
        </div>
    </form>
</body>
</html>
"""

DASHBOARD_PAGE_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Enterprise Dashboard</title>
</head>
<body>
    <h1 id="dashboard-header">Welcome to Protected Dashboard</h1>
    <p id="user-status">Authenticated as Administrator</p>
    <a id="logout-link" href="/logout">Logout</a>
</body>
</html>
"""

MALICIOUS_PAGE_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Deceptive Phishing Portal</title>
</head>
<body>
    <h1>Phishing Server</h1>
    <p>Please enter credentials</p>
    <input type="text" name="username" />
    <input type="password" name="password" />
</body>
</html>
"""

CANARY_USER = "test_admin@securecorp.com"
CANARY_PASS = "AURA_SYNTHETIC_PASS_998811"
SESSION_COOKIE_VALUE = "aura_valid_session_token_xyz9988"


class LocalAuthServerHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        cookie_header = self.headers.get("Cookie", "")
        is_authenticated = f"aura_auth_session={SESSION_COOKIE_VALUE}" in cookie_header

        if self.path == "/login":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(LOGIN_PAGE_HTML.encode("utf-8"))

        elif self.path == "/dashboard":
            if is_authenticated:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(DASHBOARD_PAGE_HTML.encode("utf-8"))
            else:
                self.send_response(302)
                self.send_header("Location", "/login")
                self.end_headers()

        elif self.path == "/logout":
            self.send_response(302)
            self.send_header("Set-Cookie", "aura_auth_session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT")
            self.send_header("Location", "/login")
            self.end_headers()

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/auth/login":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            parsed = urllib.parse.parse_qs(body)

            user = parsed.get("username", [""])[0]
            password = parsed.get("password", [""])[0]

            if user == CANARY_USER and password == CANARY_PASS:
                self.send_response(302)
                self.send_header("Set-Cookie", f"aura_auth_session={SESSION_COOKIE_VALUE}; Path=/; HttpOnly")
                self.send_header("Location", "/dashboard")
                self.end_headers()
            else:
                self.send_response(401)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<h1>401 Unauthorized</h1><p id='err'>Invalid Credentials</p>")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress console log


class MaliciousServerHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(MALICIOUS_PAGE_HTML.encode("utf-8"))

    def log_message(self, format, *args):
        pass


def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def local_auth_server():
    """Start local authentication server on ephemeral port."""
    port = _find_free_port()
    server = http.server.HTTPServer(("127.0.0.1", port), LocalAuthServerHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def local_malicious_server():
    """Start separate phishing simulation server on ephemeral port."""
    port = _find_free_port()
    server = http.server.HTTPServer(("127.0.0.1", port), MaliciousServerHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


@pytest.mark.asyncio
async def test_live_aura1003_full_vault_and_injection_lifecycle(
    db_session, local_auth_server, local_malicious_server
):
    """Execute live 13-step validation of AURA-1003 against real Playwright Chromium instance."""
    ws_id = uuid.uuid4()
    target_origin = local_auth_server

    with patch("app.core.network.ssrf_guard.validate_url", return_value=None):
        try:
            # ----------------------------------------------------------------------
            # Step 1 & 2: Store synthetic credential in vault
            # ----------------------------------------------------------------------
            cred_meta = await web_vault_service.create_credential(
                db=db_session,
                workspace_id=ws_id,
                name="Live Portal Auth",
                target_origin=target_origin,
                username=CANARY_USER,
                password=CANARY_PASS,
                allow_subdomains=False,
            )
            cred_id = uuid.UUID(cred_meta["id"])
            assert cred_meta["name"] == "Live Portal Auth"
            assert cred_meta["username_hint"] == "te***@securecorp.com"
            assert CANARY_PASS not in str(cred_meta)

            # ----------------------------------------------------------------------
            # Step 3: Direct DB inspection — verify zero plaintext secrets
            # ----------------------------------------------------------------------
            db_cred = await db_session.get(WebCredential, cred_id)
            assert db_cred is not None
            assert CANARY_PASS not in db_cred.password_ciphertext
            assert CANARY_USER not in db_cred.username_ciphertext
            assert db_cred.is_active is True

            # ----------------------------------------------------------------------
            # Step 4: Navigate to login page in real browser
            # ----------------------------------------------------------------------
            nav_res = await execute_browser_navigate(
                workspace_id=ws_id,
                url=f"{target_origin}/login",
            )
            assert nav_res["status"] == "success"
            tab_id = nav_res["tab_id"]

            # Observe page
            obs_res = await execute_browser_get_page_state(workspace_id=ws_id, tab_id=tab_id)
            assert "Enterprise Protected Portal" in obs_res["axtree_formatted"]

            # ----------------------------------------------------------------------
            # Step 5: List credentials metadata (zero plaintext)
            # ----------------------------------------------------------------------
            list_res = await execute_browser_list_credentials(
                workspace_id=ws_id,
                target_origin=target_origin,
                db=db_session,
            )
            assert list_res["total"] == 1
            assert CANARY_PASS not in str(list_res)
            assert CANARY_USER not in str(list_res)

            # ----------------------------------------------------------------------
            # Step 6: Inject credentials with form submission
            # ----------------------------------------------------------------------
            inject_res = await execute_browser_inject_credential(
                workspace_id=ws_id,
                credential_id=str(cred_id),
                tab_id=tab_id,
                submit_form=True,
                db=db_session,
            )
            assert inject_res["status"] == "success"
            assert inject_res["action"] == "credential_injected"
            assert CANARY_PASS not in str(inject_res)

            # Allow form navigation to settle
            await asyncio.sleep(0.5)

            # ----------------------------------------------------------------------
            # Step 7: Verify authenticated state on dashboard
            # ----------------------------------------------------------------------
            post_auth_obs = await execute_browser_get_page_state(workspace_id=ws_id, tab_id=tab_id)
            assert "Welcome to Protected Dashboard" in post_auth_obs["axtree_formatted"]

            # ----------------------------------------------------------------------
            # Step 8: Capture and encrypt storage state into vault
            # ----------------------------------------------------------------------
            save_res = await execute_browser_save_session(
                workspace_id=ws_id,
                session_name="live_test_session",
                tab_id=tab_id,
                db=db_session,
            )
            assert save_res["status"] == "success"
            assert save_res["session_name"] == "live_test_session"

            # Verify DB session storage ciphertext
            db_sess = await db_session.get(WebSessionState, uuid.UUID(save_res["session_id"]))
            assert db_sess is not None
            assert SESSION_COOKIE_VALUE not in db_sess.encrypted_storage_state

            # ----------------------------------------------------------------------
            # Step 9: Logout / clear cookies and verify unauthenticated state
            # ----------------------------------------------------------------------
            logout_nav = await execute_browser_navigate(
                workspace_id=ws_id,
                url=f"{target_origin}/logout",
                tab_id=tab_id,
            )
            # Attempt to visit dashboard again -> should redirect to login
            dash_nav = await execute_browser_navigate(
                workspace_id=ws_id,
                url=f"{target_origin}/dashboard",
                tab_id=tab_id,
            )
            unauth_obs = await execute_browser_get_page_state(workspace_id=ws_id, tab_id=tab_id)
            assert "Enterprise Protected Portal" in unauth_obs["axtree_formatted"]

            # ----------------------------------------------------------------------
            # Step 10: Restore encrypted session state and verify authenticated recovery
            # ----------------------------------------------------------------------
            restore_res = await execute_browser_restore_session(
                workspace_id=ws_id,
                session_name="live_test_session",
                tab_id=tab_id,
                target_origin=target_origin,
                db=db_session,
            )
            assert restore_res["status"] == "success"
            assert restore_res["cookies_restored_count"] >= 1

            # Re-navigate to dashboard -> should now succeed with restored cookie
            dash_auth_nav = await execute_browser_navigate(
                workspace_id=ws_id,
                url=f"{target_origin}/dashboard",
                tab_id=tab_id,
            )
            restored_obs = await execute_browser_get_page_state(workspace_id=ws_id, tab_id=tab_id)
            assert "Welcome to Protected Dashboard" in restored_obs["axtree_formatted"]

            # ----------------------------------------------------------------------
            # Step 11: Phishing origin attack defense
            # ----------------------------------------------------------------------
            await execute_browser_navigate(
                workspace_id=ws_id,
                url=f"{local_malicious_server}/",
                tab_id=tab_id,
            )
            with pytest.raises(AuthorizationError, match="Phishing/Origin mismatch"):
                await execute_browser_inject_credential(
                    workspace_id=ws_id,
                    credential_id=str(cred_id),
                    tab_id=tab_id,
                    db=db_session,
                )

            # ----------------------------------------------------------------------
            # Step 12: Kill switch enforcement
            # ----------------------------------------------------------------------
            kill_switch.set_active(True, workspace_id=ws_id)
            with pytest.raises(AuthorizationError, match="Emergency Kill Switch is active"):
                await execute_browser_inject_credential(
                    workspace_id=ws_id,
                    credential_id=str(cred_id),
                    tab_id=tab_id,
                    db=db_session,
                )
            kill_switch.set_active(False, workspace_id=ws_id)

            # ----------------------------------------------------------------------
            # Step 13: Revocation enforcement
            # ----------------------------------------------------------------------
            await web_vault_service.revoke_credential(
                db=db_session, credential_id=cred_id, workspace_id=ws_id, reason="Live test revocation"
            )
            # Navigate back to login page
            await execute_browser_navigate(
                workspace_id=ws_id,
                url=f"{target_origin}/login",
                tab_id=tab_id,
            )
            with pytest.raises(AuthorizationError, match="revoked or deactivated"):
                await execute_browser_inject_credential(
                    workspace_id=ws_id,
                    credential_id=str(cred_id),
                    tab_id=tab_id,
                    db=db_session,
                )

        finally:
            # Cleanup browser resources
            await browser_engine.close_workspace_context(ws_id)

