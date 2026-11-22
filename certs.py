"""
Makes the HTTPS certificate that lets tablets and phones play.

Chrome only lets a page use what the games need (shared memory, the audio
engine, offline storage) when the page is "secure": https://, or localhost on
the computer itself.  So other devices need https://, which needs a
certificate they trust.

The first time it runs, this makes a small certificate authority of its own
(tls/ca.pem; its private key never leaves this computer) and uses it to sign
a certificate for this computer's names and network addresses (tls/server.pem).
Each tablet or phone installs ca.pem once (the server's /setup page shows how).
The server certificate is remade automatically when it gets old or the
computer's address changes; devices don't need to do anything when that happens.

Needs the "cryptography" package (start-windows.bat installs it, or:
    py -m pip install cryptography).
"""
from __future__ import annotations

import datetime
import ipaddress
import socket
from pathlib import Path

TLS_DIR = Path(__file__).resolve().parent / "tls"
CA_CERT = TLS_DIR / "ca.pem"
CA_KEY = TLS_DIR / "ca-key.pem"
SERVER_CERT = TLS_DIR / "server.pem"
SERVER_KEY = TLS_DIR / "server-key.pem"

SERVER_DAYS = 397          # Apple devices refuse longer-lived server certificates
RENEW_DAYS = 30


def available() -> bool:
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


def this_computer_names(lan: list[str]) -> tuple[list[str], list[str]]:
    """(DNS names, IP addresses) the server can be reached by."""
    host = socket.gethostname().split(".")[0]
    names = ["localhost"]
    if host:
        names += [host, host + ".local"]
    ips = ["127.0.0.1", "::1"]
    for ip in lan:
        if ip and ip not in ips:
            ips.append(ip)
    return names, ips


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _write_key(path: Path, key):
    from cryptography.hazmat.primitives import serialization
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                       serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))


def _make_ca():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    host = socket.gethostname().split(".")[0] or "this computer"
    name = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Kaser games server (private)"),
        x509.NameAttribute(NameOID.COMMON_NAME, f"Kaser games on {host}"),
    ])
    now = _now()
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                         content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    TLS_DIR.mkdir(exist_ok=True)
    _write_key(CA_KEY, key)
    CA_CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _server_cert_ok(names: list[str], ips: list[str]) -> bool:
    from cryptography import x509
    try:
        cert = x509.load_pem_x509_certificate(SERVER_CERT.read_bytes())
        ca = x509.load_pem_x509_certificate(CA_CERT.read_bytes())
    except (OSError, ValueError):
        return False
    if not SERVER_KEY.exists() or cert.issuer != ca.subject:
        return False
    end = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(tzinfo=datetime.timezone.utc)
    if end - _now() < datetime.timedelta(days=RENEW_DAYS):
        return False
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return False
    have_names = {n.lower() for n in san.get_values_for_type(x509.DNSName)}
    have_ips = {str(i) for i in san.get_values_for_type(x509.IPAddress)}
    return {n.lower() for n in names} <= have_names and set(ips) <= have_ips


def _make_server_cert(names: list[str], ips: list[str]):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    ca_key = serialization.load_pem_private_key(CA_KEY.read_bytes(), password=None)
    ca = x509.load_pem_x509_certificate(CA_CERT.read_bytes())
    key = ec.generate_private_key(ec.SECP256R1())
    now = _now()
    alt = [x509.DNSName(n) for n in names] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[1] if len(names) > 1 else names[0])]))
            .issuer_name(ca.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=SERVER_DAYS))
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False, key_cert_sign=False,
                                         crl_sign=False, content_commitment=False, data_encipherment=False,
                                         key_agreement=False, encipher_only=False, decipher_only=False),
                           critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca.public_key()), critical=False)  # type: ignore[arg-type]
            .sign(ca_key, hashes.SHA256()))  # type: ignore[arg-type]
    _write_key(SERVER_KEY, key)
    SERVER_CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def ensure(lan: list[str]) -> tuple[Path, Path, bool]:
    """Make sure tls/ holds a CA and a current server certificate.
    Returns (cert, key, made_new_ca)."""
    made_ca = False
    if not (CA_CERT.exists() and CA_KEY.exists()):
        _make_ca()
        made_ca = True
    names, ips = this_computer_names(lan)
    if made_ca or not _server_cert_ok(names, ips):
        _make_server_cert(names, ips)
    return SERVER_CERT, SERVER_KEY, made_ca


def ca_der(pem_path: Path) -> bytes | None:
    """The CA certificate in the binary form phones and tablets install most easily."""
    try:
        import ssl
        return ssl.PEM_cert_to_DER_cert(pem_path.read_text(encoding="ascii"))
    except (OSError, ValueError):
        return None
