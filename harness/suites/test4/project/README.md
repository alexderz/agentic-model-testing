# home-assistant-mcp

A read-only [Model Context Protocol](https://modelcontextprotocol.io) server for the
Home Assistant REST API, written in Rust. It speaks MCP over stdio (protocol revision
`2026-07-28`, also accepting `2024-11-05` … `2025-11-25` for `initialize`) and exposes
twelve `GET`-only tools: nothing in this server can change your home.

```
MCP client  ⇄  ha-mcp (stdio)  ⇄  Home Assistant REST API  (GET only)
```

## Build

Needs Rust 1.82 or newer.

```sh
cargo build --release
```

The binary is `target/release/ha-mcp`. It takes no command-line arguments; everything is
configured through the environment.

## Run

```sh
HA_URL=http://homeassistant.local:8123 \
HA_TOKEN=<a long-lived access token> \
./target/release/ha-mcp
```

Create the token in Home Assistant under **Settings → People → Security → Long-lived
access tokens**. The server reads stdin line by line and writes one compact JSON-RPC
message per line to stdout. Anything it has to say about itself goes to stderr, so
stdout stays parseable.

The MCP handshake is stateless: `initialize`, `server/discover`, `tools/list`, `ping`
and `tools/call` may arrive in any order, and the server keeps answering while a slow
Home Assistant call is still in flight.

### Trying it by hand

```sh
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2026-07-28","clientInfo":{"name":"manual","version":"0"}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_instance_info","arguments":{}}}' \
  | HA_URL=… HA_TOKEN=… ./target/release/ha-mcp
```

### Wiring it into a client

Generic `mcpServers` snippet (Claude Desktop, Codex, Cursor, …):

```json
{
  "mcpServers": {
    "home-assistant": {
      "command": "/path/to/ha-mcp",
      "env": {
        "HA_URL": "http://homeassistant.local:8123",
        "HA_TOKEN": "<long-lived access token>"
      }
    }
  }
}
```

To poke at it interactively:

```sh
npx @modelcontextprotocol/inspector ./target/release/ha-mcp
```

## Configuration

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `HA_URL` | yes | — | Home Assistant root URL, e.g. `http://homeassistant.local:8123`. No trailing `/api`. Alias: `HA_BASE_URL`. |
| `HA_TOKEN` | yes | — | Long-lived access token. Alias: `HA_LONG_LIVED_ACCESS_TOKEN`. |
| `HA_MCP_TIMEOUT_SECS` | no | `15` | Per-request timeout. Range 1–600. |
| `HA_MCP_MAX_RESPONSE_BYTES` | no | `33554432` | Refuse a response larger than this (4 KiB – 256 MiB). |
| `HA_MCP_TLS_NO_VERIFY` | no | `false` | Skip certificate verification for `https://` URLs. Intended for a self-signed home lab, not for the internet. |
| `HA_MCP_LOG_LEVEL` | no | `info` | `off`, `error`, `warning`, `info`, `debug`. Logs go to stderr. |
| `HA_MCP_STRICT_META` | no | `false` | Require every request to declare its protocol revision in `params._meta`. |
| `HA_MCP_TOOL_PAGE_SIZE` | no | `50` | How many tools one `tools/list` page holds. |

A missing or unusable configuration is fatal: the server logs why to stderr and exits
with status `2` rather than starting a server that could only fail. The token is never
written to a log or echoed back in a tool result.

## Tools

All arguments are optional unless marked *required*; the defaults are chosen so that a
bare call is a sensible first move.

| Tool | Arguments (default) | What it reads |
| --- | --- | --- |
| `get_instance_info` | — | `GET /api/` + `/api/config` + `/api/states` + `/api/services` + `/api/events`, summarised into one orientation card: version, location, unit system, and counts of components, entities, domains, services and event types. |
| `get_config` | `sections` `[]`, `include_components` `true` | `GET /api/config`. Narrow it with `sections`; names that do not exist come back in `missing_sections`. `components_count` is reported even when the list itself is dropped. |
| `list_integrations` | `query` `""`, `limit` `100`, `cursor` `""` | The `components` array, grouped by its first segment, so `mqtt.light` appears under `mqtt`. |
| `list_domains` | `query` `""`, `sort_by` `count`\|`domain`, `limit` `40`, `cursor` `""` | `GET /api/states`, grouped by domain with entity counts, example entities and the three most common states. |
| `list_entities` | `query` `""`, `domain` `""`, `state` `""`, `only_available` `false`, `include_attributes` `false`, `sort_by` `entity_id`\|`domain`\|`friendly_name`\|`state`\|`last_updated`, `sort_dir` `asc`\|`desc`, `limit` `50`, `cursor` `""` | `GET /api/states`, filtered client-side (Home Assistant's REST API ignores filters). Hidden entities are returned flagged `hidden: true`; `only_available: true` drops them. |
| `get_entity` | `entity_id` *required* | `GET /api/states/{entity_id}`, with every attribute preserved. Members this server does not model are kept under `extra` rather than discarded. |
| `get_entities` | `entity_ids` *required*, `include_attributes` `false` | One `GET /api/states` request serving many ids; ids that do not exist are listed in `missing`. |
| `list_services` | `domain` `""`, `query` `""`, `limit` `100`, `cursor` `""` | `GET /api/services`, flattened to one row per `domain.service` with field names and which fields are required. |
| `get_service` | `domain` *required*, `service` *required* | The full definition of one service: description, target selector, every field with its selector kind, options, an example, and whether it is required. Read-only: it tells you what a service *would* do; it never calls one. |
| `get_entity_history` | `entity_id` `""`, `start_time` `""`, `end_time` `""`, `query` `""`, `limit` `100`, `cursor` `""` | `GET /api/logbook`, sorted newest first and narrowed client-side too. Timestamps accept `2026-09-22T12:00:00Z`, `±HH:MM` offsets, `2026-09-22T12:00` and bare dates. |
| `get_error_log` | `level` `any`\|`debug`\|`info`\|`warning`\|`error`\|`critical`, `contains` `""`, `max_lines` `200`, `tail` `true` | `GET /api/error_log` — plain text that can run to megabytes, so it is filtered line by line, tail-kept and clipped to 500 characters per line. |
| `list_events` | `query` `""`, `limit` `100`, `cursor` `""` | `GET /api/events`: the event types the instance knows, with listener counts. |

There are deliberately no tools that write: no service calls, no `POST`, no entity
updates, no resource or prompt APIs.

## How results look

A successful `tools/call` returns the payload twice, so both kinds of client are served:

```json
{
  "content": [{ "type": "text", "mimeType": "application/json", "text": "{…}" }],
  "structuredContent": { "matched": 434, "returned": 50, "next_cursor": "MjA", "…": [] },
  "resultType": "complete"
}
```

`text` is the compact JSON of `structuredContent`, capped at 24 000 characters with a
note when clipped; `structuredContent` is always complete and always matches the tool's
declared `outputSchema`.

When a tool cannot do its job the call still succeeds at the protocol level, and the
result explains itself:

```json
{
  "content": [{ "type": "text", "text": "not found at …/api/states/light.attic: Entity not found … — Confirm the entity id with list_entities …" }],
  "isError": true,
  "resultType": "complete",
  "_meta": { "errorKind": "not-found", "httpStatus": 404 }
}
```

`errorKind` is one of `unknown-tool`, `invalid-arguments`, `unauthorized`, `forbidden`,
`not-found`, `http-status`, `timeout`, `unreachable`, `response-too-large`,
`invalid-response`; `httpStatus` is present when Home Assistant answered with a status.

Protocol mistakes are answered as JSON-RPC errors instead: unparsable JSON (`-32700`),
a non-object message (`-32600`), an unknown method (`-32601`), a missing tool name, a
non-object `arguments`, a non-string `cursor` or a forged cursor (`-32602`), and a
`_meta` protocol revision this server cannot speak (`-32022`, whose message lists the
versions it does know).

### Pagination

Every list tool, and `tools/list` itself, pages. Take `next_cursor` from a result and
send it back unchanged; the last page omits it. `nextCursor` on `tools/list` comes with
a `ttlMs` hint, because the tool set is fixed at build time.

### Version declaration

Requests may declare their revision in `params._meta["io.modelcontextprotocol/protocolVersion"]`.
A missing declaration is accepted so that older clients keep working. An unknown one is
refused. Set `HA_MCP_STRICT_META=1` to insist on it for every non-handshake request.

### Cancellation

`notifications/cancelled` is honoured: the answer to a cancelled request id is computed
and then discarded, so a client that gave up does not get a stale reply. Notifications
are never answered.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| The process exits immediately with status `2` | `HA_URL` or `HA_TOKEN` is missing or malformed. The stderr line names the variable and what it should look like. |
| Every tool says `unauthorized` (401) | The token is missing, expired or not a long-lived access token. |
| Every tool says `forbidden` (403) | Something is in front of Home Assistant that blocks the request, or a write was attempted. |
| `unreachable` | Wrong `HA_URL` (check scheme, host, port, and that it is the root URL, not `/api`), or Home Assistant is down. |
| `timeout` | The instance is slow. Raise `HA_MCP_TIMEOUT_SECS`, or narrow the call with a smaller `limit` or a filter. |
| TLS errors behind a self-signed certificate | Use a proper certificate, or set `HA_MCP_TLS_NO_VERIFY=1` on a trusted LAN. |
| Nothing useful on stderr | Set `HA_MCP_LOG_LEVEL=debug`; every request, tool call and HTTP failure is logged there, never on stdout. |

## Development

```sh
cargo test          # 155 tests, none of which need a network
cargo clippy --all-targets
cargo build --release
```

The test suite runs the real binary over pipes against a fake Home Assistant on a
loopback socket (`tests/common/mod.rs`), so it covers stdio framing, version rules,
pagination, cancellation and every tool's output shape without touching a home.

Layout:

| Path | Contents |
| --- | --- |
| `src/main.rs` | Entry point: configuration, logging, exit codes. |
| `src/lib.rs` | Startup wiring. |
| `src/config.rs` | Environment parsing, server metadata. |
| `src/transport.rs` | stdin reader, worker pool, single stdout writer, cancellation registry. |
| `src/mcp/session.rs` | Method dispatch, version rules, `tools/list`, `tools/call` result shapes. |
| `src/mcp/tools.rs` | The tool registry: descriptions, input and output schemas, annotations. |
| `src/mcp/handlers.rs` | Each tool's Home Assistant calls and projections. |
| `src/mcp/schema.rs`, `src/mcp/args.rs` | JSON Schema builders and argument validation. |
| `src/mcp/jsonrpc.rs`, `src/mcp/protocol.rs` | Message envelopes, ids, `_meta`, version constants. |
| `src/ha/` | The Home Assistant HTTP client and typed state/event models. |
| `src/error.rs`, `src/log.rs`, `src/util.rs`, `src/timestamp.rs` | API errors, stderr logging, cursors and pagination, ISO 8601 parsing. |

## Security notes

- Only `GET` requests leave this process, and only against `HA_URL`.
- The token is sent as `Authorization: Bearer <token>` and never logged, echoed or stored.
- Responses larger than `HA_MCP_MAX_RESPONSE_BYTES` are refused before they are parsed.
- `HA_MCP_TLS_NO_VERIFY` weakens transport security; use it only where the network already is your home.
