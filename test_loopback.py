from urllib.parse import urlsplit
import ipaddress

def _is_loopback_host(host: str | None) -> bool:
    if host is None:
        return False
    normalized = host.strip().strip("[]").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False

print(_is_loopback_host(urlsplit("http://127.0.0.1:8080").hostname))
print(_is_loopback_host(urlsplit("http://localhost:8080").hostname))
print(_is_loopback_host(urlsplit("http://192.168.1.1:8080").hostname))
