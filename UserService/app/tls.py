from __future__ import annotations

import argparse
import ipaddress
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from .config import ServerSettings

logger = logging.getLogger(__name__)

DEFAULT_CERT_FILE = Path("certs/server.crt")
DEFAULT_KEY_FILE = Path("certs/server.key")


def _normalize_hosts(hosts: Sequence[str]) -> list[str]:
    values = [host.strip() for host in hosts if host and host.strip()]
    return values or ["localhost", "127.0.0.1"]


def generate_self_signed_certificate(
    cert_file: str | Path = DEFAULT_CERT_FILE,
    key_file: str | Path = DEFAULT_KEY_FILE,
    hosts: Sequence[str] | None = None,
) -> tuple[Path, Path]:
    """Generate a self-signed server certificate and key in PEM format."""
    cert_path = Path(cert_file)
    key_path = Path(key_file)
    normalized_hosts = _normalize_hosts(hosts or [])

    san_entries: list[x509.GeneralName] = []
    for host in normalized_hosts:
        try:
            san_entries.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            san_entries.append(x509.DNSName(host))

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    subject = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, normalized_hosts[0])]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    if os.name != "nt":
        try:
            key_path.chmod(0o600)
        except OSError:
            logger.warning("Could not restrict permissions on %s", key_path)

    return cert_path, key_path


def ensure_tls_files(settings: ServerSettings) -> tuple[Path, Path]:
    """Return usable cert/key paths, generating a self-signed pair if enabled."""
    if not settings.enable_https:
        raise ValueError("HTTPS is not enabled")

    cert_configured = bool(settings.tls_cert_file)
    key_configured = bool(settings.tls_key_file)
    if cert_configured != key_configured:
        raise ValueError(
            "server.tls_cert_file and server.tls_key_file must be configured together"
        )

    if cert_configured:
        cert_path = Path(settings.tls_cert_file)
        key_path = Path(settings.tls_key_file)
    elif settings.tls_self_signed:
        cert_path = DEFAULT_CERT_FILE
        key_path = DEFAULT_KEY_FILE
    else:
        raise ValueError(
            "server.enable_https is true, but no TLS certificate is configured. "
            "Set server.tls_cert_file/server.tls_key_file, or set "
            "server.tls_self_signed = true to generate one."
        )

    if cert_path.is_file() and key_path.is_file():
        return cert_path, key_path

    if not settings.tls_self_signed:
        missing = cert_path if not cert_path.is_file() else key_path
        raise ValueError(
            f"TLS file not found: {missing}. Set server.tls_self_signed = true "
            "to generate a self-signed certificate."
        )

    logger.warning(
        "TLS certificate missing; generating a self-signed certificate for %s",
        ", ".join(_normalize_hosts(settings.tls_hosts)),
    )
    cert_path, key_path = generate_self_signed_certificate(
        cert_path, key_path, settings.tls_hosts
    )
    logger.warning("Self-signed certificate written to %s", cert_path)
    return cert_path, key_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a self-signed TLS certificate for FireflyFrp User Service"
    )
    parser.add_argument("--cert", default=str(DEFAULT_CERT_FILE), help="certificate output path")
    parser.add_argument("--key", default=str(DEFAULT_KEY_FILE), help="private key output path")
    parser.add_argument(
        "--host",
        action="append",
        dest="hosts",
        default=[],
        help="DNS name or IP included in the certificate SAN; repeat for multiple values",
    )
    args = parser.parse_args()
    cert_path, key_path = generate_self_signed_certificate(
        args.cert, args.key, args.hosts
    )
    print(f"certificate: {cert_path}")
    print(f"private key: {key_path}")


if __name__ == "__main__":
    main()
