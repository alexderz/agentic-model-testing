"""Test 8, agent side: OpenCode's `browser` MCP server. Joins OpenCode's stdio to the browser container's socket.
  python3 -I mcp-bridge.py /sock/mcp.sock
The browser, its settings and the preview server live in their own container (no network); this only carries bytes.
"""
import os
import socket
import sys
import threading
import time

s = socket.socket(socket.AF_UNIX)
for _ in range(60):
    try:
        s.connect(sys.argv[1])
        break
    except OSError:
        time.sleep(1)
else:
    sys.exit("mcp-bridge: no browser at " + sys.argv[1])


def up():
    while True:
        b = os.read(0, 65536)
        if not b:
            s.shutdown(socket.SHUT_WR)
            return
        s.sendall(b)


threading.Thread(target=up, daemon=True).start()
out = sys.stdout.buffer
while True:
    b = s.recv(65536)
    if not b:
        break
    out.write(b)
    out.flush()
