# SPDX-License-Identifier: FSL-1.1-MIT
"""Root CA + on-the-fly per-host leaf certs for the opencode MITM proxy.

Separate trust model from passthrough-ca.pem (single-host `localhost`):
this CA signs leaf certs for arbitrary upstream hostnames seen via
CONNECT, so it must never be reused for the passthrough proxy and vice
versa — mixing the two would let a single compromised key impersonate
both local-only and arbitrary-host traffic.

Leaf certs are cached on disk (~/.mnemostroma/mitm_certs/<host>.{crt,key})
so the TLS handshake never blocks on cert generation after first use.
"""
from __future__ import annotations

import datetime
import threading
from pathlib import Path

_CA_CERT_NAME = "mitm-ca-cert.pem"
_CA_KEY_NAME = "mitm-ca-key.pem"
_CERTS_SUBDIR = "mitm_certs"

# x509 key generation is not thread-safe to interleave per-host; guard
# the read-check-write-cache sequence so concurrent CONNECTs for a new
# host don't race and write a half-written cert file.
_lock = threading.Lock()


def generate_mitm_ca(mnemo_dir: Path) -> tuple[Path, Path]:
    """Generate (once) the root CA used to sign per-host leaf certs.

    Returns (ca_cert_path, ca_key_path). Idempotent.
    """
    ca_cert_path = mnemo_dir / _CA_CERT_NAME
    ca_key_path = mnemo_dir / _CA_KEY_NAME

    if ca_cert_path.exists() and ca_key_path.exists():
        return ca_cert_path, ca_key_path

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    now = datetime.datetime.utcnow()
    expire = now + datetime.timedelta(days=3650)
    pem = serialization.Encoding.PEM

    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Mnemostroma MITM CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(expire)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    mnemo_dir.mkdir(parents=True, exist_ok=True)
    ca_cert_path.write_bytes(ca_cert.public_bytes(pem))
    ca_key_path.write_bytes(
        ca_key.private_bytes(
            pem,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    ca_key_path.chmod(0o600)

    return ca_cert_path, ca_key_path


def get_or_create_leaf_cert(
    host: str, ca_cert_path: Path, ca_key_path: Path, mnemo_dir: Path
) -> tuple[Path, Path]:
    """Return (cert_path, key_path) for `host`, generating + caching on first use."""
    certs_dir = mnemo_dir / _CERTS_SUBDIR
    cert_path = certs_dir / f"{host}.crt"
    key_path = certs_dir / f"{host}.key"

    if cert_path.exists() and key_path.exists():
        return cert_path, key_path

    with _lock:
        # Re-check inside the lock: another connection may have generated
        # the cert while we were waiting.
        if cert_path.exists() and key_path.exists():
            return cert_path, key_path
        _generate_leaf_cert(host, ca_cert_path, ca_key_path, cert_path, key_path)

    return cert_path, key_path


def _generate_leaf_cert(
    host: str, ca_cert_path: Path, ca_key_path: Path, cert_path: Path, key_path: Path
) -> None:
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    ca_cert = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())
    ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)

    now = datetime.datetime.utcnow()
    expire = now + datetime.timedelta(days=825)  # below CA/Browser Forum max leaf lifetime
    pem = serialization.Encoding.PEM

    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])

    try:
        san = x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(host))])
    except ValueError:
        san = x509.SubjectAlternativeName([x509.DNSName(host)])

    leaf_cert = (
        x509.CertificateBuilder()
        .subject_name(leaf_name)
        .issuer_name(ca_cert.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(expire)
        .add_extension(san, critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    cert_path.write_bytes(leaf_cert.public_bytes(pem))
    key_path.write_bytes(
        leaf_key.private_bytes(
            pem,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
