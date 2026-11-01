import ipaddress
from flask import current_app, request

def parse_ip(value):
    """The address as a normalised string, or None when it is not an IP."""
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None

def is_loopback(address):
    ip = parse_ip(address or '')
    return ip is not None and ipaddress.ip_address(ip).is_loopback

def client_ip():
    """The client's IP for lockouts, rate limits and the request log.

    A proxy header is trusted only when SHADOW_CLIENT_IP_HEADER names it AND the
    connection itself comes from loopback (the tunnel on this machine). Anything
    else falls back to the connection address, so a remote caller cannot spoof it.
    """
    remote = request.remote_addr or ''
    header = current_app.config.get('CLIENT_IP_HEADER') or ''
    if not header or not is_loopback(remote):
        return remote
    value = request.headers.get(header)
    if not value:
        return remote
    if header.lower() == 'x-forwarded-for':
        # The proxy appends the address it saw, so the right-most valid entry is the one to trust
        for part in reversed(value.split(',')):
            ip = parse_ip(part)
            if ip:
                return ip
        return remote
    return parse_ip(value) or remote
