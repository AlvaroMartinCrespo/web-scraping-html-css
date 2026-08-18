import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeUrlError(ValueError):
    pass


def validate_public_url(url: str) -> str:
    candidate = url.strip()
    parsed = urlparse(candidate)

    if parsed.scheme not in {"http", "https"}:
        raise UnsafeUrlError("La URL debe comenzar por http:// o https://.")
    if not parsed.hostname:
        raise UnsafeUrlError("La URL no contiene un dominio valido.")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("No se permiten credenciales dentro de la URL.")

    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)
        }
    except socket.gaierror as error:
        raise UnsafeUrlError("No se ha podido resolver el dominio.") from error

    if not addresses:
        raise UnsafeUrlError("No se ha podido resolver el dominio.")

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise UnsafeUrlError("La URL apunta a una red privada o reservada.")

    return candidate