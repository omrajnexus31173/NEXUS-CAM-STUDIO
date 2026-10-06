import ipaddress
import os
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from app.utils.paths import data_dir


def _private_write(path, content):
    path.write_bytes(content)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def certificate_files(addresses, folder=None):
    """One unique local CA per installation, IP-SAN server cert. Never ship a private key."""
    folder = Path(folder) if folder else data_dir() / 'phone-certificates'
    folder.mkdir(parents=True, exist_ok=True)
    root_path, root_key_path = folder / 'nexus-phone-root.crt', folder / 'root-key.pem'
    now = datetime.now(timezone.utc)
    if root_path.exists() and root_key_path.exists():
        root = x509.load_pem_x509_certificate(root_path.read_bytes())
        key = serialization.load_pem_private_key(root_key_path.read_bytes(), password=None)
        if root.not_valid_after_utc < now + timedelta(days=2):
            root = None
    else:
        root = None
    if root is None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Nexus Cam Studio local phone CA')])
        root = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
                .not_valid_after(now + timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                .sign(key, hashes.SHA256()))
        root_path.write_bytes(root.public_bytes(serialization.Encoding.PEM))
        _private_write(root_key_path, key.private_bytes(serialization.Encoding.PEM,
                                                       serialization.PrivateFormat.PKCS8,
                                                       serialization.NoEncryption()))
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Nexus Cam Studio phone camera')])
    ips = set(addresses) | {'127.0.0.1'}
    sans = [x509.IPAddress(ipaddress.ip_address(ip)) for ip in sorted(ips)]
    sans += [x509.DNSName('localhost'), x509.DNSName(socket.gethostname())]
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(root.subject)
            .public_key(server_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.KeyUsage(True, False, True, False, False, False, False, False, False), critical=True)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    chain_path, server_key_path = folder / 'server-chain.pem', folder / 'server-key.pem'
    chain_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM) + root.public_bytes(serialization.Encoding.PEM))
    _private_write(server_key_path, server_key.private_bytes(serialization.Encoding.PEM,
                                                           serialization.PrivateFormat.PKCS8,
                                                           serialization.NoEncryption()))
    return chain_path, server_key_path, root_path
