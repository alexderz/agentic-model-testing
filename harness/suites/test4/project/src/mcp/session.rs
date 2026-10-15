//! Protocol behaviour: what each method answers, independent of how bytes arrive.
//!
//! Nothing here touches stdin or stdout, which keeps the version rules, the
//! pagination of `tools/list` and the error shapes testable without a client.

use serde_json::{json, Map, Value};

use crate::config::Config;
use crate::ha::HaClient;
use crate::mcp::jsonrpc::{Incoming, ProtoError};
use crate::mcp::protocol::{
    self, capabilities, instructions, negotiate, server_info, DISCOVERABLE_VERSIONS,
};
use crate::mcp::tools;
use crate::util::truncate_chars;

/// The text block of a successful `tools/call` is capped at this many characters.
/// `structuredContent` carries the whole payload either way.
const MAX_CONTENT_CHARS: usize = 24_000;

/// The method name that starts the modern, stateless handshake.
pub const METHOD_DISCOVER: &str = "server/discover";
pub const METHOD_INITIALIZE: &str = "initialize";
pub const METHOD_PING: &str = "ping";
pub const METHOD_TOOLS_LIST: &str = "tools/list";
pub const METHOD_TOOLS_CALL: &str = "tools/call";

/// What the server should put on the wire for one incoming message.
#[derive(Debug)]
pub enum Reply {
    /// A successful `result` envelope.
    Result(Value),
    /// An `error` envelope.
    Error(ProtoError),
    /// Nothing at all: notifications and cancelled requests must stay silent.
    Silent,
}

impl Reply {
    /// The single stdout line for this reply, or `None` when nothing is sent.
    pub fn line(&self, id: Option<&crate::mcp::jsonrpc::Id>) -> Option<String> {
        match self {
            Reply::Result(result) => Some(crate::mcp::jsonrpc::result_line(id?, result.clone())),
            Reply::Error(error) => Some(crate::mcp::jsonrpc::error_line(id, error)),
            Reply::Silent => None,
        }
    }
}

/// A session holds the configuration and one HTTP client; it is stateless as far
/// as the protocol is concerned, so any request may arrive first.
pub struct Session {
    config: Config,
    client: HaClient,
}

impl Session {
    pub fn new(config: Config, client: HaClient) -> Session {
        Session { config, client }
    }

    /// Dispatches one parsed message.
    pub fn handle(&self, incoming: &Incoming) -> Reply {
        // A notification must never be answered, whatever its method.
        if incoming.is_notification() {
            crate::debug!(
                "notification {} from {}",
                incoming.method,
                incoming.meta.client_name()
            );
            return Reply::Silent;
        }

        let outcome =
            std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| self.dispatch(incoming)));
        match outcome {
            Ok(reply) => reply,
            Err(panic) => {
                let detail = panic_payload(&panic);
                crate::error!("{0} panicked: {1}", incoming.method, detail);
                Reply::Error(ProtoError::internal(format!(
                    "this server hit an internal error while handling {}: {detail}",
                    incoming.method
                )))
            }
        }
    }

    fn dispatch(&self, incoming: &Incoming) -> Reply {
        // The handshake carries its version in `params`; everything else declares
        // it in `_meta` and is refused when that declaration cannot be honoured.
        let handshake = matches!(
            incoming.method.as_str(),
            METHOD_INITIALIZE | METHOD_DISCOVER
        );
        if !handshake && !incoming.method.starts_with("notifications/") {
            if let Some(error) = self.check_meta(incoming) {
                return Reply::Error(error);
            }
        }

        match incoming.method.as_str() {
            METHOD_INITIALIZE => self.initialize(incoming),
            METHOD_DISCOVER => self.discover(incoming),
            METHOD_PING => Reply::Result(ok(json!({}))),
            METHOD_TOOLS_LIST => self.tools_list(incoming),
            METHOD_TOOLS_CALL => self.tools_call(incoming),
            "notifications/cancelled" => {
                // Recorded by the transport; nothing to answer.
                Reply::Silent
            }
            other => {
                if other.starts_with("notifications/") {
                    return Reply::Silent;
                }
                crate::debug!("unknown method {other}");
                Reply::Error(ProtoError::method_not_found(other))
            }
        }
    }

    /// `initialize`: the legacy handshake, answered without remembering anything.
    fn initialize(&self, incoming: &Incoming) -> Reply {
        let requested = incoming.str_param("protocolVersion");
        let negotiated = negotiate(requested);
        crate::info!(
            "initialize from {} claiming {requested:?}; answering {negotiated}",
            incoming.meta.client_name()
        );
        Reply::Result(ok(json!({
            "protocolVersion": negotiated,
            "capabilities": capabilities(),
            "serverInfo": server_info(),
            "instructions": instructions(),
        })))
    }

    /// `server/discover`: the modern replacement, which also states which
    /// revisions this server can speak.
    fn discover(&self, incoming: &Incoming) -> Reply {
        let requested = incoming.str_param("protocolVersion");
        let negotiated = negotiate(requested);
        crate::info!(
            "server/discover from {} claiming {requested:?}; answering {negotiated}",
            incoming.meta.client_name()
        );
        Reply::Result(ok(json!({
            "protocolVersion": negotiated,
            "supportedVersions": DISCOVERABLE_VERSIONS,
            "capabilities": capabilities(),
            "serverInfo": server_info(),
            "instructions": instructions(),
        })))
    }

    fn tools_list(&self, incoming: &Incoming) -> Reply {
        if let Some(cursor) = incoming.params.get("cursor") {
            if !cursor.is_string() {
                return Reply::Error(ProtoError::invalid_params(format!(
                    "\"cursor\" must be a string or absent, got {}",
                    crate::util::json_type(cursor)
                )));
            }
        }
        let cursor = incoming.str_param("cursor").unwrap_or("");
        let limit = self.config.tool_page_size;
        match tools::list_definitions(cursor, limit) {
            Ok(mut result) => {
                if let Some(object) = result.as_object_mut() {
                    object.insert("ttlMs".into(), json!(protocol::TOOL_LIST_TTL_MS));
                }
                let count = result["tools"].as_array().map_or(0, Vec::len);
                crate::debug!(
                    "tools/list returned {count} tools (cursor {:?})",
                    if cursor.is_empty() {
                        None
                    } else {
                        Some(cursor)
                    }
                );
                Reply::Result(ok(result))
            }
            Err(problem) => Reply::Error(ProtoError::invalid_params(problem)),
        }
    }

    fn tools_call(&self, incoming: &Incoming) -> Reply {
        let Some(name) = incoming
            .str_param("name")
            .filter(|name| !name.trim().is_empty())
        else {
            return Reply::Error(ProtoError::invalid_params(
                "\"params.name\" is required for tools/call and must be a non-empty string",
            ));
        };
        match incoming.params.get("arguments") {
            None | Some(Value::Null) => {}
            Some(Value::Object(_)) => {}
            Some(other) => {
                return Reply::Error(ProtoError::invalid_params(format!(
                    "\"params.arguments\" must be an object, got {} (send {{}} for a tool without arguments)",
                    crate::util::json_type(other)
                )));
            }
        }
        let arguments = incoming.params.get("arguments");

        let Some(tool) = tools::find(name) else {
            crate::debug!("tools/call for unknown tool {name}");
            return tool_error(name, &tools::CallError::Unknown(name.to_string()));
        };

        match tools::call(tool, arguments, &self.client) {
            Ok(structured) => Reply::Result(tool_result(name, &structured)),
            Err(error) => {
                crate::warn!(
                    "tools/call {name} failed ({}): {}",
                    error.kind(),
                    error.message()
                );
                tool_error(name, &error)
            }
        }
    }

    /// Applies the per-request version rule from `_meta`.
    ///
    /// Older clients send no `_meta` at all, so by default a missing version is
    /// accepted; `HA_MCP_STRICT_META` turns that into an error for deployments
    /// that want to insist on the 2026-07-28 rules.
    pub fn check_meta(&self, incoming: &Incoming) -> Option<ProtoError> {
        match incoming.meta.protocol_version.as_deref() {
            Some(version) if protocol::is_known(version) => None,
            Some(version) => Some(ProtoError::unsupported_version(
                version,
                protocol::KNOWN_VERSIONS,
            )),
            None if self.config.strict_meta && !incoming.meta.present => {
                Some(ProtoError::invalid_params(format!(
                    "this server runs with HA_MCP_STRICT_META, which requires \
                 params._meta.io.modelcontextprotocol/protocolVersion (one of {}); \
                 send it or unset HA_MCP_STRICT_META to accept older clients",
                    protocol::KNOWN_VERSIONS.join(", ")
                )))
            }
            None => None,
        }
    }
}

/// A result envelope body with the fields every MCP result carries.
fn ok(payload: Value) -> Value {
    let mut result = match payload {
        Value::Object(object) => object,
        other => {
            let mut object = Map::new();
            object.insert("value".into(), other);
            object
        }
    };
    result.insert("resultType".into(), json!("complete"));
    Value::Object(result)
}

/// The success shape of `tools/call`: the payload twice, once as JSON text for
/// clients that only read `content`, once as `structuredContent`.
fn tool_result(name: &str, structured: &Value) -> Value {
    let compact = serde_json::to_string(structured).unwrap_or_else(|_| "{}".to_string());
    let (text, clipped) = truncate_chars(&compact, MAX_CONTENT_CHARS);
    let text = if clipped {
        format!("{text} …truncated; ask for a smaller limit or a narrower filter")
    } else {
        text.to_string()
    };
    let mut result = Map::new();
    result.insert(
        "content".into(),
        json!([{ "type": "text", "text": text, "mimeType": "application/json" }]),
    );
    result.insert("structuredContent".into(), structured.clone());
    crate::debug!(
        "tools/call {name} succeeded ({} text chars)",
        text.chars().count()
    );
    result.insert("resultType".into(), json!("complete"));
    Value::Object(result)
}

/// The failure shape of `tools/call`: guidance for the model, not an error envelope.
fn tool_error(name: &str, error: &tools::CallError) -> Reply {
    let mut result = Map::new();
    result.insert(
        "content".into(),
        json!([{ "type": "text", "text": error.message() }]),
    );
    result.insert("isError".into(), json!(true));
    result.insert("resultType".into(), json!("complete"));
    let mut meta = Map::new();
    meta.insert("errorKind".into(), json!(error.kind()));
    if let Some(status) = match error {
        tools::CallError::Api(ha_error) => ha_error.status(),
        _ => None,
    } {
        meta.insert("httpStatus".into(), json!(status));
    }
    result.insert("_meta".into(), Value::Object(meta));
    crate::debug!("tools/call {name} reported {}", error.kind());
    Reply::Result(Value::Object(result))
}

fn panic_payload(payload: &Box<dyn std::any::Any + Send>) -> String {
    if let Some(text) = payload.downcast_ref::<&str>() {
        crate::util::one_line(text)
    } else if let Some(text) = payload.downcast_ref::<String>() {
        crate::util::one_line(text)
    } else {
        "unknown panic".to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::log::Level;
    use crate::mcp::jsonrpc::{code, error_line, parse_line, Id};

    fn session(strict_meta: bool) -> Session {
        let config = Config::from_lookup(|key| match key {
            "HA_URL" => Some("http://localhost:8123".into()),
            "HA_TOKEN" => Some("test-token".into()),
            "HA_MCP_STRICT_META" => Some(strict_meta.to_string()),
            _ => None,
        })
        .expect("test config");
        let client = HaClient::new(&config);
        Session::new(config, client)
    }

    fn reply(method: &str, params: Value) -> Reply {
        let line =
            json!({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).to_string();
        let incoming = parse_line(&line).expect("valid request");
        session(false).handle(&incoming)
    }

    fn result_of(method: &str, params: Value) -> Value {
        match reply(method, params) {
            Reply::Result(value) => value,
            other => panic!("expected a result, got {other:?}"),
        }
    }

    fn error_code(method: &str, params: Value) -> i32 {
        match reply(method, params) {
            Reply::Error(error) => error.code,
            other => panic!("expected an error, got {other:?}"),
        }
    }

    #[test]
    fn initialize_negotiates_and_describes_the_server() {
        let result = result_of(
            METHOD_INITIALIZE,
            json!({"protocolVersion": "2025-06-18", "capabilities": {}}),
        );
        assert_eq!(result["protocolVersion"], "2025-06-18");
        assert_eq!(result["capabilities"]["tools"]["listChanged"], false);
        assert_eq!(result["serverInfo"]["name"], crate::config::SERVER_NAME);
        assert!(result["instructions"]
            .as_str()
            .unwrap()
            .contains("get_instance_info"));
        assert_eq!(result["resultType"], "complete");

        let future = result_of(METHOD_INITIALIZE, json!({"protocolVersion": "2099-01-01"}));
        assert_eq!(
            future["protocolVersion"],
            protocol::LATEST_VERSION,
            "unknown versions fall back to ours"
        );
    }

    #[test]
    fn discover_lists_only_versions_it_really_speaks() {
        let result = result_of(
            METHOD_DISCOVER,
            json!({"protocolVersion": protocol::LATEST_VERSION}),
        );
        assert_eq!(result["protocolVersion"], protocol::LATEST_VERSION);
        assert_eq!(
            result["supportedVersions"].as_array().unwrap(),
            &vec![json!(protocol::LATEST_VERSION)]
        );
        assert!(result["capabilities"]["tools"].is_object());
    }

    #[test]
    fn ping_is_answered_and_notifications_are_not() {
        assert_eq!(result_of(METHOD_PING, json!({})), ok(json!({})));

        let notification =
            parse_line(r#"{"jsonrpc":"2.0","method":"notifications/initialized"}"#).unwrap();
        assert!(matches!(
            session(false).handle(&notification),
            Reply::Silent
        ));

        // Even a notification-shaped method that carries an id gets no answer.
        let odd = parse_line(r#"{"jsonrpc":"2.0","id":"7","method":"notifications/cancelled","params":{"requestId":"1"}}"#).unwrap();
        assert!(matches!(session(false).handle(&odd), Reply::Silent));
    }

    #[test]
    fn unknown_methods_get_method_not_found() {
        assert_eq!(
            error_code("resources/list", json!({})),
            code::METHOD_NOT_FOUND
        );
        assert_eq!(error_code("tools/calll", json!({})), code::METHOD_NOT_FOUND);
    }

    #[test]
    fn tools_list_pages_and_reports_caches() {
        let first = result_of(METHOD_TOOLS_LIST, json!({}));
        let names: Vec<&str> = first["tools"]
            .as_array()
            .unwrap()
            .iter()
            .map(|tool| tool["name"].as_str().unwrap())
            .collect();
        assert!(names.contains(&"get_entity"));
        assert_eq!(first["ttlMs"].as_u64(), Some(protocol::TOOL_LIST_TTL_MS));
        assert_eq!(first["resultType"], "complete");

        let second = result_of(METHOD_TOOLS_LIST, json!({"cursor": names_last_cursor()}));
        assert!(!second["tools"].as_array().unwrap().is_empty());

        assert_eq!(
            error_code(METHOD_TOOLS_LIST, json!({"cursor": 5})),
            code::INVALID_PARAMS
        );
        assert_eq!(
            error_code(METHOD_TOOLS_LIST, json!({"cursor": "nope"})),
            code::INVALID_PARAMS
        );
    }

    fn names_last_cursor() -> String {
        // Walk to the last page and hand back the cursor that ends the walk.
        let mut cursor = String::new();
        loop {
            let line = json!({"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"cursor":cursor,"limit":99}});
            let incoming = parse_line(&line.to_string()).unwrap();
            match session(false).handle(&incoming) {
                Reply::Result(value) => match value.get("nextCursor").and_then(Value::as_str) {
                    Some(next) if !next.is_empty() => cursor = next.to_string(),
                    _ => return cursor,
                },
                other => panic!("unexpected {other:?}"),
            }
        }
    }

    #[test]
    fn tools_call_validates_before_reaching_home_assistant() {
        // Unknown tool: a result the model can act on, not a protocol error.
        let unknown = match reply(
            METHOD_TOOLS_CALL,
            json!({"name": "turn_on", "arguments": {}}),
        ) {
            Reply::Result(value) => value,
            other => panic!("expected a result, got {other:?}"),
        };
        assert_eq!(unknown["isError"], true);
        assert!(unknown["content"][0]["text"]
            .as_str()
            .unwrap()
            .contains("tools/list"));
        assert_eq!(unknown["_meta"]["errorKind"], "unknown-tool");

        // Missing name is a structural mistake, so it is a protocol error.
        assert_eq!(
            error_code(METHOD_TOOLS_CALL, json!({"arguments": {}})),
            code::INVALID_PARAMS
        );
        assert_eq!(
            error_code(METHOD_TOOLS_CALL, json!({"name": "  ", "arguments": {}})),
            code::INVALID_PARAMS
        );
        assert_eq!(
            error_code(
                METHOD_TOOLS_CALL,
                json!({"name": "get_config", "arguments": "all"})
            ),
            code::INVALID_PARAMS
        );

        // Bad arguments come back as guidance, not as an error envelope.
        let rejected = match reply(
            METHOD_TOOLS_CALL,
            json!({"name": "get_entity", "arguments": {"limit": 3}}),
        ) {
            Reply::Result(value) => value,
            other => panic!("expected a result, got {other:?}"),
        };
        assert_eq!(rejected["isError"], true);
        let text = rejected["content"][0]["text"].as_str().unwrap();
        assert!(text.contains("entity_id"), "{text}");
        assert!(
            rejected.get("structuredContent").is_none(),
            "a failed call has no structure to show"
        );
    }

    #[test]
    fn a_missing_meta_version_is_accepted_unless_strict() {
        let lenient = parse_line(r#"{"jsonrpc":"2.0","id":1,"method":"ping"}"#).unwrap();
        assert!(session(false).check_meta(&lenient).is_none());

        let strict = session(true);
        let problem = strict
            .check_meta(&lenient)
            .expect("strict mode must complain");
        assert_eq!(problem.code, code::INVALID_PARAMS);
        assert!(problem.message.contains("HA_MCP_STRICT_META"));

        let modern = parse_line(
            &json!({"jsonrpc":"2.0","id":1,"method":"ping","params":{"_meta":{"io.modelcontextprotocol/protocolVersion": protocol::LATEST_VERSION}}}).to_string(),
        )
        .unwrap();
        assert!(
            strict.check_meta(&modern).is_none(),
            "a declared version satisfies strict mode"
        );
    }

    #[test]
    fn an_unknown_meta_version_is_rejected_with_the_supported_list() {
        let line = json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "ping",
            "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "1999-12-31"}}
        })
        .to_string();
        let incoming = parse_line(&line).unwrap();
        let problem = session(false).check_meta(&incoming).expect("must reject");
        assert_eq!(problem.code, code::UNSUPPORTED_PROTOCOL_VERSION);
        assert_eq!(problem.data.as_ref().unwrap()["requested"], "1999-12-31");
        assert!(problem.data.as_ref().unwrap()["supported"]
            .as_array()
            .unwrap()
            .contains(&json!(protocol::LATEST_VERSION)));
    }

    #[test]
    fn successful_tool_results_carry_both_views_of_the_payload() {
        let structured = json!({ "matched": 2, "returned": 2, "entities": [] });
        let result = tool_result("list_entities", &structured);
        assert_eq!(result["structuredContent"], structured);
        assert_eq!(result["content"][0]["type"], "text");
        assert_eq!(result["content"][0]["mimeType"], "application/json");
        assert_eq!(result["resultType"], "complete");
        assert!(result["isError"].is_null());
        let text = result["content"][0]["text"].as_str().unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(text).unwrap(),
            structured,
            "the text block is the same JSON"
        );
        assert!(!text.contains('\n'), "text must be one line");

        let huge = json!({ "lines": vec!["x".repeat(500); 200] });
        let capped = tool_result("get_error_log", &huge);
        let text = capped["content"][0]["text"].as_str().unwrap();
        assert!(text.ends_with("narrower filter"), "clipping must say so");
        assert!(text.chars().count() <= MAX_CONTENT_CHARS + 100);
        assert_eq!(
            capped["structuredContent"], huge,
            "structuredContent is never clipped"
        );
    }

    #[test]
    fn a_panicking_handler_becomes_an_internal_error_not_a_dead_server() {
        // Same path `handle` uses: a panic below the dispatch layer must still
        // produce a well-formed error envelope for the waiting request.
        let reply = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| -> Reply {
            panic!("boom");
        }))
        .unwrap_or_else(|payload| Reply::Error(ProtoError::internal(panic_payload(&payload))));
        match reply {
            Reply::Error(error) => {
                assert_eq!(error.code, code::INTERNAL_ERROR);
                assert!(error.message.contains("boom"));
                let line = error_line(Some(&Id::Number(9)), &error);
                let parsed: Value = serde_json::from_str(&line).unwrap();
                assert_eq!(parsed["error"]["code"], code::INTERNAL_ERROR);
            }
            other => panic!("expected an error, got {other:?}"),
        }
    }

    #[test]
    fn replies_render_to_exactly_one_line() {
        let id = Id::Number(4);
        let line = Reply::Result(ok(json!({"ok": true})))
            .line(Some(&id))
            .expect("a line");
        assert_eq!(line.lines().count(), 1);
        assert!(line.contains(r#""jsonrpc":"2.0""#));

        let line = Reply::Error(ProtoError::method_not_found("nope"))
            .line(Some(&id))
            .expect("a line");
        assert_eq!(line.lines().count(), 1);
        assert!(line.contains("-32601"));

        assert!(Reply::Silent.line(Some(&id)).is_none());
        assert!(
            Reply::Result(ok(json!({}))).line(None).is_none(),
            "notifications get no envelope"
        );
    }

    #[test]
    fn every_method_answer_carries_the_result_type() {
        for method in [METHOD_INITIALIZE, METHOD_DISCOVER, METHOD_PING] {
            let result = result_of(method, json!({"protocolVersion": protocol::LATEST_VERSION}));
            assert_eq!(result["resultType"], "complete", "{method}");
        }
    }

    #[test]
    fn level_logging_does_not_affect_replies() {
        crate::log::set_level(Level::Off);
        assert_eq!(result_of(METHOD_PING, json!({})), ok(json!({})));
        crate::log::set_level(Level::Debug);
    }
}
