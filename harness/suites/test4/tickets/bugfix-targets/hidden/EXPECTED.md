# bugfix-targets: the defect and the correct answer

Reproduced on 2026-10-10 with the untouched project (`suites/test4/project`), built in
`localhost/bakeoff-agent` as evalbox and driven over stdio against the grading replay (port 8127).

`list_services` with `{"domain": "lock"}` returns three services:

| Service | `targets_entities` as shipped | Correct |
| --- | --- | --- |
| `lock.lock` | `false` | `true` |
| `lock.open` | `false` | `true` |
| `lock.unlock` | `false` | `true` |

Each of the three declares `"target": {"entity": [{"domain": ["lock"]}]}` in `/api/services`
(`lock.open` adds `"supported_features": [1]`), so the correct answer is `true` for all three.

Across the whole catalogue of the recorded installation (254 services in 64 domains):

- 177 services declare `target.entity`. Correct: `true`. As shipped: `false` for all 177.
- 73 services declare no `target`. Correct: `false`. As shipped: `false`.
- 4 services declare an empty target (`"target": {}`): `homeassistant.turn_on`, `turn_off`, `toggle`
  and `reload_config_entry`. Home Assistant accepts any entity, device or area for these, so `true`
  is the better answer, but `false` is defensible for a field described as "declares an entity
  target". The checks accept both. The reference solution answers `true`.

The project's own fixtures (`tests/common/mod.rs`) use the older shape, `target.entity_id`, and one
existing test asserts `true` for it. A fix that only swaps one key for the other therefore fails a
baseline test, which the grader counts as a regression, and the hidden check
`old_and_new_catalogue_shapes_both_work`.
