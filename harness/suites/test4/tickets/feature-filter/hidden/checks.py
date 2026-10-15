"""Hidden acceptance checks for ticket feature-filter. The agent never sees this file.

`list_entities` gains two arguments, exactly as TICKET.md specifies them:
  device_class  string, default ""    only entities whose device_class attribute equals it (ASCII
                                      case-insensitive); "" means no filter
  count_only    boolean, default false  when true: entities is [], returned is 0, next_cursor is
                                      null; matched and total_entities are computed as usual
The expected numbers are computed from the replay's own /api/states, not written down here.
"""
from t4lib import Mcp, check, replay_json


def states():
    return replay_json("/api/states")


def device_class(state):
    value = state["attributes"].get("device_class")
    return value.lower() if isinstance(value, str) else None


def schema_declares_both_arguments():
    with Mcp() as mcp:
        tool = next((t for t in mcp.tools() if t.get("name") == "list_entities"), None)
    check(tool is not None, "tools/list has no list_entities")
    schema = tool.get("inputSchema") or {}
    props = schema.get("properties") or {}
    for name, kind, default in (("device_class", "string", ""), ("count_only", "boolean", False)):
        check(name in props, f"list_entities inputSchema has no \"{name}\" property")
        check(props[name].get("type") == kind, f"{name}: type is {props[name].get('type')!r}, expected {kind!r}")
        check("default" in props[name] and props[name]["default"] == default
              and type(props[name]["default"]) is type(default),
              f"{name}: default is {props[name].get('default')!r}, expected {default!r}")
        check(name not in (schema.get("required") or []), f"{name} must be optional")


def device_class_filters_exactly():
    all_states = states()
    want = sorted(s["entity_id"] for s in all_states if device_class(s) == "temperature")
    check(len(want) > 3, "the replay has too few temperature entities for this check")
    with Mcp() as mcp:
        page = mcp.call("list_entities", {"device_class": "temperature", "limit": 200})
    check(page.get("matched") == len(want), f"matched is {page.get('matched')}, expected {len(want)}")
    check(page.get("total_entities") == len(all_states),
          f"total_entities is {page.get('total_entities')}, expected {len(all_states)} (it counts before filtering)")
    got = sorted(e["entity_id"] for e in page.get("entities") or [])
    check(got == want, f"returned {len(got)} entities, expected the {len(want)} with device_class temperature")
    bad = [e["entity_id"] for e in page["entities"] if e.get("device_class") != "temperature"]
    check(not bad, f"entities without device_class temperature were returned: {bad[:3]}")


def device_class_is_case_insensitive():
    want = sum(1 for s in states() if device_class(s) == "battery")
    with Mcp() as mcp:
        for spelling in ("BATTERY", "Battery"):
            page = mcp.call("list_entities", {"device_class": spelling, "limit": 200})
            check(page.get("matched") == want, f"device_class {spelling!r}: matched is {page.get('matched')}, expected {want}")


def empty_device_class_means_no_filter():
    total = len(states())
    with Mcp() as mcp:
        page = mcp.call("list_entities", {"device_class": ""})
        plain = mcp.call("list_entities", {})
    check(page.get("matched") == total, f"device_class \"\": matched is {page.get('matched')}, expected {total}")
    check(page.get("returned") == plain.get("returned") == 50, "the default page size must stay 50")


def unknown_device_class_matches_nothing():
    with Mcp() as mcp:
        page = mcp.call("list_entities", {"device_class": "no_such_device_class"})
    check(page.get("matched") == 0 and page.get("returned") == 0 and page.get("entities") == [],
          f"expected an empty result, got matched={page.get('matched')} returned={page.get('returned')}")
    check(page.get("next_cursor") is None, "next_cursor must be null on an empty result")


def device_class_combines_with_other_filters():
    all_states = states()
    with Mcp() as mcp:
        for args in ({"device_class": "battery", "domain": "sensor"},
                     {"device_class": "motion", "state": "off"},
                     {"device_class": "timestamp", "state": "unavailable"},
                     {"device_class": "temperature", "domain": "light"}):
            want = sum(1 for s in all_states
                       if device_class(s) == args["device_class"]
                       and ("domain" not in args or s["entity_id"].split(".")[0] == args["domain"])
                       and ("state" not in args or s["state"].lower() == args["state"]))
            page = mcp.call("list_entities", dict(args, limit=200))
            check(page.get("matched") == want, f"{args}: matched is {page.get('matched')}, expected {want}")


def device_class_pages_with_cursors():
    want = sorted(s["entity_id"] for s in states() if device_class(s) == "timestamp")
    check(len(want) > 25, "the replay has too few timestamp entities for this check")
    with Mcp() as mcp:
        items, first = mcp.call_all("list_entities", {"device_class": "timestamp"}, "entities", 20)
    check(first.get("returned") == 20 and first.get("next_cursor"), "the first page of 20 must carry a next_cursor")
    got = [e["entity_id"] for e in items]
    check(len(got) == len(set(got)), "paging returned an entity twice")
    check(sorted(got) == want, f"paging returned {len(got)} entities, expected {len(want)}")


def count_only_returns_counts_without_entities():
    total = len(states())
    with Mcp() as mcp:
        page = mcp.call("list_entities", {"count_only": True})
    check(page.get("matched") == total, f"matched is {page.get('matched')}, expected {total}")
    check(page.get("total_entities") == total, f"total_entities is {page.get('total_entities')}, expected {total}")
    check(page.get("entities") == [], f"entities must be an empty list, got {str(page.get('entities'))[:80]}")
    check(page.get("returned") == 0, f"returned is {page.get('returned')}, expected 0")
    check("next_cursor" in page and page["next_cursor"] is None, f"next_cursor must be null, got {page.get('next_cursor')!r}")


def count_only_respects_every_filter():
    all_states = states()
    cases = [
        ({"domain": "light"}, sum(1 for s in all_states if s["entity_id"].startswith("light."))),
        ({"state": "unavailable"}, sum(1 for s in all_states if s["state"] == "unavailable")),
        ({"device_class": "motion"}, sum(1 for s in all_states if device_class(s) == "motion")),
        ({"domain": "light", "state": "on"},
         sum(1 for s in all_states if s["entity_id"].startswith("light.") and s["state"] == "on")),
        ({"device_class": "battery", "domain": "sensor"},
         sum(1 for s in all_states if device_class(s) == "battery" and s["entity_id"].startswith("sensor."))),
    ]
    with Mcp() as mcp:
        for args, want in cases:
            page = mcp.call("list_entities", dict(args, count_only=True))
            check(page.get("matched") == want, f"count_only with {args}: matched is {page.get('matched')}, expected {want}")
            check(page.get("entities") == [] and page.get("returned") == 0,
                  f"count_only with {args}: entities must be [] and returned 0")


def count_only_false_changes_nothing():
    with Mcp() as mcp:
        explicit = mcp.call("list_entities", {"count_only": False})
        plain = mcp.call("list_entities", {})
    check(explicit.get("returned") == 50 and len(explicit.get("entities") or []) == 50,
          f"count_only false must return the normal page, got returned={explicit.get('returned')}")
    check(explicit.get("next_cursor"), "count_only false must keep next_cursor when more pages exist")
    check([e["entity_id"] for e in explicit["entities"]] == [e["entity_id"] for e in plain["entities"]],
          "count_only false must return the same page as leaving it out")


def wrong_argument_types_are_rejected():
    with Mcp() as mcp:
        check(mcp.call_fails("list_entities", {"device_class": 5}), "device_class: 5 (a number) was accepted")
        check(mcp.call_fails("list_entities", {"count_only": "yes"}), "count_only: \"yes\" (a string) was accepted")
        mcp.call("list_entities", {"device_class": "motion", "count_only": True})   # and the right types still work


CHECKS = [
    ("schema_declares_both_arguments", schema_declares_both_arguments),
    ("device_class_filters_exactly", device_class_filters_exactly),
    ("device_class_is_case_insensitive", device_class_is_case_insensitive),
    ("empty_device_class_means_no_filter", empty_device_class_means_no_filter),
    ("unknown_device_class_matches_nothing", unknown_device_class_matches_nothing),
    ("device_class_combines_with_other_filters", device_class_combines_with_other_filters),
    ("device_class_pages_with_cursors", device_class_pages_with_cursors),
    ("count_only_returns_counts_without_entities", count_only_returns_counts_without_entities),
    ("count_only_respects_every_filter", count_only_respects_every_filter),
    ("count_only_false_changes_nothing", count_only_false_changes_nothing),
    ("wrong_argument_types_are_rejected", wrong_argument_types_are_rejected),
]
