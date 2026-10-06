"""Encrypted Web Session & Credential Injection Vault Service (AURA-1003).

Provides:
1. AES-256-GCM encrypted credential vault for web authentication.
2. Encrypted browser session and storage state persistence.
3. Strict workspace isolation and domain/origin binding.
4. Phishing and lookalike domain defenses.
5. Playwright-native credential injection boundary (zero plaintext model exposure).
6. Atomically verifiable key rotation and tamper detection.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.core.logging import logger
from app.core.security import compute_sha256_hash, generate_key_fingerprint
from app.db.models.web_vault import WebCredential, WebSessionState
from app.services.browser.engine import browser_engine
from app.services.browser.governance import freshness_store


def derive_vault_key(master_key: Optional[str] = None, workspace_id: Optional[uuid.UUID] = None) -> bytes:
    """Derive a 32-byte AES-256 key from master key with optional workspace scoping."""
    raw = master_key or settings.AURA_MASTER_ENCRYPTION_KEY
    if workspace_id:
        seed = f"{raw}:{str(workspace_id)}"
    else:
        seed = raw
    return hashlib.sha256(seed.encode("utf-8")).digest()


def encrypt_field(
    plaintext: str,
    master_key: Optional[str] = None,
    workspace_id: Optional[uuid.UUID] = None,
) -> str:
    """Encrypt a secret string using AES-256-GCM with 96-bit random nonce."""
    if not isinstance(plaintext, str):
        raise ValidationError("Plaintext to encrypt must be a string")

    key = derive_vault_key(master_key, workspace_id)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96-bit nonce
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    payload = nonce + ciphertext
    return base64.b64encode(payload).decode("ascii")


def decrypt_field(
    encrypted_b64: str,
    master_key: Optional[str] = None,
    workspace_id: Optional[uuid.UUID] = None,
) -> str:
    """Decrypt AES-256-GCM ciphertext and verify authentication tag."""
    try:
        key = derive_vault_key(master_key, workspace_id)
        aesgcm = AESGCM(key)
        payload = base64.b64decode(encrypted_b64.encode("ascii"))
        if len(payload) < 28:  # 12-byte nonce + 16-byte tag minimum
            raise ValidationError("Ciphertext payload is truncated or corrupted")
        nonce = payload[:12]
        ciphertext = payload[12:]
        decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted_bytes.decode("utf-8")
    except Exception as e:
        logger.warning(f"WebVault: Decryption/tamper verification failure: {e}")
        raise ValidationError("Ciphertext tampering or integrity verification failure") from e


def generate_username_hint(username: str) -> str:
    """Generate privacy-preserving masked identifier for UI/metadata display."""
    if not username:
        return "anonymous"
    if "@" in username:
        parts = username.split("@", 1)
        user_part, domain_part = parts[0], parts[1]
        if len(user_part) <= 2:
            masked_user = user_part + "***"
        else:
            masked_user = user_part[:2] + "***"
        return f"{masked_user}@{domain_part}"
    else:
        if len(username) <= 2:
            return username + "***"
        return username[:2] + "***"


def normalize_origin(url_or_origin: str) -> str:
    """Normalize URL or origin string to canonical 'scheme://hostname[:port]' format."""
    if not url_or_origin or not isinstance(url_or_origin, str):
        raise ValidationError("Origin must be a non-empty string")

    target = url_or_origin.strip()
    if "://" not in target:
        target = f"https://{target}"

    parsed = urlparse(target)
    scheme = (parsed.scheme or "https").lower()
    if scheme not in ["http", "https"]:
        raise ValidationError(f"Prohibited origin scheme '{scheme}'. Only http and https are permitted.")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValidationError(f"Invalid origin missing valid hostname: '{url_or_origin}'")

    port = parsed.port
    if port and ((scheme == "https" and port != 443) or (scheme == "http" and port != 80)):
        return f"{scheme}://{hostname}:{port}"
    return f"{scheme}://{hostname}"


def extract_domain(url_or_origin: str) -> str:
    """Extract lowercase hostname/domain from URL or origin."""
    normalized = normalize_origin(url_or_origin)
    parsed = urlparse(normalized)
    return (parsed.hostname or "").lower()


def validate_origin_match(
    credential_origin: str,
    target_url: str,
    allow_subdomains: bool = False,
) -> bool:
    """Strictly validate whether a target URL matches the credential's bound origin.
    
    Prevents phishing, lookalike domains, and cross-origin credential injection.
    """
    try:
        cred_norm = normalize_origin(credential_origin)
        target_norm = normalize_origin(target_url)

        cred_parsed = urlparse(cred_norm)
        target_parsed = urlparse(target_norm)

        # 1. Scheme must match
        if cred_parsed.scheme != target_parsed.scheme:
            return False

        # 2. Port must match
        if cred_parsed.port != target_parsed.port:
            return False

        cred_host = cred_parsed.hostname or ""
        target_host = target_parsed.hostname or ""

        # 3. Hostname check
        if cred_host == target_host:
            return True

        # 4. Subdomain check (only if explicitly enabled on credential)
        if allow_subdomains:
            if target_host.endswith(f".{cred_host}"):
                return True

        return False
    except Exception:
        return False


class WebVaultService:
    """Encrypted Web Credential & Browser Session Management Boundary."""

    def __init__(self):
        pass

    async def create_credential(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        name: str,
        target_origin: str,
        username: str,
        password: str,
        extra_secrets: Optional[Dict[str, Any]] = None,
        allow_subdomains: bool = False,
        master_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Encrypt and store a web credential in the vault. Returns metadata only."""
        if not name or not name.strip():
            raise ValidationError("Credential name cannot be empty")
        if not username or not username.strip():
            raise ValidationError("Username cannot be empty")
        if not password:
            raise ValidationError("Password cannot be empty")

        norm_origin = normalize_origin(target_origin)
        domain = extract_domain(norm_origin)

        # Check duplicate
        stmt = select(WebCredential).where(
            WebCredential.workspace_id == workspace_id,
            WebCredential.target_origin == norm_origin,
            WebCredential.name == name.strip(),
            WebCredential.is_active == True,
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing:
            raise ValidationError(
                f"Active credential with name '{name}' already exists for origin '{norm_origin}'"
            )

        # Encrypt secrets with workspace-bound AES-256-GCM
        username_enc = encrypt_field(username, master_key=master_key, workspace_id=workspace_id)
        password_enc = encrypt_field(password, master_key=master_key, workspace_id=workspace_id)
        extra_enc = None
        if extra_secrets:
            extra_json = json.dumps(extra_secrets, sort_keys=True)
            extra_enc = encrypt_field(extra_json, master_key=master_key, workspace_id=workspace_id)

        hint = generate_username_hint(username)
        fingerprint = generate_key_fingerprint(password)

        cred = WebCredential(
            workspace_id=workspace_id,
            name=name.strip(),
            target_domain=domain,
            target_origin=norm_origin,
            allow_subdomains=allow_subdomains,
            username_ciphertext=username_enc,
            password_ciphertext=password_enc,
            extra_secrets_ciphertext=extra_enc,
            username_hint=hint,
            key_fingerprint=fingerprint,
            is_active=True,
            version=1,
        )
        db.add(cred)
        await db.commit()
        await db.refresh(cred)

        logger.info(
            f"WebVault: Created encrypted credential {cred.id} ('{cred.name}') bound to '{norm_origin}' for Workspace {workspace_id}"
        )

        return self._to_metadata_dict(cred)

    async def list_credentials(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        target_origin: Optional[str] = None,
        include_revoked: bool = False,
    ) -> List[Dict[str, Any]]:
        """List metadata for active credentials available to workspace. NEVER exposes secrets."""
        stmt = select(WebCredential).where(
            WebCredential.workspace_id == workspace_id,
        )
        if not include_revoked:
            stmt = stmt.where(WebCredential.is_active == True)

        if target_origin:
            norm_origin = normalize_origin(target_origin)
            stmt = stmt.where(WebCredential.target_origin == norm_origin)

        stmt = stmt.order_by(WebCredential.created_at.desc())
        results = (await db.execute(stmt)).scalars().all()
        return [self._to_metadata_dict(c) for c in results]

    async def get_credential_metadata(
        self,
        db: AsyncSession,
        credential_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> Dict[str, Any]:
        """Fetch credential metadata with strict workspace validation."""
        cred = await self._get_credential_entity(db, credential_id, workspace_id)
        return self._to_metadata_dict(cred)

    async def revoke_credential(
        self,
        db: AsyncSession,
        credential_id: uuid.UUID,
        workspace_id: uuid.UUID,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Revoke a credential immediately."""
        cred = await self._get_credential_entity(db, credential_id, workspace_id)
        cred.is_active = False
        cred.revoked_at = datetime.now(timezone.utc)
        cred.revoked_reason = reason or "Revoked by operator"
        await db.commit()
        await db.refresh(cred)
        logger.info(f"WebVault: Revoked credential {cred.id} for Workspace {workspace_id}")
        return self._to_metadata_dict(cred)

    async def delete_credential(
        self,
        db: AsyncSession,
        credential_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> bool:
        """Permanently delete a credential record."""
        cred = await self._get_credential_entity(db, credential_id, workspace_id)
        await db.delete(cred)
        await db.commit()
        logger.info(f"WebVault: Deleted credential {credential_id} for Workspace {workspace_id}")
        return True

    async def rotate_encryption_key(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        old_master_key: str,
        new_master_key: str,
    ) -> Dict[str, Any]:
        """Atomically re-encrypt stored credentials in workspace under new master key."""
        from datetime import datetime, timezone
        stmt = select(WebCredential).where(
            WebCredential.workspace_id == workspace_id,
            WebCredential.is_active == True,
        )
        creds = (await db.execute(stmt)).scalars().all()
        rotated_count = 0

        for c in creds:
            # 1. Decrypt with old key
            user_plain = decrypt_field(c.username_ciphertext, master_key=old_master_key, workspace_id=workspace_id)
            pass_plain = decrypt_field(c.password_ciphertext, master_key=old_master_key, workspace_id=workspace_id)
            extra_plain = None
            if c.extra_secrets_ciphertext:
                extra_plain = decrypt_field(c.extra_secrets_ciphertext, master_key=old_master_key, workspace_id=workspace_id)

            # 2. Re-encrypt with new key
            c.username_ciphertext = encrypt_field(user_plain, master_key=new_master_key, workspace_id=workspace_id)
            c.password_ciphertext = encrypt_field(pass_plain, master_key=new_master_key, workspace_id=workspace_id)
            if extra_plain:
                c.extra_secrets_ciphertext = encrypt_field(extra_plain, master_key=new_master_key, workspace_id=workspace_id)

            c.version += 1
            c.key_fingerprint = generate_key_fingerprint(pass_plain)
            rotated_count += 1

        await db.commit()
        logger.info(f"WebVault: Successfully rotated {rotated_count} credentials for Workspace {workspace_id}")
        return {
            "status": "success",
            "workspace_id": str(workspace_id),
            "credentials_rotated": rotated_count,
        }

    rotate_credentials_key = rotate_encryption_key

    async def save_session_state(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        target_origin: str,
        session_name: str,
        storage_state: Dict[str, Any],
        ttl_seconds: Optional[int] = None,
        expires_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Encrypt and store browser storage state (cookies + localStorage)."""
        from datetime import timedelta
        norm_origin = normalize_origin(target_origin)
        domain = extract_domain(norm_origin)
        state_json = json.dumps(storage_state, sort_keys=True)
        encrypted_state = encrypt_field(state_json, workspace_id=workspace_id)
        fingerprint = compute_sha256_hash(state_json)[:12]

        if ttl_seconds is not None and expires_at is None:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

        stmt = select(WebSessionState).where(
            WebSessionState.workspace_id == workspace_id,
            WebSessionState.target_origin == norm_origin,
            WebSessionState.session_name == session_name,
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()

        now = datetime.now(timezone.utc)
        if existing:
            existing.encrypted_storage_state = encrypted_state
            existing.key_fingerprint = fingerprint
            existing.is_active = True
            existing.expires_at = expires_at
            existing.last_used_at = now
            existing.revoked_at = None
            session_rec = existing
        else:
            session_rec = WebSessionState(
                workspace_id=workspace_id,
                session_name=session_name,
                target_domain=domain,
                target_origin=norm_origin,
                encrypted_storage_state=encrypted_state,
                key_fingerprint=fingerprint,
                is_active=True,
                expires_at=expires_at,
                last_used_at=now,
            )
            db.add(session_rec)

        await db.commit()
        await db.refresh(session_rec)
        logger.info(f"WebVault: Saved encrypted session '{session_name}' for origin '{norm_origin}'")

        return {
            "session_id": str(session_rec.id),
            "workspace_id": str(workspace_id),
            "session_name": session_name,
            "target_origin": norm_origin,
            "target_domain": domain,
            "is_active": session_rec.is_active,
            "created_at": session_rec.created_at.isoformat() if session_rec.created_at else None,
        }

    async def get_session_state(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        target_origin: str,
        session_name: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """Retrieve and decrypt stored browser storage state internally."""
        norm_origin = normalize_origin(target_origin)
        stmt = select(WebSessionState).where(
            WebSessionState.workspace_id == workspace_id,
            WebSessionState.target_origin == norm_origin,
            WebSessionState.session_name == session_name,
            WebSessionState.is_active == True,
        )
        session_rec = (await db.execute(stmt)).scalar_one_or_none()
        if not session_rec:
            return None

        # Expiry check
        if session_rec.expires_at:
            now = datetime.now(timezone.utc)
            exp = session_rec.expires_at if session_rec.expires_at.tzinfo else session_rec.expires_at.replace(tzinfo=timezone.utc)
            if exp < now:
                session_rec.is_active = False
                session_rec.revoked_at = now
                await db.commit()
                return None

        state_json = decrypt_field(session_rec.encrypted_storage_state, workspace_id=workspace_id)
        session_rec.last_used_at = datetime.now(timezone.utc)
        await db.commit()
        return json.loads(state_json)

    async def revoke_session_state(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> bool:
        """Revoke a stored browser session."""
        stmt = select(WebSessionState).where(
            WebSessionState.id == session_id,
            WebSessionState.workspace_id == workspace_id,
        )
        session_rec = (await db.execute(stmt)).scalar_one_or_none()
        if not session_rec:
            raise EntityNotFoundError("WebSessionState", str(session_id))

        session_rec.is_active = False
        session_rec.revoked_at = datetime.now(timezone.utc)
        await db.commit()
        return True

    # --------------------------------------------------------------------------
    # Secure Injection Execution Boundary
    # --------------------------------------------------------------------------

    async def inject_credential_into_tab(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        credential_id: uuid.UUID,
        tab_id: Optional[str] = None,
        username_element_id: Optional[int] = None,
        password_element_id: Optional[int] = None,
        submit_form: bool = False,
    ) -> Dict[str, Any]:
        """Securely inject credential into targeted webpage input fields without model disclosure."""
        from app.services.kill_switch import kill_switch
        if kill_switch.is_active(workspace_id):
            raise AuthorizationError(f"Emergency Kill Switch is active for workspace {workspace_id}.")

        # 1. Fetch credential with workspace validation
        cred = await self._get_credential_entity(db, credential_id, workspace_id)
        if not cred.is_active or cred.revoked_at:
            raise AuthorizationError(f"Credential '{cred.name}' is revoked or deactivated")

        # 2. Acquire active Playwright context and page
        ws_ctx = await browser_engine.get_or_create_workspace_context(workspace_id)
        target_tab_id = tab_id or ws_ctx.active_tab_id
        if not target_tab_id:
            raise ValidationError("No active tab open in workspace browser context")

        page = ws_ctx.get_page(target_tab_id)
        current_page_url = page.url or "about:blank"

        # 3. Phishing / Origin Mismatch Guard
        is_origin_valid = validate_origin_match(
            credential_origin=cred.target_origin,
            target_url=current_page_url,
            allow_subdomains=cred.allow_subdomains,
        )
        if not is_origin_valid:
            logger.warning(
                f"WebVault: Phishing/Origin mismatch! Credential '{cred.name}' bound to '{cred.target_origin}' "
                f"cannot be injected into page '{current_page_url}'"
            )
            raise AuthorizationError(
                f"Phishing/Origin mismatch: Credential bound to '{cred.target_origin}' "
                f"cannot be injected into active page origin '{current_page_url}'"
            )

        # 4. Decrypt secrets inside transient execution boundary
        plain_user = decrypt_field(cred.username_ciphertext, workspace_id=workspace_id)
        plain_pass = decrypt_field(cred.password_ciphertext, workspace_id=workspace_id)

        try:
            # 5. Inject username into target field
            if username_element_id is not None:
                user_node = freshness_store.get_element(workspace_id, target_tab_id, username_element_id)
                if user_node.bounding_box:
                    cx = user_node.bounding_box["x"] + user_node.bounding_box["width"] / 2.0
                    cy = user_node.bounding_box["y"] + user_node.bounding_box["height"] / 2.0
                    await page.mouse.click(cx, cy)
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")
                    await page.keyboard.type(plain_user)
                else:
                    await page.locator('input[type="text"], input[type="email"], input[autocomplete*="user"], input[name*="user"]').first.fill(plain_user)
            else:
                user_loc = page.locator(
                    'input[type="text"], input[type="email"], input[autocomplete*="user"], input[autocomplete*="email"], input[name*="user"], input[name*="login"], input[id*="user"], input[id*="login"]'
                ).first
                await user_loc.fill(plain_user)

            # 6. Inject password into target field
            if password_element_id is not None:
                pass_node = freshness_store.get_element(workspace_id, target_tab_id, password_element_id)
                if pass_node.bounding_box:
                    cx = pass_node.bounding_box["x"] + pass_node.bounding_box["width"] / 2.0
                    cy = pass_node.bounding_box["y"] + pass_node.bounding_box["height"] / 2.0
                    await page.mouse.click(cx, cy)
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")
                    await page.keyboard.type(plain_pass)
                else:
                    await page.locator('input[type="password"], input[autocomplete*="pass"], input[name*="pass"], input[id*="pass"]').first.fill(plain_pass)
            else:
                pass_loc = page.locator(
                    'input[type="password"], input[autocomplete*="password"], input[name*="pass"], input[id*="pass"]'
                ).first
                await pass_loc.fill(plain_pass)

            # 7. Optional Form Submission
            if submit_form:
                submit_loc = page.locator('button[type="submit"], input[type="submit"], button:has-text("Sign in"), button:has-text("Log in"), button:has-text("Login")').first
                try:
                    await submit_loc.click(timeout=3000)
                except Exception:
                    await page.keyboard.press("Enter")

            # Update last used timestamp
            cred.last_used_at = datetime.now(timezone.utc)
            await db.commit()

            logger.info(
                f"WebVault: Successfully injected credential {cred.id} into tab {target_tab_id} for '{cred.target_origin}'"
            )

            # Return metadata response — ZERO PLAINTEXT SECRETS
            return {
                "status": "success",
                "action": "credential_injected",
                "credential_id": str(cred.id),
                "name": cred.name,
                "target_origin": cred.target_origin,
                "username_hint": cred.username_hint,
                "tab_id": target_tab_id,
                "is_untrusted_content": True,
            }

        finally:
            # Immediate transient memory cleanup
            del plain_user
            del plain_pass

    async def _get_credential_entity(
        self,
        db: AsyncSession,
        credential_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> WebCredential:
        """Fetch credential verifying workspace tenancy."""
        stmt = select(WebCredential).where(
            WebCredential.id == credential_id,
            WebCredential.workspace_id == workspace_id,
        )
        cred = (await db.execute(stmt)).scalar_one_or_none()
        if not cred:
            raise EntityNotFoundError("WebCredential", str(credential_id))
        return cred

    def _to_metadata_dict(self, c: WebCredential) -> Dict[str, Any]:
        """Serialize WebCredential metadata WITHOUT plaintext secrets or ciphertexts."""
        return {
            "id": str(c.id),
            "workspace_id": str(c.workspace_id),
            "name": c.name,
            "target_domain": c.target_domain,
            "target_origin": c.target_origin,
            "allow_subdomains": c.allow_subdomains,
            "username_hint": c.username_hint,
            "key_fingerprint": c.key_fingerprint,
            "is_active": c.is_active,
            "version": c.version,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            "last_used_at": c.last_used_at.isoformat() if c.last_used_at else None,
            "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None,
            "revoked_reason": c.revoked_reason,
        }


web_vault_service = WebVaultService()
