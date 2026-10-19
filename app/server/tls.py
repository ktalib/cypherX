"""
A self-made HTTPS certificate for the web dashboard.

Phone browsers only allow the camera on secure (https://) pages, so the
dashboard also listens on a second, encrypted port. Nobody can issue a real
certificate for a home address like 192.168.1.20, so the app makes its own:
phones show a one-time "not private" warning that the user accepts.

The certificate names every LAN address of this PC and is made again when the
PC's address changes or it gets close to expiring.
"""
import datetime
import ipaddress
import os
import socket
import ssl

from app.config import USER_DATA_DIR

TLS_DIR = USER_DATA_DIR / "web"
VALID_DAYS = 825
RENEW_DAYS = 30

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    HAS_CRYPTO = True
except ImportError:  # pragma: no cover
    HAS_CRYPTO = False


def _wanted_names(ips):
    return {"localhost", socket.gethostname()}, {"127.0.0.1", *ips}


def _cert_ok(cert_path, ips, now):
    try:
        with open(cert_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except (OSError, ValueError, x509.ExtensionNotFound):
        return False
    have = {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}
    _, want_ips = _wanted_names(ips)
    expires = cert.not_valid_after_utc
    return want_ips <= have and expires - now > datetime.timedelta(days=RENEW_DAYS)


def ensure_certificate(ips, folder=None, now=None):
    """Return (cert_path, key_path), making a new pair when needed."""
    if not HAS_CRYPTO:
        raise RuntimeError("The 'cryptography' package is needed for HTTPS (pip install cryptography)")
    folder = folder or TLS_DIR
    os.makedirs(folder, exist_ok=True)
    cert_path, key_path = os.path.join(folder, "cert.pem"), os.path.join(folder, "key.pem")
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if os.path.exists(key_path) and _cert_ok(cert_path, ips, now):
        return cert_path, key_path

    key = ec.generate_private_key(ec.SECP256R1())
    dns, addrs = _wanted_names(ips)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CYPHER-X Home"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CYPHER-X")])
    san = [x509.DNSName(d) for d in sorted(dns)] + [x509.IPAddress(ipaddress.ip_address(a)) for a in sorted(addrs)]
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=VALID_DAYS))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256()))
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def server_context(cert_path, key_path):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert_path, key_path)
    return ctx
