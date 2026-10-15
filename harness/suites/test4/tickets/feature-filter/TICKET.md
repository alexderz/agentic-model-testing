# list_entities: filter by device class, and a count-only mode

Two things we keep needing from `list_entities`.

## 1. A `device_class` argument

- Type string, optional, default `""`.
- When it is not empty, only entities whose `device_class` attribute equals it match. The comparison
  ignores ASCII case (`"Temperature"` matches `temperature`). An entity without a device class never
  matches.
- `""` means no filter. It combines with `query`, `domain`, `state` and `only_available` (all must
  hold), and pagination works as before.

## 2. A `count_only` argument

- Type boolean, optional, default `false`.
- When `true`, the result keeps its usual fields but carries no entities: `entities` is `[]`,
  `returned` is `0` and `next_cursor` is `null`. `matched` is still the number of entities the
  filters select, and `total_entities` the number before filtering.
- When `false` or left out, nothing changes.

## For both

- They appear in the tool's `inputSchema` in `tools/list` with these types and defaults, and a value
  of the wrong type is rejected like any other bad argument.
- The result still matches the tool's `outputSchema`.
- The README's tool table mentions them.
- The new behaviour is covered by tests, and the existing tests still pass (`cargo test`).

Example: `{"device_class": "motion", "count_only": true}` answers "how many motion sensors are
there?" in one small reply.
