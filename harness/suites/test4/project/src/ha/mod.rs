//! Thin, deliberately read-only client for the Home Assistant REST API.
//!
//! Only `GET` is ever issued. Every call funnels through [`HaClient::fetch`],
//! which applies the shared auth header, the response size cap and the timeout,
//! and converts whatever went wrong into a [`HaError`] with an actionable hint.

pub mod model;

use std::io::Read;
use std::time::Duration;

use serde_json::Value;
use ureq::config::Config as HttpConfig;
use ureq::tls::TlsConfig;
use ureq::Agent;

use crate::config::Config;
use crate::error::HaError;
use crate::util::{one_line, percent_encode, truncate_chars};
use model::{EventTypeInfo, State};

/// Longest error snippet copied out of a Home Assistant response body.
const MAX_DETAIL_CHARS: usize = 300;

#[derive(Debug, Clone)]
pub struct HaClient {
    agent: Agent,
    base_url: String,
    token: String,
    max_bytes: usize,
    timeout: Duration,
}

impl HaClient {
    pub fn new(config: &Config) -> HaClient {
        let tls = TlsConfig::builder().disable_verification(config.tls_no_verify);
        let connect_timeout = config.request_timeout.min(Duration::from_secs(5));
        let http = HttpConfig::builder()
            // Status codes are inspected by hand so the response body can be
            // quoted back to the caller instead of being swallowed.
            .http_status_as_error(false)
            .timeout_global(Some(config.request_timeout))
            .timeout_connect(Some(connect_timeout))
            .tls_config(tls.build());
        HaClient {
            agent: Agent::new_with_config(http.build()),
            base_url: config.base_url.clone(),
            token: config.token.clone(),
            max_bytes: config.max_response_bytes,
            timeout: config.request_timeout,
        }
    }

    /// `GET {base}/api` — the API liveness probe. Reply text is `"API running."`.
    /// Home Assistant answers `GET /api/` with `{"message": "API running."}`;
    /// the message alone is what a caller wants to see.
    pub fn api_status(&self) -> Result<String, HaError> {
        let body = self.get_text("/api/")?;
        Ok(match serde_json::from_str::<Value>(&body) {
            Ok(document) => document
                .get("message")
                .and_then(Value::as_str)
                .map(str::to_string)
                .unwrap_or_else(|| one_line(&body)),
            Err(_) => one_line(&body),
        })
    }

    /// `GET /api/config`: the whole configuration object, verbatim.
    pub fn configuration(&self) -> Result<Value, HaError> {
        self.get_parsed("/api/config")
    }

    /// `GET /api/states`: every entity's current state.
    pub fn states(&self) -> Result<Vec<State>, HaError> {
        self.get_parsed("/api/states")
    }

    /// `GET /api/states/{entity_id}` for one entity.
    pub fn state(&self, entity_id: &str) -> Result<State, HaError> {
        self.get_parsed(&format!("/api/states/{}", percent_encode(entity_id)))
    }

    /// `GET /api/services`: the service catalog, verbatim.
    pub fn service_catalog(&self) -> Result<Value, HaError> {
        self.get_parsed("/api/services")
    }

    /// `GET /api/events`: event types with listener counts.
    pub fn event_types(&self) -> Result<Vec<EventTypeInfo>, HaError> {
        self.get_parsed("/api/events")
    }

    /// `GET /api/logbook`, optionally narrowed to a window. Home Assistant
    /// ignores filters it does not understand, so callers may still need to
    /// narrow the result set themselves.
    pub fn logbook(
        &self,
        start_time: Option<&str>,
        end_time: Option<&str>,
    ) -> Result<Vec<Value>, HaError> {
        let query = logbook_query(start_time, end_time);
        self.get_parsed(&format!("/api/logbook{query}"))
    }

    /// `GET /api/error_log`: the raw error log as text.
    pub fn error_log(&self) -> Result<String, HaError> {
        self.get_text("/api/error_log")
    }

    /// `GET` a JSON document and deserialize it into a typed value.
    fn get_parsed<T: serde::de::DeserializeOwned>(&self, api_path: &str) -> Result<T, HaError> {
        let url = self.base_url.clone() + api_path;
        let body = self.fetch(&url, "application/json")?;
        serde_json::from_str(&body).map_err(|e| HaError::InvalidResponse {
            url,
            reason: format!("expected a JSON document: {}", one_line(&e.to_string())),
        })
    }

    /// `GET` a document and hand back the text as-is.
    fn get_text(&self, api_path: &str) -> Result<String, HaError> {
        let url = self.base_url.clone() + api_path;
        self.fetch(&url, "*/*")
    }

    /// The single HTTP entry point: auth header, size cap, status handling.
    fn fetch(&self, url: &str, accept: &str) -> Result<String, HaError> {
        crate::debug!("GET {url}");
        let response = self
            .agent
            .get(url)
            .header("Authorization", format!("Bearer {}", self.token))
            .header("Accept", accept)
            .header(
                "User-Agent",
                concat!("home-assistant-mcp/", env!("CARGO_PKG_VERSION")),
            )
            .call()
            .map_err(|e| self.transport_error(url, e))?;

        let status = response.status().as_u16();
        let body = self.read_body(response, url)?;

        if (200..300).contains(&status) {
            return Ok(body);
        }
        Err(self.http_error(status, url.to_string(), &body))
    }

    fn read_body(
        &self,
        mut response: ureq::http::Response<ureq::Body>,
        url: &str,
    ) -> Result<String, HaError> {
        // +1 so "exactly at the limit" is still accepted but anything beyond is caught.
        let cap = self.max_bytes as u64 + 1;
        let mut bytes: Vec<u8> = Vec::new();
        response
            .body_mut()
            .as_reader()
            .take(cap)
            .read_to_end(&mut bytes)
            .map_err(|e| self.io_error(url, e))?;
        if bytes.len() as u64 > self.max_bytes as u64 {
            return Err(HaError::TooLarge {
                url: url.to_string(),
                limit_bytes: self.max_bytes,
            });
        }
        String::from_utf8(bytes).map_err(|_| HaError::InvalidResponse {
            url: url.to_string(),
            reason: "response body is not valid UTF-8 text".into(),
        })
    }

    fn http_error(&self, status: u16, url: String, body: &str) -> HaError {
        let detail = error_detail(body);
        match status {
            401 | 407 => HaError::Unauthorized { status, detail },
            403 => HaError::Forbidden { status, detail },
            404 => HaError::NotFound { url, detail },
            _ => HaError::Status {
                status,
                url,
                detail,
            },
        }
    }

    fn transport_error(&self, url: &str, error: ureq::Error) -> HaError {
        match error {
            ureq::Error::StatusCode(status) => {
                // `http_status_as_error(false)` means this only happens for
                // transport-level status codes such as 5xx from a proxy.
                HaError::Status {
                    status,
                    url: url.to_string(),
                    detail: String::new(),
                }
            }
            ureq::Error::Timeout(_) => HaError::Timeout {
                url: url.to_string(),
                secs: self.timeout.as_secs(),
            },
            ureq::Error::HostNotFound => HaError::Unreachable {
                url: url.to_string(),
                reason: "the hostname in HA_URL could not be resolved".into(),
            },
            ureq::Error::ConnectionFailed => HaError::Unreachable {
                url: url.to_string(),
                reason: "the connection was refused or dropped".into(),
            },
            other => self.io_error(url, other.into_io()),
        }
    }

    fn io_error(&self, url: &str, error: std::io::Error) -> HaError {
        let timed_out = matches!(
            error.kind(),
            std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
        ) || error.to_string().contains("timed out");
        if timed_out {
            return HaError::Timeout {
                url: url.to_string(),
                secs: self.timeout.as_secs(),
            };
        }
        HaError::Unreachable {
            url: url.to_string(),
            reason: one_line(&error.to_string()),
        }
    }
}

/// Builds the `/api/logbook` query string; `None` values are omitted.
fn logbook_query(start_time: Option<&str>, end_time: Option<&str>) -> String {
    let mut parts: Vec<String> = Vec::new();
    if let Some(value) = start_time {
        parts.push(format!("start_time={}", percent_encode(value)));
    }
    if let Some(value) = end_time {
        parts.push(format!("end_time={}", percent_encode(value)));
    }
    if parts.is_empty() {
        String::new()
    } else {
        format!("?{}", parts.join("&"))
    }
}

/// Pulls a human-readable explanation out of an error response body.
fn error_detail(body: &str) -> String {
    let body = body.trim();
    if body.is_empty() {
        return String::new();
    }
    if let Ok(Value::Object(fields)) = serde_json::from_str::<Value>(body) {
        let message = ["message", "error", "error_message"]
            .iter()
            .find_map(|key| fields.get(*key))
            .and_then(Value::as_str)
            .map(str::to_string)
            .unwrap_or_else(|| one_line(body));
        return match fields.get("hint").and_then(Value::as_str) {
            Some(hint) if !hint.trim().is_empty() => format!("{message} ({})", one_line(hint)),
            _ => truncate_chars(&message, MAX_DETAIL_CHARS).0.to_string(),
        };
    }
    truncate_chars(&one_line(body), MAX_DETAIL_CHARS)
        .0
        .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn logbook_query_only_includes_what_was_given() {
        assert_eq!(logbook_query(None, None), "");
        assert_eq!(
            logbook_query(Some("2026-01-01T00:00:00Z"), None),
            "?start_time=2026-01-01T00%3A00%3A00Z"
        );
        assert_eq!(
            logbook_query(Some("a"), Some("b")),
            "?start_time=a&end_time=b"
        );
    }

    #[test]
    fn error_detail_prefers_the_message_field() {
        assert_eq!(
            error_detail(r#"{"message":"Entity not found: light.nope"}"#),
            "Entity not found: light.nope"
        );
    }

    #[test]
    fn error_detail_keeps_server_hints() {
        let detail = error_detail(
            r#"{"error":"not in the recorded fixture","hint":"only recorded paths exist"}"#,
        );
        assert_eq!(
            detail,
            "not in the recorded fixture (only recorded paths exist)"
        );
    }

    #[test]
    fn error_detail_handles_html_and_empty_bodies() {
        assert_eq!(error_detail(""), "");
        assert_eq!(error_detail("   "), "");
        assert_eq!(
            error_detail("<html>\n  <body>Bad Gateway</body>\n</html>"),
            "<html> <body>Bad Gateway</body> </html>"
        );
    }

    #[test]
    fn error_detail_is_capped() {
        let long = format!(r#"{{"message":"{}"}}"#, "x".repeat(1000));
        assert!(error_detail(&long).chars().count() <= MAX_DETAIL_CHARS);
    }
}
