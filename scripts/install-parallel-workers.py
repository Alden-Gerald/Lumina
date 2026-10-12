#!/usr/bin/env python3
"""Install this machine's worker units only while both app modes are idle."""
from pathlib import Path
import shutil
import subprocess
from local_coder.cli import request
from local_coder.settings import DATA_ROOT,APP_ROOT


def main():
    for route,terminal in [('/runs',{'completed','needs_attention','cancelled'}),('/chats',{'idle','failed','cancelled'})]:
        if any(s['status'] not in terminal for s in request(route)):
            raise SystemExit('Running work found. Wait for both Chat and Code before installing.')
    marker=DATA_ROOT/'maintenance'
    owned=not marker.exists()
    marker.touch(mode=0o600)
    try:
        subprocess.run(['systemctl','--user','stop','local-coder.service'],check=True)
        subprocess.run(['systemctl','--user','stop','local-coder-helper.service','local-coder-ollama.service'],check=True)
        target=Path.home()/'.config/systemd/user'
        for path in (APP_ROOT/'config/systemd').glob('local-coder-*'):
            shutil.copy2(path,target/path.name)
        subprocess.run(['systemctl','--user','daemon-reload'],check=True)
        subprocess.run(['systemctl','--user','start','local-coder-ollama.service','local-coder.service'],check=True)
        print('RX builder installed; GTX helper starts on demand. Shared cap: 16 GiB.')
    finally:
        if owned:marker.unlink(missing_ok=True)


if __name__=='__main__':main()
