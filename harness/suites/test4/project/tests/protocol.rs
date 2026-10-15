//! Protocol behaviour of the real binary: handshake, version rules, notifications,
//! error envelopes and the stdio framing itself.

mod common;

use std::time::Duration;

use common::{request_without_params, tool_names, FakeHa, Message, TOKEN};
use serde_json::{json, Value};

const LATEST: &str = "2026-07-28";
const PARSE_ERROR: i64 = -32700;
const INVALID_REQUEST: i64 = -32600;
const METHOD_NOT_FOUND: i64 = -32601;
const INVALID_PARAMS: i64 = -32602;
const UNSUPPORTED_PROTOCOL_VERSION: i64 = -32022;

#[test]
fn initialize_and_discover_agree_on_who_the_server_is() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);

    let initialized = client.request(
        "initialize",
        json!({
            "protocolVersion": LATEST,
            "capabilities": {},
            "clientInfo": {"name": "integration-test", "version": "1"},
        }),
    );
    let result = initialized.expect_result("initialize");
    assert_eq!(result["protocolVersion"], LATEST);
    assert_eq!(result["resultType"], "complete");
    assert!(
        result["capabilities"]["tools"].is_object(),
        "a tools server must advertise tools"
    );
    assert!(result["serverInfo"]["name"]
        .as_str()
        .is_some_and(|name| !name.is_empty()));
    assert!(result["instructions"]
        .as_str()
        .is_some_and(|text| !text.is_empty()));

    let discovered = client.request("server/discover", json!({"protocolVersion": LATEST}));
    let discovered = discovered.expect_result("server/discover");
    assert_eq!(discovered["supportedVersions"], json!([LATEST]));
    assert_eq!(
        discovered["serverInfo"], result["serverInfo"],
        "both handshakes must describe the same server"
    );

    // A client claiming a revision the server does not know gets the newest one
    // it can speak, not an error: that is what `initialize` is for.
    let future = client.request_as(77, "initialize", json!({"protocolVersion": "2099-01-01"}));
    assert_eq!(
        future.expect_result("initialize with a future version")["protocolVersion"],
        LATEST
    );

    assert_eq!(
        client.close(),
        0,
        "the server must exit cleanly when stdin closes"
    );
}

#[test]
fn requests_may_arrive_in_any_order_because_the_server_is_stateless() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);

    let listed = client.request("tools/list", json!({}));
    assert_eq!(
        tool_names(&listed.expect_result("tools/list")).len(),
        12,
        "no initialize required"
    );

    let pinged = client.request("ping", Value::Null);
    assert_eq!(pinged.expect_result("ping")["resultType"], "complete");

    let late_handshake = client.request("initialize", json!({"protocolVersion": LATEST}));
    assert_eq!(
        late_handshake.expect_result("late initialize")["protocolVersion"],
        LATEST
    );
}

#[test]
fn a_request_may_come_without_a_params_member() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);
    client.send(&request_without_params(5, "ping"));
    let answered = client.recv("the ping answer");
    assert_eq!(answered["id"], 5);
    assert!(
        answered.get("error").is_none(),
        "ping needs no params: {}",
        answered["error"]
    );
}

#[test]
fn the_meta_version_rule_is_lenient_by_default_and_can_be_strict() {
    let fake = FakeHa::standard();
    let lenient = common::Client::start(&fake.url);

    // No `_meta` at all: accepted.
    let plain = lenient.request("tools/list", json!({}));
    assert!(plain.get("error").is_none(), "older clients must be served");
    // A version the server knows: accepted.
    let declared = lenient.request(
        "ping",
        json!({"_meta": {"io.modelcontextprotocol/protocolVersion": LATEST}}),
    );
    assert!(declared.get("error").is_none());
    // A version nobody has released: refused, and the message lists what is known.
    let bogus = lenient.request(
        "ping",
        json!({"_meta": {"io.modelcontextprotocol/protocolVersion": "2000-01-01"}}),
    );
    let error = bogus.expect_error("an unknown protocol version", UNSUPPORTED_PROTOCOL_VERSION);
    assert!(
        error["message"].as_str().unwrap().contains(LATEST),
        "the client should learn what to send"
    );

    let strict = common::Client::with_env(&fake.url, TOKEN, &[("HA_MCP_STRICT_META", "1")]);
    let missing = strict.request("ping", json!({}));
    let error = missing.expect_error("a missing version under HA_MCP_STRICT_META", INVALID_PARAMS);
    assert!(error["message"]
        .as_str()
        .unwrap()
        .contains("HA_MCP_STRICT_META"));
    let still_fine = strict.request(
        "ping",
        json!({"_meta": {"io.modelcontextprotocol/protocolVersion": LATEST}}),
    );
    assert!(still_fine.get("error").is_none());
}

#[test]
fn notifications_are_never_answered() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);

    client.notify("notifications/initialized", Value::Null);
    client.notify(
        "notifications/cancelled",
        json!({"requestId": 999, "reason": "the test does not care"}),
    );
    client.notify("notifications/unknown", json!({}));
    client.expect_silence(Duration::from_millis(300));

    // ...and the server is still healthy afterwards.
    let pinged = client.request("ping", Value::Null);
    assert_eq!(
        pinged.expect_result("ping after notifications")["resultType"],
        "complete"
    );
}

#[test]
fn malformed_and_non_object_messages_are_answered_with_jsonrpc_errors() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);

    client.send("this is not JSON");
    let unparseable = client.recv("a parse error");
    assert!(
        unparseable["id"].is_null(),
        "the id is unknown, so it stays null"
    );
    assert_eq!(unparseable["error"]["code"], PARSE_ERROR);

    client.send(r#"{"jsonrpc":"2.0","id":8,"method":"ping","unexpected":true}"#);
    // A well-formed request with an extra member is still a request.
    let extra_member = client.recv("the ping answer");
    assert_eq!(extra_member["id"], 8);

    // A message that omits `jsonrpc` is accepted as legacy; one that names the
    // wrong revision is not.
    client.send(r#"{"id":9,"method":"ping"}"#);
    assert_eq!(client.recv("a message without a jsonrpc member")["id"], 9);
    client.send(r#"{"jsonrpc":"1.0","id":13,"method":"ping"}"#);
    assert_eq!(
        client
            .recv("a wrong jsonrpc version")
            .expect_error("a wrong jsonrpc version", INVALID_REQUEST)["code"],
        INVALID_REQUEST
    );

    client.send(r#"[{"jsonrpc":"2.0","id":10,"method":"ping"}]"#);
    assert_eq!(
        client
            .recv("a batch request")
            .expect_error("a batch request", INVALID_REQUEST)["code"],
        INVALID_REQUEST,
        "this server speaks single messages only"
    );

    client.send(r#"{"jsonrpc":"2.0","id":11,"method":"ping",,}"#);
    assert_eq!(
        client
            .recv("trailing comma")
            .expect_error("trailing comma", PARSE_ERROR)["code"],
        PARSE_ERROR
    );

    let after = client.request("ping", Value::Null);
    assert_eq!(
        after.expect_result("ping after bad input")["resultType"],
        "complete"
    );
}

#[test]
fn blank_lines_between_messages_are_harmless() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);
    client.send("");
    client.send("   ");
    client.send(&request_without_params(12, "ping"));
    client.send("");
    let answered = client.recv("the ping answer");
    assert_eq!(answered["id"], 12);
    client.expect_silence(Duration::from_millis(200));
}

#[test]
fn unknown_methods_are_reported_as_method_not_found() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);
    let unknown = client.request("resources/list", json!({}));
    let error = unknown.expect_error("resources/list", METHOD_NOT_FOUND);
    assert!(error["message"]
        .as_str()
        .unwrap()
        .contains("resources/list"));
}

#[test]
fn tools_list_pages_with_opaque_cursors() {
    let fake = FakeHa::standard();
    let client = common::Client::with_env(&fake.url, TOKEN, &[("HA_MCP_TOOL_PAGE_SIZE", "5")]);

    let first = client
        .request("tools/list", json!({}))
        .expect_result("first page");
    assert_eq!(first["tools"].as_array().unwrap().len(), 5);
    assert_eq!(first["ttlMs"].as_u64().unwrap(), 3_600_000);
    let cursor = first["nextCursor"]
        .as_str()
        .expect("a first page must point at a second");

    let second = client
        .request("tools/list", json!({"cursor": cursor}))
        .expect_result("second page");
    assert_eq!(second["tools"].as_array().unwrap().len(), 5);
    let cursor = second["nextCursor"]
        .as_str()
        .expect("a second page must point at a third");

    let third = client
        .request("tools/list", json!({"cursor": cursor}))
        .expect_result("third page");
    assert_eq!(third["tools"].as_array().unwrap().len(), 2);
    assert!(
        third.get("nextCursor").is_none(),
        "the last page must not advertise a cursor"
    );
    assert!(third["resultType"] == "complete");

    let names: Vec<String> = common::all_tools(&client)
        .iter()
        .map(|tool| tool["name"].as_str().unwrap().to_string())
        .collect();
    assert_eq!(names.len(), 12, "paging must not lose or repeat tools");
    let mut sorted = names.clone();
    sorted.sort();
    assert_eq!(names, sorted, "tools must be listed in a stable order");
    for tool in common::all_tools(&client) {
        assert!(tool["description"]
            .as_str()
            .is_some_and(|text| !text.is_empty()));
        assert!(tool["inputSchema"]["type"] == "object");
        assert!(tool["outputSchema"]["type"] == "object");
    }
}

#[test]
fn a_cursor_that_is_not_a_string_is_a_protocol_error() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);

    let numeric = client.request("tools/list", json!({"cursor": 4}));
    numeric.expect_error("a numeric cursor", INVALID_PARAMS);
    let forged = client.request("tools/list", json!({"cursor": "not-a-cursor"}));
    let error = forged.expect_error("a forged cursor", INVALID_PARAMS);
    assert!(error["message"].as_str().unwrap().contains("cursor"));
}

#[test]
fn a_missing_tool_name_is_a_protocol_error_but_an_unknown_tool_is_not() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);

    client
        .request("tools/call", json!({"arguments": {}}))
        .expect_error("a call without a name", INVALID_PARAMS);
    client
        .request("tools/call", json!({"name": "  ", "arguments": {}}))
        .expect_error("a call with a blank name", INVALID_PARAMS);
    client
        .request(
            "tools/call",
            json!({"name": "get_config", "arguments": ["light.living_room"]}),
        )
        .expect_error("arguments that are not an object", INVALID_PARAMS);

    // An unknown tool is a *tool* failure: the call itself was well formed.
    let unknown = client.request(
        "tools/call",
        json!({"name": "turn_on_the_lights", "arguments": {}}),
    );
    let result = unknown.expect_tool_error("an unknown tool");
    assert_eq!(result["_meta"]["errorKind"], "unknown-tool");
    assert!(
        unknown.text().contains("tools/list"),
        "the client should be pointed at tools/list"
    );
}

#[test]
fn cancelling_a_request_silences_its_answer() {
    // A deliberately slow entity lookup, so the cancellation lands first.
    let fake = FakeHa::start(
        TOKEN,
        vec![(
            "/api/states/light.living_room",
            common::Response::ok(common::entity("light.living_room"))
                .delayed(Duration::from_millis(600)),
        )],
    );
    let client = common::Client::start(&fake.url);

    client.send(
        &json!({
            "jsonrpc": "2.0", "id": 4242, "method": "tools/call",
            "params": {"name": "get_entity", "arguments": {"entity_id": "light.living_room"}}
        })
        .to_string(),
    );
    std::thread::sleep(Duration::from_millis(80));
    client.notify(
        "notifications/cancelled",
        json!({"requestId": 4242, "reason": "the user pressed escape"}),
    );

    // The server keeps serving other requests while the slow one is in flight.
    let pinged = client.request("ping", Value::Null);
    assert_eq!(
        pinged.expect_result("ping during a slow tool call")["resultType"],
        "complete"
    );

    client.expect_silence(Duration::from_millis(900));
    assert!(
        client.log_mentions("cancelled"),
        "the log should mention the dropped answer:\n{}",
        client.stderr_text()
    );
}

#[test]
fn many_requests_in_flight_all_get_exactly_one_answer() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);

    let total = 40i64;
    for id in 1..=total {
        client.send(&json!({"jsonrpc": "2.0", "id": id, "method": "ping"}).to_string());
    }
    let mut ids: Vec<i64> = Vec::new();
    for _ in 1..=total {
        let message = client.recv("a ping answer");
        assert!(
            message.get("_unparsable").is_none(),
            "stdout must carry nothing but JSON-RPC: {:?}",
            message["_unparsable"]
        );
        assert!(
            message["result"]["resultType"] == "complete",
            "every ping must succeed: {message}"
        );
        ids.push(message["id"].as_i64().expect("a numeric id"));
    }
    ids.sort_unstable();
    assert_eq!(
        ids,
        (1..=total).collect::<Vec<i64>>(),
        "no answer may be lost or duplicated"
    );
}

#[test]
fn missing_configuration_stops_the_server_before_it_serves_anything() {
    // Exit code 2 is the documented "bad configuration" signal.
    common::Client::without_configuration().expect_exit_code(2);
}

#[test]
fn the_token_never_reaches_stdout_or_the_log() {
    let fake = FakeHa::standard();
    let client = common::Client::with_env(
        &fake.url,
        "super-secret-token",
        &[("HA_MCP_LOG_LEVEL", "debug")],
    );
    client.request("initialize", json!({"protocolVersion": LATEST}));
    client.request("tools/list", json!({}));
    client.request(
        "tools/call",
        json!({"name": "get_instance_info", "arguments": {}}),
    );

    let output = client.stderr_text();
    assert!(
        !output.contains("super-secret-token"),
        "the log leaked the token:\n{output}"
    );
    assert!(
        !client.has_pending(),
        "only messages asked for may appear on stdout"
    );
}

#[test]
fn the_stdin_writer_survives_a_request_that_home_assistant_cannot_answer() {
    // The fake answers only `/api/config`; everything else 404s like the fixture.
    let fake = FakeHa::start(
        TOKEN,
        vec![("/api/config", common::Response::ok(common::config()))],
    );
    let client = common::Client::start(&fake.url);

    let failed = client.request(
        "tools/call",
        json!({"name": "list_entities", "arguments": {}}),
    );
    let result = failed.expect_tool_error("list_entities against a 404");
    assert_eq!(result["_meta"]["errorKind"], "not-found");
    assert_eq!(result["_meta"]["httpStatus"], 404);

    let healthy = client.request("tools/call", json!({"name": "get_config", "arguments": {}}));
    assert!(
        healthy.get("error").is_none(),
        "one dead endpoint must not break the session"
    );
}
