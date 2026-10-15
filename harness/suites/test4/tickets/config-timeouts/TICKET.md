# Make the connect timeout and retries configurable

Our Home Assistant sits behind a proxy that answers 502 or 503 for a few seconds whenever it
restarts, and every tool call made in that window fails. We need three more settings, read from the
environment like `HA_MCP_TIMEOUT_SECS`.

- `HA_MCP_CONNECT_TIMEOUT_SECS`, default `5`, range 1 to 600: the longest wait for the connection to
  open. A value above `HA_MCP_TIMEOUT_SECS` is accepted; the request timeout still applies.
- `HA_MCP_RETRIES`, default `0`, range 0 to 10: extra attempts after a failed request. `2` means at
  most three requests.
- `HA_MCP_RETRY_DELAY_MS`, default `500`, range 0 to 60000: the fixed pause between two attempts.

## Rules

- Retry only when the connection cannot be made, the request times out, or the answer is HTTP 502,
  503 or 504. Any other answer (401, 403, 404, other 4xx) is final and is requested once.
- When every attempt fails, the tool reports the last failure the way it does today.
- With none of the three set, the server behaves exactly as now: one attempt, the same timeouts.
- All three take whole numbers. Anything else, or a value out of range, stops the server at start
  like a bad `HA_MCP_TIMEOUT_SECS` does: exit status 2 and a stderr line naming the variable.
- The README's configuration table documents all three.
- The new behaviour has tests, and the existing tests still pass (`cargo test`).
