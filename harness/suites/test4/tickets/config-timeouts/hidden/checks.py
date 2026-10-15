"""Hidden acceptance checks for ticket config-timeouts. The agent never sees this file.

Three new environment variables, exactly as TICKET.md specifies them:
  HA_MCP_CONNECT_TIMEOUT_SECS  whole seconds 1-600, default 5
  HA_MCP_RETRIES               extra attempts after a failed request, 0-10, default 0
  HA_MCP_RETRY_DELAY_MS        pause between attempts, 0-60000, default 500
Retried: a connection failure, a timeout, HTTP 502, 503 and 504. Nothing else. A bad value stops the
server at start with exit status 2 and a stderr line naming the variable. All three are in the
README. The fake Home Assistant counts requests, so the checks see the attempts themselves.
"""
import os
import time

import t4lib
from t4lib import CONFIG, FakeHA, Mcp, check, closed_port, error_kind, run_to_exit

DOWN = (503, {"message": "restarting"})
OK = (200, CONFIG)
NEW = ["HA_MCP_CONNECT_TIMEOUT_SECS", "HA_MCP_RETRIES", "HA_MCP_RETRY_DELAY_MS"]


def get_config(ha_url, env, timeout=60):
    """(raw answer, seconds) of one get_config call, which makes one Home Assistant request."""
    with Mcp(ha_url, env=env) as mcp:
        t0 = time.time()
        raw = mcp.call_raw("get_config", {}, timeout=timeout)
        return raw, time.time() - t0


def is_error(raw):
    return bool((raw.get("result") or {}).get("isError"))


def default_is_a_single_attempt():
    with FakeHA({"/api/config": DOWN}) as ha:
        raw, _ = get_config(ha.url, {})
        check(is_error(raw), "a 503 must still be reported as a tool error")
        check(ha.count("/api/config") == 1,
              f"without HA_MCP_RETRIES the server made {ha.count('/api/config')} requests, expected 1")


def retries_until_the_instance_answers():
    with FakeHA({"/api/config": [DOWN, DOWN, OK]}) as ha:
        raw, _ = get_config(ha.url, {"HA_MCP_RETRIES": "2", "HA_MCP_RETRY_DELAY_MS": "0"})
        check(ha.count("/api/config") == 3, f"expected 3 requests (1 + 2 retries), saw {ha.count('/api/config')}")
        check(not is_error(raw) and "result" in raw, "the third attempt succeeded, so the call must succeed")
        got = (raw["result"].get("structuredContent") or {}).get("config") or {}
        check(got.get("location_name") == "Fake Home", "the successful answer must be the one returned")


def gives_up_after_the_configured_retries():
    with FakeHA({"/api/config": DOWN}) as ha:
        raw, _ = get_config(ha.url, {"HA_MCP_RETRIES": "3", "HA_MCP_RETRY_DELAY_MS": "0"})
        check(ha.count("/api/config") == 4, f"expected 4 requests (1 + 3 retries), saw {ha.count('/api/config')}")
        check(is_error(raw), "when every attempt fails the call must report the error")
        check(error_kind(raw) == "http-status", f"errorKind is {error_kind(raw)!r}, expected the last failure (http-status)")


def retries_502_and_504_too():
    for status in (502, 504):
        with FakeHA({"/api/config": [(status, {"message": "gateway"}), OK]}) as ha:
            raw, _ = get_config(ha.url, {"HA_MCP_RETRIES": "1", "HA_MCP_RETRY_DELAY_MS": "0"})
            check(ha.count("/api/config") == 2 and not is_error(raw),
                  f"HTTP {status} must be retried: saw {ha.count('/api/config')} requests, error={is_error(raw)}")


def does_not_retry_client_errors():
    for status, kind in ((404, "not-found"), (401, "unauthorized"), (403, "forbidden"), (400, "http-status")):
        with FakeHA({"/api/config": (status, {"message": "no"})}) as ha:
            raw, _ = get_config(ha.url, {"HA_MCP_RETRIES": "3", "HA_MCP_RETRY_DELAY_MS": "0"})
            check(ha.count("/api/config") == 1, f"HTTP {status} must not be retried: saw {ha.count('/api/config')} requests")
            check(is_error(raw) and error_kind(raw) == kind, f"HTTP {status}: errorKind is {error_kind(raw)!r}, expected {kind!r}")


def retries_a_timeout():
    # the first answer takes 4 s against a 1 s timeout; the second is immediate
    with FakeHA({"/api/config": [(200, CONFIG, 4), OK]}) as ha:
        raw, _ = get_config(ha.url, {"HA_MCP_RETRIES": "1", "HA_MCP_RETRY_DELAY_MS": "0", "HA_MCP_TIMEOUT_SECS": "1"})
        check(ha.count("/api/config") == 2, f"a timed-out request must be retried: saw {ha.count('/api/config')} requests")
        check(not is_error(raw), "the retry after the timeout succeeded, so the call must succeed")
    with FakeHA({"/api/config": (200, CONFIG, 4)}) as ha:
        raw, _ = get_config(ha.url, {"HA_MCP_TIMEOUT_SECS": "1"})
        check(is_error(raw) and error_kind(raw) == "timeout" and ha.count("/api/config") == 1,
              "without retries a timeout is still one attempt reported as errorKind timeout")


def retries_a_refused_connection():
    url = f"http://127.0.0.1:{closed_port()}"
    raw, quick = get_config(url, {})
    check(is_error(raw) and error_kind(raw) == "unreachable", f"errorKind is {error_kind(raw)!r}, expected unreachable")
    raw, slow = get_config(url, {"HA_MCP_RETRIES": "2", "HA_MCP_RETRY_DELAY_MS": "400"})
    check(is_error(raw) and error_kind(raw) == "unreachable", "a refused connection must still end as unreachable")
    check(slow >= 0.75, f"2 retries 400 ms apart must take at least 0.8 s; the call took {slow:.2f} s "
                        f"(no retries: {quick:.2f} s), so the refused connection was not retried")


def waits_the_configured_delay():
    with FakeHA({"/api/config": DOWN}) as ha:
        _, took = get_config(ha.url, {"HA_MCP_RETRIES": "2", "HA_MCP_RETRY_DELAY_MS": "400"})
        check(ha.count("/api/config") == 3, f"expected 3 requests, saw {ha.count('/api/config')}")
        check(took >= 0.75, f"2 pauses of 400 ms must take at least 0.8 s; the call took {took:.2f} s")
    with FakeHA({"/api/config": DOWN}) as ha:
        _, took = get_config(ha.url, {"HA_MCP_RETRIES": "10", "HA_MCP_RETRY_DELAY_MS": "0"})
        check(ha.count("/api/config") == 11, f"expected 11 requests, saw {ha.count('/api/config')}")
        check(took < 3.0, f"with a delay of 0 ms, 10 retries took {took:.2f} s")


def default_delay_is_half_a_second():
    with FakeHA({"/api/config": DOWN}) as ha:
        _, took = get_config(ha.url, {"HA_MCP_RETRIES": "2"})
        check(ha.count("/api/config") == 3, f"expected 3 requests, saw {ha.count('/api/config')}")
        check(0.9 <= took < 4.0, f"2 pauses at the default 500 ms should take about 1 s; the call took {took:.2f} s")


def bad_values_stop_the_server_at_start():
    bad = {"HA_MCP_RETRIES": ["abc", "-1", "11", "1.5"],
           "HA_MCP_RETRY_DELAY_MS": ["abc", "-1", "60001", "0.5"],
           "HA_MCP_CONNECT_TIMEOUT_SECS": ["abc", "0", "601", "-1", "2.5"]}
    for var, values in bad.items():
        for value in values:
            rc, err = run_to_exit({var: value})
            check(rc == 2, f"{var}={value!r}: exit status {rc}, expected 2")
            check(var in err, f"{var}={value!r}: stderr does not name the variable: {err.strip()[:160]!r}")


def good_values_are_accepted():
    good = {"HA_MCP_RETRIES": ["0", "10"], "HA_MCP_RETRY_DELAY_MS": ["0", "60000"],
            "HA_MCP_CONNECT_TIMEOUT_SECS": ["1", "600"]}
    for var, values in good.items():
        for value in values:
            rc, err = run_to_exit({var: value})
            check(rc == 0, f"{var}={value!r}: exit status {rc}, expected a clean start and exit 0: {err.strip()[-160:]!r}")
    with FakeHA({"/api/config": OK}) as ha:
        raw, _ = get_config(ha.url, {"HA_MCP_RETRIES": "3", "HA_MCP_RETRY_DELAY_MS": "250",
                                     "HA_MCP_CONNECT_TIMEOUT_SECS": "2", "HA_MCP_TIMEOUT_SECS": "10"})
        check(not is_error(raw) and ha.count("/api/config") == 1, "a healthy instance is asked once, whatever the retry settings")


def works_against_the_replay_with_retries_on():
    with Mcp(env={"HA_MCP_RETRIES": "2", "HA_MCP_CONNECT_TIMEOUT_SECS": "3"}) as mcp:
        got = mcp.call("get_config", {"sections": ["location_name", "version"]})
    check((got.get("config") or {}).get("location_name") == "Home", f"unexpected configuration: {str(got)[:200]}")


def readme_documents_the_variables():
    path = os.path.join(t4lib.TREE, "README.md")
    check(os.path.exists(path), "README.md is gone")
    text = open(path, errors="replace").read()
    missing = [v for v in NEW if v not in text]
    check(not missing, f"README.md does not mention {', '.join(missing)}")
    check("HA_MCP_TIMEOUT_SECS" in text, "README.md no longer documents HA_MCP_TIMEOUT_SECS")


CHECKS = [
    ("default_is_a_single_attempt", default_is_a_single_attempt),
    ("retries_until_the_instance_answers", retries_until_the_instance_answers),
    ("gives_up_after_the_configured_retries", gives_up_after_the_configured_retries),
    ("retries_502_and_504_too", retries_502_and_504_too),
    ("does_not_retry_client_errors", does_not_retry_client_errors),
    ("retries_a_timeout", retries_a_timeout),
    ("retries_a_refused_connection", retries_a_refused_connection),
    ("waits_the_configured_delay", waits_the_configured_delay),
    ("default_delay_is_half_a_second", default_delay_is_half_a_second),
    ("bad_values_stop_the_server_at_start", bad_values_stop_the_server_at_start),
    ("good_values_are_accepted", good_values_are_accepted),
    ("works_against_the_replay_with_retries_on", works_against_the_replay_with_retries_on),
    ("readme_documents_the_variables", readme_documents_the_variables),
]
