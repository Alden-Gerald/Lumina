#!/usr/bin/env python3
"""Change the Lumina LAN login password without printing or storing plaintext."""
import getpass
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import re

from local_coder.lan_gateway import password_hash
from local_coder.settings import DATA_ROOT


def main():
    folder = DATA_ROOT / "lan"
    credential_path=folder / "login.json"
    try:current=json.loads(credential_path.read_text())
    except (OSError,ValueError):current={"username":"lumina","version":1}
    username=input(f"Lumina username [{current.get('username','lumina')}]: ").strip() or current.get('username','lumina')
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}",username):
        raise SystemExit("Username must be 3–40 letters, numbers, dots, dashes, or underscores")
    password = getpass.getpass("New Lumina password (at least 12 characters): ")
    if len(password) < 12:
        raise SystemExit("Password must have at least 12 characters")
    if password != getpass.getpass("Confirm new password: "):
        raise SystemExit("Passwords did not match")
    salt = secrets.token_bytes(16)
    payload = json.dumps({"username":username,"salt":salt.hex(),"hash":password_hash(password,salt),"version":int(current.get('version',1))+1})
    fd, temporary = tempfile.mkstemp(prefix="login-", dir=folder)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as file:
            file.write(payload)
        os.replace(temporary, folder / "login.json")
    finally:
        Path(temporary).unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "restart", "lumina-gateway.service"], check=True)
    print("Lumina password changed. Existing sessions were signed out.")


if __name__ == "__main__":
    main()
