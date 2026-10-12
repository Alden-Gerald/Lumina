#!/usr/bin/env python3
"""Issue or renew Lumina's HTTPS certificate from its private local CA."""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import subprocess
import tempfile

from local_coder.settings import DATA_ROOT


FOLDER = DATA_ROOT / "lan"


def openssl(*arguments: str):
    subprocess.run(["openssl", *arguments], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    FOLDER.mkdir(parents=True, exist_ok=True, mode=0o700)
    FOLDER.chmod(0o700)
    ca_certificate = FOLDER / "lumina-ca.crt"
    ca_key = FOLDER / "lumina-ca.key"
    if ca_certificate.exists() != ca_key.exists():
        raise SystemExit("Local CA is incomplete; refusing to replace it")
    if not ca_certificate.exists():
        openssl("req", "-x509", "-newkey", "rsa:4096", "-nodes", "-sha256",
                "-days", "3650", "-subj", "/CN=Lumina Local CA",
                "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
                "-addext", "keyUsage=critical,keyCertSign,cRLSign",
                "-addext", "subjectKeyIdentifier=hash",
                "-keyout", str(ca_key), "-out", str(ca_certificate))
        ca_key.chmod(0o600)
        ca_certificate.chmod(0o644)

    with tempfile.TemporaryDirectory(prefix="lumina-cert-", dir=FOLDER) as temporary:
        tmp = Path(temporary)
        key = tmp / "key.pem"
        request = tmp / "request.csr"
        leaf = tmp / "leaf.pem"
        chain = tmp / "cert.pem"
        extensions = tmp / "extensions.cnf"
        extensions.write_text("""[server_cert]
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:lumina.local,IP:192.168.18.5
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid
""")
        openssl("req", "-new", "-newkey", "rsa:3072", "-nodes", "-sha256",
                "-subj", "/CN=lumina.local", "-keyout", str(key), "-out", str(request))
        openssl("x509", "-req", "-in", str(request), "-CA", str(ca_certificate),
                "-CAkey", str(ca_key), "-set_serial", "0x" + secrets.token_hex(16),
                "-days", "397", "-sha256", "-extfile", str(extensions),
                "-extensions", "server_cert", "-out", str(leaf))
        chain.write_bytes(leaf.read_bytes() + ca_certificate.read_bytes())
        openssl("verify", "-CAfile", str(ca_certificate), "-verify_hostname", "lumina.local", str(leaf))
        key.chmod(0o600)
        chain.chmod(0o600)
        os.replace(key, FOLDER / "key.pem")
        os.replace(chain, FOLDER / "cert.pem")

    fingerprint = subprocess.check_output(
        ["openssl", "x509", "-in", str(ca_certificate), "-noout", "-fingerprint", "-sha256"],
        text=True).strip()
    print("Lumina CA:", fingerprint)
    subprocess.run(["systemctl", "--user", "restart", "lumina-gateway.service"], check=True)


if __name__ == "__main__":
    main()
