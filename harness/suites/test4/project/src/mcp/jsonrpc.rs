//! JSON-RPC 2.0 envelope handling for the stdio binding.
//!
//! Every outgoing message is produced here so that the "one compact JSON
//! object per line, no embedded newlines" rule of the stdio transport holds in
//! exactly one place.

use serde_json::{Map, Value};

/// JSON-RPC and MCP error codes used by this server.
pub mod code {
    pub const PARSE_ERROR: i32 = -32700;
    pub const INVALID_REQUEST: i32 = -32600;
    pub const METHOD_NOT_FOUND: i32 = -32601;
    pub const INVALID_PARAMS: i32 = -32602;
    pub const INTERNAL_ERROR: i32 = -32603;
    /// `UnsupportedProtocolVersionError` (MCP 2026-07-28).
    pub const UNSUPPORTED_PROTOCOL_VERSION: i32 = -32022;
}

/// A JSON-RPC request id. MCP forbids `null`, so it is not a variant.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum Id {
    Number(i64),
    Text(String),
}

impl Id {
    pub fn parse(value: &Value) -> Option<Id> {
        match value {
            Value::Number(number) => number.as_i64().map(Id::Number),
            Value::String(text) => Some(Id::Text(text.clone())),
            _ => None,
        }
    }

    pub fn to_value(&self) -> Value {
        match self {
            Id::Number(number) => Value::Number((*number).into()),
            Id::Text(text) => Value::String(text.clone()),
        }
    }
}

/// A JSON-RPC error object, plus the rules for the ones MCP names.
#[derive(Debug, Clone, PartialEq)]
pub struct ProtoError {
    pub code: i32,
    pub message: String,
    pub data: Option<Value>,
}

impl ProtoError {
    pub fn new(code: i32, message: impl Into<String>) -> ProtoError {
        ProtoError {
            code,
            message: message.into(),
            data: None,
        }
    }

    pub fn invalid_request(message: impl Into<String>) -> ProtoError {
        ProtoError::new(code::INVALID_REQUEST, message)
    }

    pub fn invalid_params(message: impl Into<String>) -> ProtoError {
        ProtoError::new(code::INVALID_PARAMS, message)
    }

    pub fn method_not_found(method: &str) -> ProtoError {
        ProtoError::new(
            code::METHOD_NOT_FOUND,
            format!("Method not found: {method}"),
        )
    }

    pub fn internal(message: impl Into<String>) -> ProtoError {
        ProtoError::new(code::INTERNAL_ERROR, message)
    }

    /// Tells the client which versions it may pick instead.
    pub fn unsupported_version(requested: &str, supported: &[&str]) -> ProtoError {
        ProtoError {
            code: code::UNSUPPORTED_PROTOCOL_VERSION,
            message: format!(
                "Unsupported protocol version: {requested}; this server speaks {}",
                supported.join(", ")
            ),
            data: Some(serde_json::json!({
                "requested": requested,
                "supported": supported,
            })),
        }
    }
}

/// Per-request protocol metadata carried in `params._meta`.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Meta {
    pub protocol_version: Option<String>,
    pub client_info: Option<Value>,
    pub present: bool,
}

impl Meta {
    fn from_params(params: &Map<String, Value>) -> Meta {
        let Some(value) = params.get("_meta").and_then(Value::as_object) else {
            return Meta::default();
        };
        Meta {
            protocol_version: value
                .get(PROTOCOL_VERSION_KEY)
                .and_then(Value::as_str)
                .map(str::to_string),
            client_info: value.get(CLIENT_INFO_KEY).cloned(),
            present: true,
        }
    }

    pub fn client_name(&self) -> &str {
        self.client_info
            .as_ref()
            .and_then(|info| info.get("name"))
            .and_then(Value::as_str)
            .unwrap_or("unknown-client")
    }
}

pub const PROTOCOL_VERSION_KEY: &str = "io.modelcontextprotocol/protocolVersion";
pub const CLIENT_INFO_KEY: &str = "io.modelcontextprotocol/clientInfo";
pub const SERVER_INFO_KEY: &str = "io.modelcontextprotocol/serverInfo";
pub const CANCELLED_METHOD: &str = "notifications/cancelled";

/// A client message that this server knows how to act on.
#[derive(Debug, Clone, PartialEq)]
pub struct Incoming {
    /// `None` marks a notification, which must never be answered.
    pub id: Option<Id>,
    pub method: String,
    pub params: Map<String, Value>,
    pub meta: Meta,
}

impl Incoming {
    pub fn is_notification(&self) -> bool {
        self.id.is_none()
    }

    /// `params.name`, used by `tools/call`.
    pub fn str_param(&self, key: &str) -> Option<&str> {
        self.params.get(key).and_then(Value::as_str)
    }
}

/// Parses one line of client input into an [`Incoming`].
///
/// Errors here are protocol errors: the caller answers with a JSON-RPC error
/// response (whose id is `null` when the id could not be read).
pub fn parse_line(line: &str) -> Result<Incoming, (Option<Id>, ProtoError)> {
    let document: Value = serde_json::from_str(line).map_err(|e| {
        (
            None,
            ProtoError::new(
                code::PARSE_ERROR,
                format!(
                    "Could not parse JSON: {}",
                    crate::util::one_line(&e.to_string())
                ),
            ),
        )
    })?;

    let mut object = match document {
        Value::Object(object) => object,
        other => {
            return Err((
                None,
                ProtoError::invalid_request(format!(
                    "a JSON-RPC message must be an object, got {}",
                    crate::util::json_type(&other)
                )),
            ))
        }
    };

    let id = match object.get("id") {
        None => None,
        Some(value) => Some(Id::parse(value).ok_or_else(|| {
            (
                None,
                ProtoError::invalid_request("request id must be a string or an integer"),
            )
        })?),
    };

    if let Some(version) = object.get("jsonrpc") {
        if version.as_str() != Some("2.0") {
            return Err((
                id.clone(),
                ProtoError::invalid_request("jsonrpc must be the string \"2.0\""),
            ));
        }
    }

    let Some(method) = object.remove("method").and_then(|m| match m {
        Value::String(text) if !text.is_empty() => Some(text),
        _ => None,
    }) else {
        return Err((
            id,
            ProtoError::invalid_request("a \"method\" string is required"),
        ));
    };

    let params = match object.remove("params") {
        None | Some(Value::Null) => Map::new(),
        Some(Value::Object(params)) => params,
        Some(other) => {
            return Err((
                id,
                ProtoError::invalid_params(format!(
                    "\"params\" must be an object, got {}",
                    crate::util::json_type(&other)
                )),
            ))
        }
    };
    let meta = Meta::from_params(&params);

    Ok(Incoming {
        id,
        method,
        params,
        meta,
    })
}

/// Serialises a successful result envelope.
pub fn result_line(id: &Id, result: Value) -> String {
    envelope(|body| {
        body.insert("id".into(), id.to_value());
        body.insert("result".into(), result);
    })
}

/// Serialises an error envelope. `id` is `null` when it could not be determined.
pub fn error_line(id: Option<&Id>, error: &ProtoError) -> String {
    envelope(|body| {
        body.insert("id".into(), id.map(Id::to_value).unwrap_or(Value::Null));
        let mut object = Map::new();
        object.insert("code".into(), error.code.into());
        object.insert("message".into(), error.message.clone().into());
        if let Some(data) = &error.data {
            object.insert("data".into(), data.clone());
        }
        body.insert("error".into(), Value::Object(object));
    })
}

fn envelope(build: impl FnOnce(&mut Map<String, Value>)) -> String {
    let mut body = Map::new();
    body.insert("jsonrpc".into(), Value::String("2.0".into()));
    build(&mut body);
    // Serialization cannot fail for these shapes; falling back keeps stdout valid.
    serde_json::to_string(&Value::Object(body)).unwrap_or_else(|_| {
        String::from(
            r#"{"jsonrpc":"2.0","error":{"code":-32603,"message":"Could not serialise response"}}"#,
        )
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_a_request_with_params_and_meta() {
        let incoming = parse_line(
            r#"{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"get_config","_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientInfo":{"name":"probe","version":"1"}}}}"#,
        )
        .expect("valid request");
        assert_eq!(incoming.id, Some(Id::Number(7)));
        assert_eq!(incoming.method, "tools/call");
        assert_eq!(incoming.str_param("name"), Some("get_config"));
        assert_eq!(
            incoming.meta.protocol_version.as_deref(),
            Some("2026-07-28")
        );
        assert_eq!(incoming.meta.client_name(), "probe");
        assert!(!incoming.is_notification());
    }

    #[test]
    fn treats_a_message_without_an_id_as_a_notification() {
        let incoming =
            parse_line(r#"{"jsonrpc":"2.0","method":"notifications/initialized"}"#).unwrap();
        assert!(incoming.is_notification());
        assert_eq!(incoming.meta, Meta::default());
    }

    #[test]
    fn accepts_the_legacy_shape_without_meta_or_jsonrpc() {
        let incoming = parse_line(r#"{"id":"abc","method":"ping"}"#).unwrap();
        assert_eq!(incoming.id, Some(Id::Text("abc".into())));
        assert!(!incoming.meta.present);
    }

    #[test]
    fn rejects_malformed_requests_with_the_right_codes() {
        assert_eq!(
            error_code_of(r#"{"jsonrpc":"2.0","id":1}"#),
            code::INVALID_REQUEST
        );
        assert_eq!(
            error_code_of(r#"{"jsonrpc":"2.0","id":1,"method":42}"#),
            code::INVALID_REQUEST
        );
        assert_eq!(
            error_code_of(r#"{"jsonrpc":"1.0","id":1,"method":"ping"}"#),
            code::INVALID_REQUEST
        );
        assert_eq!(
            error_code_of(r#"{"jsonrpc":"2.0","id":null,"method":"ping"}"#),
            code::INVALID_REQUEST
        );
        assert_eq!(
            error_code_of(r#"{"jsonrpc":"2.0","id":1,"method":"ping","params":[1,2]}"#),
            code::INVALID_PARAMS
        );
        // Valid JSON that is not a request object is an invalid request, not a
        // parse failure; batch messages are not part of MCP.
        assert_eq!(error_code_of(r#"[1,2,3]"#), code::INVALID_REQUEST);
        assert_eq!(error_code_of("not json at all"), code::PARSE_ERROR);
    }

    #[test]
    fn empty_method_is_not_a_valid_method() {
        assert_eq!(
            error_code_of(r#"{"jsonrpc":"2.0","id":1,"method":""}"#),
            code::INVALID_REQUEST
        );
    }

    #[test]
    fn result_envelope_is_a_single_line_correlated_by_id() {
        let line = result_line(&Id::Text("x/1".into()), serde_json::json!({ "ok": true }));
        assert_eq!(line.lines().count(), 1);
        let parsed: Value = serde_json::from_str(&line).unwrap();
        assert_eq!(parsed["jsonrpc"], "2.0");
        assert_eq!(parsed["id"], "x/1");
        assert_eq!(parsed["result"]["ok"], true);
        assert!(parsed.get("error").is_none());
    }

    #[test]
    fn error_envelope_carries_id_and_data() {
        let line = error_line(
            Some(&Id::Number(3)),
            &ProtoError::unsupported_version("2099-01-01", &["2026-07-28"]),
        );
        let parsed: Value = serde_json::from_str(&line).unwrap();
        assert_eq!(parsed["id"], 3);
        assert_eq!(parsed["error"]["code"], code::UNSUPPORTED_PROTOCOL_VERSION);
        assert_eq!(parsed["error"]["data"]["requested"], "2099-01-01");
        assert_eq!(parsed["error"]["data"]["supported"][0], "2026-07-28");
    }

    #[test]
    fn error_envelope_uses_a_null_id_when_the_id_is_unknown() {
        let line = error_line(None, &ProtoError::new(code::PARSE_ERROR, "nope"));
        let parsed: Value = serde_json::from_str(&line).unwrap();
        assert!(parsed["id"].is_null());
        assert_eq!(parsed["error"]["message"], "nope");
    }

    #[test]
    fn text_payloads_cannot_smuggle_extra_messages() {
        let line = result_line(
            &Id::Number(1),
            serde_json::json!({ "content": [{ "type": "text", "text": "line one\nline two" }] }),
        );
        assert_eq!(
            line.lines().count(),
            1,
            "framing must not contain a raw newline"
        );
        let parsed: Value = serde_json::from_str(&line).unwrap();
        assert_eq!(parsed["result"]["content"][0]["text"], "line one\nline two");
    }

    fn error_code_of(line: &str) -> i32 {
        match parse_line(line) {
            Err((_, error)) => error.code,
            Ok(incoming) => panic!("accepted {incoming:?}"),
        }
    }
}
