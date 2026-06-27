"""SSRF protections for outbound monitor checks."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class SSRFError(ValueError):
    """Raised when a monitor URL targets a blocked host or scheme."""


_BLOCKED_SCHEMES = {"", "file", "ftp", "gopher", "data", "javascript"}
_ALLOWED_SCHEMES = {"http", "https"}


def _is_blocked_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if address.is_loopback:
        return True
    if address.is_private:
        return True
    if address.is_link_local:
        return True
    if address.is_multicast:
        return True
    if address.is_reserved:
        return True
    if address.is_unspecified:
        return True

    if isinstance(address, ipaddress.IPv4Address):
        if address in ipaddress.IPv4Network("169.254.0.0/16"):
            return True
        if address in ipaddress.IPv4Network("127.0.0.0/8"):
            return True
        if address in ipaddress.IPv4Network("10.0.0.0/8"):
            return True
        if address in ipaddress.IPv4Network("172.16.0.0/12"):
            return True
        if address in ipaddress.IPv4Network("192.168.0.0/16"):
            return True
        if address in ipaddress.IPv4Network("0.0.0.0/8"):
            return True

    if isinstance(address, ipaddress.IPv6Address):
        if address == ipaddress.IPv6Address("::1"):
            return True
        if address in ipaddress.IPv6Network("fe80::/10"):
            return True
        if address in ipaddress.IPv6Network("fc00::/7"):
            return True

    return False


def _hostname_is_blocked(hostname: str) -> bool:
    lowered = hostname.strip().lower().rstrip(".")
    if lowered in {"localhost", "localhost.localdomain"}:
        return True
    if lowered.endswith(".localhost"):
        return True
    if lowered.endswith(".local"):
        return True
    if lowered.endswith(".internal"):
        return True
    return False


def validate_monitor_url(url: str) -> str:
    """Validate URL scheme/host and reject private or internal targets."""
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()

    if scheme in _BLOCKED_SCHEMES or scheme not in _ALLOWED_SCHEMES:
        raise SSRFError("Monitor URL must use http or https.")

    if not parsed.hostname:
        raise SSRFError("Monitor URL must include a hostname.")

    hostname = parsed.hostname
    if _hostname_is_blocked(hostname):
        raise SSRFError("Monitor URL hostname is not allowed.")

    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None
    else:
        if _is_blocked_ip(literal_ip):
            raise SSRFError("Monitor URL resolves to a blocked IP address.")

    try:
        port = parsed.port or (443 if scheme == "https" else 80)
        addrinfos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SSRFError(f"Unable to resolve monitor URL hostname: {hostname}") from exc

    if not addrinfos:
        raise SSRFError(f"Unable to resolve monitor URL hostname: {hostname}")

    for family, _, _, _, sockaddr in addrinfos:
        if family == socket.AF_INET:
            ip = ipaddress.IPv4Address(sockaddr[0])
        elif family == socket.AF_INET6:
            ip = ipaddress.IPv6Address(sockaddr[0])
        else:
            continue
        if _is_blocked_ip(ip):
            raise SSRFError("Monitor URL resolves to a blocked IP address.")

    return url.strip()
