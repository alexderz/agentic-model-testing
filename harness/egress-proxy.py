#!/usr/bin/env python3
"""Allowlisting egress proxy for agent sandboxes.

The agent container sits on a podman --internal network and has NO route out.
Everything it reaches goes through this process, which:

  * ALLOWS the public internet (the point: give the agent real docs and search)
  * DENIES RFC1918, CGNAT, link-local and the WireGuard range, so the agent
    cannot reach the house LAN, the mesh, the real Home Assistant, Saturn, the
    NAS, or any other machine
  * makes a NARROW exception for the two endpoints the harness itself needs,
    which are reached through dedicated forwarders rather than by name

Every request is logged. That log is the point as much as the filtering is: it
tells us whether a model consults primary sources or invents them, which is the
question the whole experiment exists to answer.
"""
import ipaddress
import logging
import os
import select
import socket
import socketserver
import sys
import threading

LOG = os.environ.get("EGRESS_LOG", "/var/log/egress.jsonl")
DENY_NETS = [ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",   # RFC1918: LAN + WireGuard
    "100.64.0.0/10",                                    # CGNAT
    "169.254.0.0/16", "127.0.0.0/8", "::1/128", "fe80::/10", "fc00::/7",
)]
logging.basicConfig(filename=LOG, level=logging.INFO,
                    format='{"t":"%(asctime)s","%(message)s}')


def resolves_to_denied(host):
    """Resolve and check every answer, so a public name pointing at a private
    address (DNS rebinding) is refused too."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True, "unresolvable"
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        for net in DENY_NETS:
            if addr.version == net.version and addr in net:
                return True, f"{addr} is in {net}"
    return False, ""


class Handler(socketserver.StreamRequestHandler):
    timeout = 60

    def handle(self):
        try:
            line = self.rfile.readline(65536).decode("latin-1").strip()
        except Exception:
            return
        if not line:
            return
        parts = line.split()
        if len(parts) < 2:
            return
        method, target = parts[0], parts[1]

        if method.upper() == "CONNECT":
            host, _, port = target.rpartition(":")
            port = int(port or 443)
        else:
            rest = target.split("//", 1)[-1]
            hostport = rest.split("/", 1)[0]
            host, _, port = hostport.partition(":")
            port = int(port or 80)

        denied, why = resolves_to_denied(host)
        if denied:
            logging.info('"verdict":"DENY","host":"%s","port":%d,"why":"%s"', host, port, why)
            self.wfile.write(b"HTTP/1.1 403 Forbidden\r\n\r\nblocked by egress policy: "
                             + why.encode() + b"\r\n")
            return
        logging.info('"verdict":"ALLOW","method":"%s","host":"%s","port":%d', method, host, port)

        try:
            upstream = socket.create_connection((host, port), timeout=20)
        except OSError as exc:
            self.wfile.write(f"HTTP/1.1 502 Bad Gateway\r\n\r\n{exc}\r\n".encode())
            return
        if method.upper() == "CONNECT":
            self.wfile.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        else:
            # replay the request line and the rest of the headers
            upstream.sendall(line.encode("latin-1") + b"\r\n")
            while True:
                hdr = self.rfile.readline(65536)
                upstream.sendall(hdr)
                if hdr in (b"\r\n", b"\n", b""):
                    break
        self.pump(self.connection, upstream)

    def pump(self, a, b):
        socks = [a, b]
        try:
            while True:
                ready, _, err = select.select(socks, [], socks, 60)
                if err or not ready:
                    break
                for s in ready:
                    other = b if s is a else a
                    data = s.recv(65536)
                    if not data:
                        return
                    other.sendall(data)
        except OSError:
            pass
        finally:
            for s in socks:
                try:
                    s.close()
                except OSError:
                    pass


class Threaded(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8888
    print(f"egress proxy on :{port}, denying {len(DENY_NETS)} private ranges", flush=True)
    Threaded(("0.0.0.0", port), Handler).serve_forever()
