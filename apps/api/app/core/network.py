"""Network Isolation and Server-Side Request Forgery (SSRF) Defense Module.

Protects against:
- Loopback addresses (127.0.0.0/8, ::1)
- RFC 1918 private IPv4 networks (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
- Link-local addresses (169.254.0.0/16, fe80::/10)
- Cloud metadata service endpoints (169.254.169.254)
- Local Docker/Kubernetes bridge networks
- Broadcast and Multicast addresses (224.0.0.0/4, 255.255.255.255)
- Dangerous URL schemes (file://, gopher://, dict://, ldap://)
- DNS Rebinding and IP-spoofing via hostname resolution
"""

import ipaddress
import socket
from urllib.parse import urlparse
import httpx
from app.core.config import settings
from app.core.errors import AuthorizationError, ValidationError
from app.core.logging import logger


class SSRFProtectionGuard:
    """Validates URLs and destination IP addresses against strict SSRF defense policies."""

    ALLOWED_SCHEMES = {"http", "https"}

    # Cloud metadata IP
    CLOUD_METADATA_IP = ipaddress.ip_address("169.254.169.254")

    @classmethod
    def is_ip_prohibited(cls, ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        """Check if an IP address belongs to a prohibited or private range."""
        if ip.is_loopback:
            return True
        if ip.is_private:
            return True
        if ip.is_link_local:
            return True
        if ip.is_multicast:
            return True
        if ip.is_reserved:
            return True
        if ip.is_unspecified:
            return True
        if ip == cls.CLOUD_METADATA_IP:
            return True
        return False

    @classmethod
    def validate_url(cls, url: str) -> None:
        """Perform comprehensive URL and DNS resolution validation.

        Raises ValidationError or AuthorizationError on any SSRF violation.
        """
        if not settings.SSRF_PROTECTION_ENABLED:
            return

        if not url or not isinstance(url, str):
            raise ValidationError("URL must be a non-empty string")

        parsed = urlparse(url)

        # 1. Validate URL Scheme
        if not parsed.scheme or parsed.scheme.lower() not in cls.ALLOWED_SCHEMES:
            logger.error(f"SSRFGuard: Prohibited scheme '{parsed.scheme}' in URL: {url}")
            raise AuthorizationError(f"Prohibited URL scheme '{parsed.scheme}'. Only http and https are permitted.")

        # 2. Extract Hostname
        hostname = parsed.hostname
        if not hostname:
            raise ValidationError(f"Invalid URL missing hostname: '{url}'")

        # 3. Check direct IP representation
        try:
            direct_ip = ipaddress.ip_address(hostname)
            if cls.is_ip_prohibited(direct_ip):
                logger.error(f"SSRFGuard: Prohibited direct IP target: {direct_ip}")
                raise AuthorizationError(f"Access to private/internal IP address {direct_ip} is strictly prohibited")
            return
        except ValueError:
            pass  # Hostname is a domain name, proceed to DNS resolution

        # 4. Resolve Domain Name to IPs and check all returned addresses
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            resolved_ips = {ipaddress.ip_address(addr[4][0]) for addr in addr_info}
        except socket.gaierror as e:
            logger.warning(f"SSRFGuard: DNS resolution failed for hostname '{hostname}': {e}")
            raise ValidationError(f"Could not resolve host '{hostname}'")

        for resolved_ip in resolved_ips:
            if cls.is_ip_prohibited(resolved_ip):
                logger.error(f"SSRFGuard: Hostname '{hostname}' resolved to prohibited IP '{resolved_ip}'")
                raise AuthorizationError(f"Access to host '{hostname}' resolved to prohibited address {resolved_ip}")

    @classmethod
    async def safe_fetch(
        cls,
        url: str,
        method: str = "GET",
        headers: dict = None,
        timeout: float = 15.0,
        **kwargs,
    ) -> httpx.Response:
        """Execute HTTP request with strict SSRF pre-validation."""
        cls.validate_url(url)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            resp = await client.request(method, url, headers=headers, **kwargs)
            # If redirect, validate the redirect target before following
            if resp.is_redirect and "location" in resp.headers:
                redirect_url = resp.headers["location"]
                cls.validate_url(redirect_url)
            return resp


ssrf_guard = SSRFProtectionGuard()
