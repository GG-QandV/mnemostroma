# SPDX-License-Identifier: FSL-1.1-MIT
"""Generate self-signed CA + server cert for proxy_passthrough TLS.

Called once during `mnemostroma setup`. Requires `cryptography` package
(available when mnemostroma[sse] is installed).
"""
from __future__ import annotations

import datetime
import ipaddress
from pathlib import Path


def generate_passthrough_tls(mnemo_dir: Path) -> tuple[Path, Path, Path]:
    """Generate CA cert + server cert/key into mnemo_dir/certs/.

    Returns (ca_cert_path, server_cert_path, server_key_path).
    Idempotent — skips generation if all three files already exist.
    """
    certs_dir    = mnemo_dir / "certs"
    ca_cert_path = certs_dir / "passthrough-ca.pem"
    cert_path    = certs_dir / "passthrough-cert.pem"
    key_path     = certs_dir / "passthrough-key.pem"

    if ca_cert_path.exists() and cert_path.exists() and key_path.exists():
        return ca_cert_path, cert_path, key_path

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now    = datetime.datetime.utcnow()
    expire = now + datetime.timedelta(days=3650)
    pem    = serialization.Encoding.PEM

    # CA key + self-signed cert
    ca_key  = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Mnemostroma Local CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(expire)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    # Server key + cert signed by CA
    srv_key  = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    srv_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    srv_cert = (
        x509.CertificateBuilder()
        .subject_name(srv_name)
        .issuer_name(ca_name)
        .public_key(srv_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(expire)
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            ]),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    certs_dir.mkdir(parents=True, exist_ok=True)
    ca_cert_path.write_bytes(ca_cert.public_bytes(pem))
    cert_path.write_bytes(srv_cert.public_bytes(pem))
    key_path.write_bytes(
        srv_key.private_bytes(
            pem,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)

    return ca_cert_path, cert_path, key_path
