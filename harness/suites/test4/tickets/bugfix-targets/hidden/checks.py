"""Hidden acceptance checks for ticket bugfix-targets. The agent never sees this file.

`list_services` must report `targets_entities: true` for every service that declares an entity
target, in the shape current Home Assistant publishes (`target.entity`, a list of filters) and in
the older shape the project's own fixtures use (`target.entity_id`), and `false` for a service that
declares no target at all. A service whose target is the empty object (`"target": {}`, four
services in the recorded installation) is not checked: both answers are defensible.
"""
from t4lib import CONFIG, FakeHA, Mcp, check, replay_json


def truth():
    """(domain, service) -> True / False / None (not checked), from the replay's own catalogue."""
    out = {}
    for entry in replay_json("/api/services"):
        for service, definition in entry["services"].items():
            target = definition.get("target")
            if target is None:
                want = False
            elif target.get("entity") or "entity_id" in target:
                want = True
            else:
                want = None
            out[(entry["domain"], service)] = want
    return out


def listed(mcp, args=None):
    rows, _ = mcp.call_all("list_services", args or {}, "services", 300)
    return {(r["domain"], r["service"]): r.get("targets_entities") for r in rows}


def lock_services_target_entities():
    with Mcp() as mcp:
        got = listed(mcp, {"domain": "lock"})
    check(sorted(s for _, s in got) == ["lock", "open", "unlock"], f"lock services listed: {sorted(got)}")
    wrong = {f"lock.{s}": v for (_, s), v in got.items() if v is not True}
    check(not wrong, f"targets_entities should be true for lock.lock, lock.open and lock.unlock; got {wrong}")


def every_entity_targeted_service_is_true():
    want = truth()
    with Mcp() as mcp:
        got = listed(mcp)
    expected = [k for k, v in want.items() if v is True]
    check(len(expected) > 100, f"the replay lists only {len(expected)} entity-targeted services")
    missing = [k for k in expected if k not in got]
    check(not missing, f"{len(missing)} services are missing from list_services, e.g. {missing[:3]}")
    wrong = [f"{d}.{s}" for d, s in expected if got[(d, s)] is not True]
    check(not wrong, f"{len(wrong)} of {len(expected)} entity-targeted services report targets_entities != true, "
                     f"e.g. {wrong[:5]}")


def services_without_a_target_stay_false():
    want = truth()
    with Mcp() as mcp:
        got = listed(mcp)
    expected = [k for k, v in want.items() if v is False]
    check(len(expected) > 20, f"the replay lists only {len(expected)} services without a target")
    wrong = [f"{d}.{s}" for d, s in expected if got.get((d, s)) is not False]
    check(not wrong, f"{len(wrong)} of {len(expected)} services without a target report targets_entities != false, "
                     f"e.g. {wrong[:5]}")


CATALOG = [
    {"domain": "light", "services": {
        "turn_on": {"name": "Turn on", "description": "Old catalogue shape.",
                    "target": {"entity_id": {"selector": {"entity": {"domain": ["light"]}}}}, "fields": {}},
        "turn_off": {"name": "Turn off", "description": "Old shape, empty selector.",
                     "target": {"entity_id": {}}, "fields": {}},
        "toggle": {"name": "Toggle", "description": "Current catalogue shape.",
                   "target": {"entity": [{"domain": ["light"]}]}, "fields": {}}}},
    {"domain": "lock", "services": {
        "open": {"name": "Open", "description": "Current shape with a feature filter.",
                 "target": {"entity": [{"domain": ["lock"], "supported_features": [1]}]},
                 "fields": {"code": {"example": 1234, "selector": {"text": {}}}}}}},
    {"domain": "homeassistant", "services": {
        "restart": {"name": "Restart", "description": "No target, no fields.", "fields": {}},
        "update_entity": {"name": "Update entity", "description": "An entity_id field, but no target.",
                          "fields": {"entity_id": {"required": True, "selector": {"entity": {"multiple": True}}}}}}},
]


def old_and_new_catalogue_shapes_both_work():
    with FakeHA({"/api/services": (200, CATALOG), "/api/config": (200, CONFIG)}) as ha:
        with Mcp(ha.url) as mcp:
            got = listed(mcp)
    want = {("light", "turn_on"): True, ("light", "turn_off"): True, ("light", "toggle"): True,
            ("lock", "open"): True, ("homeassistant", "restart"): False, ("homeassistant", "update_entity"): False}
    wrong = {f"{d}.{s}": got.get((d, s)) for (d, s), v in want.items() if got.get((d, s)) is not v}
    check(not wrong, f"wrong targets_entities (expected the opposite) for {wrong}")


CHECKS = [
    ("lock_services_target_entities", lock_services_target_entities),
    ("every_entity_targeted_service_is_true", every_entity_targeted_service_is_true),
    ("services_without_a_target_stay_false", services_without_a_target_stay_false),
    ("old_and_new_catalogue_shapes_both_work", old_and_new_catalogue_shapes_both_work),
]
