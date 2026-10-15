#!/bin/bash
# Test 8 browser container (localhost/bakeoff-browser, run by run-case-test8.sh with --network=none, a read-only root,
# no capabilities). Mounts: /site = the agent's /work (read-only), /three = three 0.186.1 (read-only), /opt/t8 = this
# folder (read-only: these settings), /sock = the socket folder shared with the agent's container.
# Starts the preview server on 127.0.0.1:8000, also offered on /sock/preview.sock for the agent's shell
# (sandbox/t8/preview-bridge.py puts it on the agent's 127.0.0.1:8000), then serves Playwright MCP (stdio) on /sock/mcp.sock: one MCP server and
# one browser per connection. Image answers are set by PLAYWRIGHT_MCP_IMAGE_RESPONSES (allow or omit) at container start.
set -u
export HOME=/root
python3 -I /opt/t8/preview.py /site /three 8000 &
for i in $(seq 1 50); do python3 -c 'import socket; socket.create_connection(("127.0.0.1", 8000), 1)' 2>/dev/null && break; sleep 0.2; done
python3 -c 'import socket; socket.create_connection(("127.0.0.1", 8000), 1)' 2>/dev/null \
  || { echo "browser-entry: the preview server did not start" >&2; exit 1; }
socat UNIX-LISTEN:/sock/preview.sock,fork,unlink-early,mode=600 TCP:127.0.0.1:8000 &
PSOCK=$!
for i in $(seq 1 50); do [ -S /sock/preview.sock ] && break; sleep 0.1; done
# without the preview socket there is no mcp.sock either, so run-case-test8.sh stops the case as a harness failure
kill -0 "$PSOCK" 2>/dev/null && [ -S /sock/preview.sock ] \
  || { echo "browser-entry: the preview socket did not start" >&2; exit 1; }
echo "browser-entry: preview up; chromium $(chromium --version 2>/dev/null); image responses ${PLAYWRIGHT_MCP_IMAGE_RESPONSES:-allow}" >&2
exec socat UNIX-LISTEN:/sock/mcp.sock,fork,unlink-early,mode=600 \
  EXEC:"node /usr/local/lib/node_modules/@playwright/mcp/cli.js --config /opt/t8/playwright-mcp.json"
