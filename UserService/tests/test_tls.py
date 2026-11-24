from __future__ import annotations

import ipaddress

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from app.config import ServerSettings
from app.tls import ensure_tls_files, generate_self_signed_certificate


def test_generate_self_signed_certificate(tmp_path):
    cert_path, key_path = generate_self_signed_certificate(
        tmp_path / "server.crt",
        tmp_path / "server.key",
        ["localhost", "127.0.0.1"],
    )

    assert cert_path.is_file()
    assert key_path.is_file()

    certificate = x509.load_pem_x509_certificate(cert_path.read_bytes())
    assert certificate.issuer == certificate.subject
    san = certificate.extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    ).value
    assert set(san.get_values_for_type(x509.DNSName)) == {"localhost"}
    assert set(san.get_values_for_type(x509.IPAddress)) == {
        ipaddress.ip_address("127.0.0.1")
    }

    private_key = serialization.load_pem_private_key(
        key_path.read_bytes(), password=None
    )
    assert private_key.key_size == 2048


def test_ensure_tls_files_generates_when_self_signed(tmp_path):
    settings = ServerSettings(
        enable_https=True,
        tls_self_signed=True,
        tls_cert_file=str(tmp_path / "server.crt"),
        tls_key_file=str(tmp_path / "server.key"),
        tls_hosts=["localhost"],
    )

    cert_path, key_path = ensure_tls_files(settings)

    assert cert_path == tmp_path / "server.crt"
    assert key_path == tmp_path / "server.key"
    assert cert_path.is_file()
    assert key_path.is_file()


def test_ensure_tls_files_requires_certificate_without_self_signed(tmp_path):
    settings = ServerSettings(
        enable_https=True,
        tls_self_signed=False,
        tls_cert_file=str(tmp_path / "server.crt"),
        tls_key_file=str(tmp_path / "server.key"),
    )

    with pytest.raises(ValueError, match="TLS file not found"):
        ensure_tls_files(settings)


def test_ensure_tls_files_requires_both_paths(tmp_path):
    settings = ServerSettings(
        enable_https=True,
        tls_cert_file=str(tmp_path / "server.crt"),
    )

    with pytest.raises(ValueError, match="configured together"):
        ensure_tls_files(settings)


def test_ensure_tls_files_requires_https():
    with pytest.raises(ValueError, match="not enabled"):
        ensure_tls_files(ServerSettings())
