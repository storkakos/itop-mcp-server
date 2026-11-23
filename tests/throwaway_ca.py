"""Throwaway test CA and a server certificate signed by it, for the internal-CA tests.

Used by tests/test_internal_ca.py and, inside the image, by scripts/smoke-test.sh:

    python tests/throwaway_ca.py <out-dir> <host> [<host> ...]

writes ca.pem (the bundle a customer would mount), server.pem and server-key.pem.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import sys
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


@dataclass
class CAFiles:
    ca: Path
    cert: Path
    key: Path


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _san(host: str) -> x509.GeneralName:
    try:
        return x509.IPAddress(ipaddress.ip_address(host))
    except ValueError:
        return x509.DNSName(host)


def make_ca(out_dir: Path, hosts: list[str]) -> CAFiles:
    out_dir.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    valid_from, valid_to = now - dt.timedelta(minutes=5), now + dt.timedelta(days=1)

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_ski = x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key())
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(_name("itop-mcp throwaway test CA"))
        .issuer_name(_name("itop-mcp throwaway test CA"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(valid_from)
        .not_valid_after(valid_to)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                     data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                     crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(ca_ski, critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(hosts[0]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(valid_from)
        .not_valid_after(valid_to)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([_san(h) for h in hosts]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ca_ski), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    files = CAFiles(out_dir / "ca.pem", out_dir / "server.pem", out_dir / "server-key.pem")
    files.ca.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    files.cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    files.key.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption()))
    return files


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: throwaway_ca.py <out-dir> <host> [<host> ...]")
    make_ca(Path(sys.argv[1]), sys.argv[2:])
