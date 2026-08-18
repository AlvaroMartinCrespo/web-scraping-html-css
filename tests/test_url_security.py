import socket
import unittest
from unittest.mock import patch

from url_security import UnsafeUrlError, validate_public_url


PUBLIC_RESULT = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
PRIVATE_RESULT = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]


class ValidatePublicUrlTests(unittest.TestCase):
    @patch("url_security.socket.getaddrinfo", return_value=PUBLIC_RESULT)
    def test_accepts_public_http_url(self, _getaddrinfo):
        self.assertEqual(
            validate_public_url(" https://example.com/page "),
            "https://example.com/page",
        )

    def test_rejects_non_http_urls(self):
        for url in ("file:///etc/passwd", "ftp://example.com", "example.com"):
            with self.subTest(url=url), self.assertRaises(UnsafeUrlError):
                validate_public_url(url)

    @patch("url_security.socket.getaddrinfo", return_value=PRIVATE_RESULT)
    def test_rejects_private_networks(self, _getaddrinfo):
        with self.assertRaisesRegex(UnsafeUrlError, "privada"):
            validate_public_url("http://localhost/admin")

    @patch("url_security.socket.getaddrinfo", return_value=PUBLIC_RESULT)
    def test_rejects_embedded_credentials(self, _getaddrinfo):
        with self.assertRaisesRegex(UnsafeUrlError, "credenciales"):
            validate_public_url("https://admin:secret@example.com")


if __name__ == "__main__":
    unittest.main()