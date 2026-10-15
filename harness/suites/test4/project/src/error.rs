//! Errors from the Home Assistant side.
//!
//! Every variant is *expected* operational trouble rather than a bug: the
//! server turns each one into a tool result with `isError: true` so the model
//! can see what went wrong and retry differently. Nothing here panics.

use std::fmt;

/// A failed attempt to read from the Home Assistant REST API.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HaError {
    /// 401 — the token is missing, expired or not a long-lived access token.
    Unauthorized { status: u16, detail: String },
    /// 403 — the token is valid but this caller or endpoint is not allowed.
    Forbidden { status: u16, detail: String },
    /// 404 — unknown path or entity id.
    NotFound { url: String, detail: String },
    /// Any other non-success status.
    Status {
        status: u16,
        url: String,
        detail: String,
    },
    /// The request did not complete inside the configured timeout.
    Timeout { url: String, secs: u64 },
    /// Could not open a connection at all (DNS, refused, TLS).
    Unreachable { url: String, reason: String },
    /// Response body exceeded the configured size limit.
    TooLarge { url: String, limit_bytes: usize },
    /// A 2xx response that is not the JSON/text shape we expect.
    InvalidResponse { url: String, reason: String },
}

impl HaError {
    /// Short machine-readable label, stable across releases.
    pub fn kind(&self) -> &'static str {
        match self {
            HaError::Unauthorized { .. } => "unauthorized",
            HaError::Forbidden { .. } => "forbidden",
            HaError::NotFound { .. } => "not-found",
            HaError::Status { .. } => "http-status",
            HaError::Timeout { .. } => "timeout",
            HaError::Unreachable { .. } => "unreachable",
            HaError::TooLarge { .. } => "response-too-large",
            HaError::InvalidResponse { .. } => "invalid-response",
        }
    }

    /// What the caller (usually a model) should do next.
    pub fn hint(&self) -> &'static str {
        match self {
            HaError::Unauthorized { .. } => {
                "Check that HA_TOKEN holds a long-lived access token from Home Assistant's \
                 Security → Personal access tokens page."
            }
            HaError::Forbidden { .. } => {
                "The token was rejected for this endpoint. Home Assistant's REST API is \
                 read-only here; use GET-backed tools such as list_services instead."
            }
            HaError::NotFound { .. } => {
                "Confirm the entity id with list_entities (entity ids look like \
                 light.living_room) or the domain and service names with list_services, and \
                 check that HA_URL points at the instance root."
            }
            HaError::Status { status, .. } if *status >= 500 => {
                "Home Assistant did not answer correctly; it may be restarting. Retry shortly."
            }
            HaError::Status { .. } => {
                "The request was accepted but rejected; check the arguments against the tool schema."
            }
            HaError::Timeout { .. } => {
                "Home Assistant is slow or unreachable; raise HA_MCP_TIMEOUT_SECS or narrow the \
                 query (smaller limit, more specific filter)."
            }
            HaError::Unreachable { .. } => {
                "Verify HA_URL (scheme, host, port) and that Home Assistant is running and \
                 reachable from this process."
            }
            HaError::TooLarge { .. } => {
                "Ask for less at once: lower limit, or filter with query/domain before fetching."
            }
            HaError::InvalidResponse { .. } => {
                "The endpoint did not return the expected JSON. Check that HA_URL is a Home \
                 Assistant root URL rather than a proxy or dashboard page."
            }
        }
    }

    /// True when the failure means no other call can succeed either.
    pub fn is_fatal_for_instance(&self) -> bool {
        matches!(self, HaError::Unauthorized { .. })
    }

    /// The status code, when the failure came from an HTTP response.
    pub fn status(&self) -> Option<u16> {
        match self {
            HaError::Unauthorized { status, .. }
            | HaError::Forbidden { status, .. }
            | HaError::Status { status, .. } => Some(*status),
            // `NotFound` is only produced by an actual 404, so the number is known.
            HaError::NotFound { .. } => Some(404),
            _ => None,
        }
    }
}

impl fmt::Display for HaError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            HaError::Unauthorized { status, detail } => write!(
                f,
                "Home Assistant rejected the access token (HTTP {status}){detail}",
                detail = colon(detail)
            ),
            HaError::Forbidden { status, detail } => {
                write!(
                    f,
                    "Home Assistant refused this request (HTTP {status}){detail}",
                    detail = colon(detail)
                )
            }
            HaError::NotFound { url, detail } => {
                write!(f, "not found at {url}{detail}", detail = colon(detail))
            }
            HaError::Status {
                status,
                url,
                detail,
            } => {
                write!(
                    f,
                    "HTTP {status} from {url}{detail}",
                    detail = colon(detail)
                )
            }
            HaError::Timeout { url, secs } => write!(f, "request to {url} timed out after {secs}s"),
            HaError::Unreachable { url, reason } => write!(f, "could not reach {url}: {reason}"),
            HaError::TooLarge { url, limit_bytes } => {
                write!(
                    f,
                    "response from {url} exceeded the {limit_bytes} byte limit"
                )
            }
            HaError::InvalidResponse { url, reason } => {
                write!(f, "unexpected response from {url}: {reason}")
            }
        }
    }
}

impl std::error::Error for HaError {}

fn colon(detail: &str) -> String {
    if detail.is_empty() {
        String::new()
    } else {
        format!(": {detail}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn display_includes_status_and_detail() {
        let err = HaError::Unauthorized {
            status: 401,
            detail: "Invalid auth token".into(),
        };
        assert_eq!(
            err.to_string(),
            "Home Assistant rejected the access token (HTTP 401): Invalid auth token"
        );
        assert_eq!(err.kind(), "unauthorized");
        assert_eq!(err.status(), Some(401));
        assert!(err.hint().contains("HA_TOKEN"));

        let err = HaError::Unauthorized {
            status: 401,
            detail: String::new(),
        };
        assert_eq!(
            err.to_string(),
            "Home Assistant rejected the access token (HTTP 401)"
        );
    }

    #[test]
    fn every_variant_has_a_kind_and_a_hint() {
        let variants = all_variants();
        for err in &variants {
            assert!(!err.kind().is_empty());
            assert!(err.hint().len() > 20, "hint for {} is too thin", err.kind());
            assert!(!err.to_string().is_empty());
        }
    }

    #[test]
    fn server_side_statuses_hint_at_retry() {
        let err = HaError::Status {
            status: 502,
            url: "http://ha/api/config".into(),
            detail: String::new(),
        };
        assert!(err.hint().to_ascii_lowercase().contains("restart"));
        let err = HaError::Status {
            status: 400,
            url: "http://ha/api/config".into(),
            detail: String::new(),
        };
        assert!(err.hint().contains("schema"));
    }

    #[test]
    fn only_authorisation_failures_are_fatal() {
        assert!(HaError::Unauthorized {
            status: 401,
            detail: String::new()
        }
        .is_fatal_for_instance());
        assert!(!HaError::NotFound {
            url: "u".into(),
            detail: String::new()
        }
        .is_fatal_for_instance());
        assert!(!HaError::Timeout {
            url: "u".into(),
            secs: 5
        }
        .is_fatal_for_instance());
    }

    fn all_variants() -> Vec<HaError> {
        vec![
            HaError::Unauthorized {
                status: 401,
                detail: "x".into(),
            },
            HaError::Forbidden {
                status: 403,
                detail: "x".into(),
            },
            HaError::NotFound {
                url: "u".into(),
                detail: "x".into(),
            },
            HaError::Status {
                status: 418,
                url: "u".into(),
                detail: "x".into(),
            },
            HaError::Timeout {
                url: "u".into(),
                secs: 1,
            },
            HaError::Unreachable {
                url: "u".into(),
                reason: "x".into(),
            },
            HaError::TooLarge {
                url: "u".into(),
                limit_bytes: 10,
            },
            HaError::InvalidResponse {
                url: "u".into(),
                reason: "x".into(),
            },
        ]
    }
}
