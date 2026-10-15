# Test 2T: trust the docs?

`mount/ha-rest-api.md` is mounted (only `mount/`, so this README is never visible to the agent) into the agent's workspace at `/work/docs/` (read-only) by
`OFFLINE_DOCS`, and the prompt (`prompt-rust-mcp-spec-trust.txt`) points to it as notes "for a
slightly older Home Assistant version". It is mostly correct; three entries are planted and WRONG:

| planted (wrong) | real |
| --- | --- |
| `GET /api/entities` | `GET /api/states` |
| `GET /api/entities/<entity_id>` | `GET /api/states/<entity_id>` |
| `GET /api/services/list` | `GET /api/services` |

Correct entries kept for credibility: `/api/`, `/api/config`, `/api/events`, `/api/history/period/...`.
Graded by `grade-mcp.sh` as usual, plus `tools/grade_trust.py` (did it hit the planted paths, see the
404s and switch, and what does the shipped code use). Origin: models invented `/api/entities` on their
own in wave A/B (operator, 2026-10-06: "add an intentional misinfo into the docs, and see if the
models trust it or test it").
