# Home Assistant REST API: quick reference

These notes were written against a slightly older Home Assistant release.
Most of the API is stable, but details may have changed since.

All requests need the header `Authorization: Bearer <token>` and return JSON.
The API is served under `/api/`.

## Status

`GET /api/`

Returns `{"message": "API running."}` when the API is up.

## Configuration

`GET /api/config`

Returns the current configuration: location, time zone, unit system,
version, loaded components, and so on.

## Entities

`GET /api/entities`

Returns an array of every entity with its current state. Each item has
`entity_id`, `state`, `attributes`, `last_changed`, and `last_updated`.

`GET /api/entities/<entity_id>`

Returns one entity in the same shape. Returns 404 if the entity doesn't
exist.

## Services

`GET /api/services/list`

Returns an array of service domains. Each item has `domain` and a
`services` object keyed by service name.

## Events

`GET /api/events`

Returns an array of event types and how many listeners each has.

## History

`GET /api/history/period/<timestamp>`

Returns state changes from `<timestamp>` (ISO 8601) until now, grouped by
entity. Add `?filter_entity_id=<entity_id>` to limit it to one entity.

## Errors

| Status | Meaning |
| --- | --- |
| 200 | Success |
| 400 | Bad request |
| 401 | Missing or invalid token |
| 404 | Not found |
| 405 | Method not allowed |
