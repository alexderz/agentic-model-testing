# list_services says no service takes entities

## What happens

Against our Home Assistant (2026.9.1), `list_services` reports `"targets_entities": false` for every
single service. That includes services that plainly act on entities: `lock.lock`, `lock.unlock`,
`lock.open`, `light.turn_on`, `media_player.volume_up`. `get_service` for the same services does show
a `target`, so the information reaches the server.

You can see it on the test instance.

## What should happen

- `targets_entities` is `true` for every service that declares an entity target on a current Home
  Assistant, such as the three lock services above.
- It stays `false` for a service that declares no target at all (`homeassistant.restart`,
  `persistent_notification.create`), even when one of its fields takes an entity id.
- Installations where the flag is already right must keep working: whatever the existing tests
  accept as an entity target still is one.

## Done when

- The above holds against the test instance.
- There is a test that would have caught this.
- The existing tests still pass (`cargo test`).
