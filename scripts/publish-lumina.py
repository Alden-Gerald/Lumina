#!/usr/bin/python3
"""Keep the lumina.local mDNS address published through the system Avahi daemon."""
import sys
import socket
import time

import dbus


def publish(address):
    bus = dbus.SystemBus()
    server = dbus.Interface(bus.get_object("org.freedesktop.Avahi", "/"), "org.freedesktop.Avahi.Server")
    group_path = server.EntryGroupNew()
    group = dbus.Interface(bus.get_object("org.freedesktop.Avahi", group_path), "org.freedesktop.Avahi.EntryGroup")
    # This address already has fedora-2.local as its reverse name.
    # Avahi's NO_REVERSE flag permits an additional forward name.
    group.AddAddress(socket.if_nametoindex("br0"), 0, dbus.UInt32(16), "lumina.local", address)
    group.Commit()
    return bus, group


def main():
    address = sys.argv[1] if len(sys.argv) > 1 else "192.168.18.5"
    while True:
        try:
            bus, group = publish(address)
            print(f"Published lumina.local → {address}", flush=True)
            while True:
                state = int(group.GetState())
                if state in (3, 4):
                    raise RuntimeError(f"Avahi address publication failed (state {state})")
                time.sleep(10)
        except (dbus.DBusException, RuntimeError) as error:
            print(f"Lumina mDNS: {error}; retrying", file=sys.stderr, flush=True)
            time.sleep(10)


if __name__ == "__main__":
    main()
