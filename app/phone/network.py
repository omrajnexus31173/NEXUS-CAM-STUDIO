import ipaddress
import socket
import psutil


def lan_addresses():
    found = []
    try:
        for name, entries in psutil.net_if_addrs().items():
            for entry in entries:
                if entry.family == socket.AF_INET:
                    ip = ipaddress.ip_address(entry.address)
                    if not ip.is_loopback and not ip.is_link_local and not ip.is_unspecified:
                        found.append(entry.address)
    except Exception:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            # UDP connect only asks the OS for its route; no data leaves the PC.
            probe.connect(('8.8.8.8', 80))
            primary = probe.getsockname()[0]
            if primary not in ('127.0.0.1', '0.0.0.0'):
                found = [primary] + [v for v in found if v != primary]
    except OSError:
        pass
    return list(dict.fromkeys(found))


def choose_ip(auto=True, manual=''):
    if not auto:
        address = ipaddress.ip_address(manual.strip())
        if address.version != 4 or address.is_loopback or address.is_unspecified:
            raise ValueError('Enter the PC Wi-Fi/Ethernet IPv4 address, not localhost or 0.0.0.0')
        return str(address)
    addresses = lan_addresses()
    if not addresses:
        raise RuntimeError('No LAN address found. Connect this PC to Wi-Fi/Ethernet and try again.')
    return addresses[0]
