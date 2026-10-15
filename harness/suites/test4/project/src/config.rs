//! Process configuration, taken entirely from the environment.
//!
//! An MCP client launches the binary directly and cannot pass command line
//! arguments, so every knob lives in an environment variable. The two that must
//! be present are the Home Assistant base URL and a long-lived access token;
//! everything else has a conservative default.

use std::time::Duration;

use crate::log::Level;

/// Programmatic identifier reported in `serverInfo` / `_meta`.
pub const SERVER_NAME: &str = "home-assistant-mcp";
/// Human readable name for user interfaces.
pub const SERVER_TITLE: &str = "Home Assistant (read-only)";
/// One-line summary reported in `serverInfo`.
pub const SERVER_DESCRIPTION: &str = "Read-only Home Assistant explorer: entities, states, \
    configuration, service catalog, history and error log over the REST API.";
/// Version reported to MCP clients; comes from `Cargo.toml`.
pub const SERVER_VERSION: &str = env!("CARGO_PKG_VERSION");

const DEFAULT_TIMEOUT_SECS: u64 = 15;
const DEFAULT_MAX_RESPONSE_BYTES: usize = 32 * 1024 * 1024;
const DEFAULT_TOOL_PAGE_SIZE: usize = 50;
const MIN_TIMEOUT_SECS: u64 = 1;
const MAX_TIMEOUT_SECS: u64 = 600;
const MIN_PAGE_SIZE: usize = 1;
const MAX_PAGE_SIZE: usize = 100;
const MIN_RESPONSE_BYTES: usize = 4 * 1024;
const MAX_RESPONSE_BYTES: usize = 256 * 1024 * 1024;

/// Everything the server needs to run.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Config {
    /// Home Assistant root, without a trailing slash (e.g. `http://ha.local:8123`).
    pub base_url: String,
    /// Long-lived access token sent as a bearer token. Never logged.
    pub token: String,
    /// End-to-end timeout for one Home Assistant request.
    pub request_timeout: Duration,
    /// Refuse to buffer a response larger than this.
    pub max_response_bytes: usize,
    /// Skip TLS certificate verification (LAN installations with self-signed certs).
    pub tls_no_verify: bool,
    /// stderr verbosity.
    pub log_level: Level,
    /// Reject requests that omit the per-request `_meta` protocol fields.
    pub strict_meta: bool,
    /// Tools reported per `tools/list` page.
    pub tool_page_size: usize,
}

/// A fatal problem with the environment configuration.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ConfigError {
    /// A required variable is unset or blank.
    Missing {
        var: &'static str,
        alternates: &'static [&'static str],
        hint: &'static str,
    },
    /// A variable is set but unusable. The offending *value* is deliberately
    /// not included, because a secret may be involved.
    Invalid { var: &'static str, reason: String },
}

impl std::fmt::Display for ConfigError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ConfigError::Missing {
                var,
                alternates,
                hint,
            } => {
                write!(f, "missing required environment variable {var}")?;
                if !alternates.is_empty() {
                    write!(f, " (or {})", alternates.join(" / "))?;
                }
                write!(f, ": {hint}")
            }
            ConfigError::Invalid { var, reason } => write!(f, "{var} is invalid: {reason}"),
        }
    }
}

impl std::error::Error for ConfigError {}

impl Config {
    /// Reads configuration from the process environment.
    pub fn from_env() -> Result<Config, ConfigError> {
        Self::from_lookup(|key| std::env::var(key).ok())
    }

    /// Reads configuration from an arbitrary source, so the rules are testable
    /// without mutating the environment of the test process.
    pub fn from_lookup(lookup: impl Fn(&str) -> Option<String>) -> Result<Config, ConfigError> {
        let base_url = parse_base_url(first(&lookup, "HA_URL", &["HA_BASE_URL"]))?;
        let token = parse_token(first(&lookup, "HA_TOKEN", &["HA_LONG_LIVED_ACCESS_TOKEN"]))?;

        Ok(Config {
            base_url,
            token,
            request_timeout: Duration::from_secs(parse_timeout_secs(lookup(
                "HA_MCP_TIMEOUT_SECS",
            ))?),
            max_response_bytes: parse_usize(
                lookup("HA_MCP_MAX_RESPONSE_BYTES"),
                DEFAULT_MAX_RESPONSE_BYTES,
                MIN_RESPONSE_BYTES,
                MAX_RESPONSE_BYTES,
                "HA_MCP_MAX_RESPONSE_BYTES",
                "a byte count between {min} and {max}",
            )?,
            tls_no_verify: parse_bool(
                lookup("HA_MCP_TLS_NO_VERIFY"),
                false,
                "HA_MCP_TLS_NO_VERIFY",
            )?,
            log_level: match lookup("HA_MCP_LOG_LEVEL") {
                None => Level::Info,
                Some(raw) => Level::parse(&raw).ok_or_else(|| ConfigError::Invalid {
                    var: "HA_MCP_LOG_LEVEL",
                    reason: format!("expected one of {}", Level::NAMES.join(", ")),
                })?,
            },
            strict_meta: parse_bool(lookup("HA_MCP_STRICT_META"), false, "HA_MCP_STRICT_META")?,
            tool_page_size: parse_usize(
                lookup("HA_MCP_TOOL_PAGE_SIZE"),
                DEFAULT_TOOL_PAGE_SIZE,
                MIN_PAGE_SIZE,
                MAX_PAGE_SIZE,
                "HA_MCP_TOOL_PAGE_SIZE",
                "an integer between {min} and {max}",
            )?,
        })
    }

    /// Absolute URL for an already percent-encoded `/api/...` path.
    pub fn api_url(&self, api_path: &str) -> String {
        debug_assert!(api_path.starts_with('/'));
        format!("{}{api_path}", self.base_url)
    }

    /// True for `https://` installations.
    pub fn uses_tls(&self) -> bool {
        self.base_url.starts_with("https://")
    }
}

/// Returns the first variable that is set to a non-blank value.
fn first(
    lookup: &impl Fn(&str) -> Option<String>,
    primary: &'static str,
    alternates: &[&'static str],
) -> Option<String> {
    for var in std::iter::once(primary).chain(alternates.iter().copied()) {
        if let Some(value) = lookup(var) {
            if !value.trim().is_empty() {
                return Some(value);
            }
        }
    }
    None
}

fn parse_base_url(raw: Option<String>) -> Result<String, ConfigError> {
    let var = "HA_URL";
    let raw = raw.ok_or(ConfigError::Missing {
        var,
        alternates: &["HA_BASE_URL"],
        hint: "the Home Assistant root URL the MCP client should reach, e.g. http://homeassistant.local:8123",
    })?;
    let trimmed = raw.trim().to_string();

    if trimmed.chars().any(|c| c.is_control() || c.is_whitespace()) {
        return Err(ConfigError::Invalid {
            var,
            reason: "must not contain whitespace or control characters".into(),
        });
    }
    let without_scheme = trimmed
        .strip_prefix("http://")
        .or_else(|| trimmed.strip_prefix("https://"))
        .or_else(|| {
            trimmed
                .strip_prefix("HTTP://")
                .or_else(|| trimmed.strip_prefix("HTTPS://"))
        })
        .ok_or_else(|| ConfigError::Invalid {
            var,
            reason: "must start with http:// or https://".into(),
        })?;
    let host = without_scheme
        .split(['/', '?', '#'])
        .next()
        .unwrap_or(without_scheme);
    if host.is_empty() {
        return Err(ConfigError::Invalid {
            var,
            reason: "must include a host, e.g. http://homeassistant.local:8123".into(),
        });
    }
    if host.contains('@') {
        return Err(ConfigError::Invalid {
            var,
            reason: "must not embed credentials; put the token in HA_TOKEN instead".into(),
        });
    }
    if trimmed.contains('?') || trimmed.contains('#') {
        return Err(ConfigError::Invalid {
            var,
            reason: "must be the root URL only, without a query string or fragment".into(),
        });
    }

    Ok(trimmed.trim_end_matches('/').to_string())
}

fn parse_token(raw: Option<String>) -> Result<String, ConfigError> {
    let var = "HA_TOKEN";
    let raw = raw.ok_or(ConfigError::Missing {
        var,
        alternates: &["HA_LONG_LIVED_ACCESS_TOKEN"],
        hint: "a Home Assistant long-lived access token (Security → Personal access tokens). \
              This server only issues GET requests.",
    })?;
    let trimmed = raw.trim().to_string();
    if trimmed.chars().any(|c| c.is_control()) {
        return Err(ConfigError::Invalid {
            var,
            reason: "must not contain control characters".into(),
        });
    }
    Ok(trimmed)
}

fn parse_timeout_secs(raw: Option<String>) -> Result<u64, ConfigError> {
    let var = "HA_MCP_TIMEOUT_SECS";
    let Some(raw) = raw else {
        return Ok(DEFAULT_TIMEOUT_SECS);
    };
    let secs = raw.trim().parse::<u64>().map_err(|_| ConfigError::Invalid {
        var,
        reason: format!("expected a whole number of seconds between {MIN_TIMEOUT_SECS} and {MAX_TIMEOUT_SECS}"),
    })?;
    if !(MIN_TIMEOUT_SECS..=MAX_TIMEOUT_SECS).contains(&secs) {
        return Err(ConfigError::Invalid {
            var,
            reason: format!("expected a whole number of seconds between {MIN_TIMEOUT_SECS} and {MAX_TIMEOUT_SECS}"),
        });
    }
    Ok(secs)
}

fn parse_usize(
    raw: Option<String>,
    default: usize,
    min: usize,
    max: usize,
    var: &'static str,
    expectation: &str,
) -> Result<usize, ConfigError> {
    let Some(raw) = raw else {
        return Ok(default);
    };
    let expectation = expectation
        .replace("{min}", &min.to_string())
        .replace("{max}", &max.to_string());
    let value = raw
        .trim()
        .parse::<usize>()
        .map_err(|_| ConfigError::Invalid {
            var,
            reason: format!("expected {expectation}"),
        })?;
    if !(min..=max).contains(&value) {
        return Err(ConfigError::Invalid {
            var,
            reason: format!("expected {expectation}"),
        });
    }
    Ok(value)
}

fn parse_bool(raw: Option<String>, default: bool, var: &'static str) -> Result<bool, ConfigError> {
    let Some(raw) = raw else {
        return Ok(default);
    };
    match raw.trim().to_ascii_lowercase().as_str() {
        "" | "0" | "false" | "no" | "off" => Ok(false),
        "1" | "true" | "yes" | "on" => Ok(true),
        _ => Err(ConfigError::Invalid {
            var,
            reason: "expected a boolean such as 1, true, yes, 0 or false".into(),
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Environment fixture: only the keys listed here are "set".
    fn env(pairs: &[(&str, &str)]) -> impl Fn(&str) -> Option<String> {
        let owned: Vec<(String, String)> = pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect();
        move |key: &str| owned.iter().find(|(k, _)| k == key).map(|(_, v)| v.clone())
    }

    const BASE: &str = "http://ha.test:8123";
    const TOKEN: &str = "abcdef.5555550110";

    fn base_pairs<'a>(extra: &'a [(&'a str, &'a str)]) -> Vec<(&'a str, &'a str)> {
        let mut pairs = vec![("HA_URL", BASE), ("HA_TOKEN", TOKEN)];
        pairs.extend_from_slice(extra);
        pairs
    }

    fn config(pairs: &[(&str, &str)]) -> Config {
        Config::from_lookup(env(pairs)).expect("config should be valid")
    }

    #[test]
    fn reads_url_and_token_with_sensible_defaults() {
        let cfg = config(&base_pairs(&[]));
        assert_eq!(cfg.base_url, BASE);
        assert_eq!(cfg.token, TOKEN);
        assert_eq!(cfg.request_timeout, Duration::from_secs(15));
        assert_eq!(cfg.max_response_bytes, 32 * 1024 * 1024);
        assert_eq!(cfg.tool_page_size, 50);
        assert_eq!(cfg.log_level, Level::Info);
        assert!(!cfg.tls_no_verify);
        assert!(!cfg.strict_meta);
        assert!(!cfg.uses_tls());
    }

    #[test]
    fn falls_back_to_alternate_variable_names() {
        let cfg = Config::from_lookup(env(&[
            ("HA_BASE_URL", "https://ha.example/"),
            ("HA_LONG_LIVED_ACCESS_TOKEN", "  spaced-token  "),
        ]))
        .expect("alternate names should work");
        assert_eq!(cfg.base_url, "https://ha.example");
        assert_eq!(cfg.token, "spaced-token");
        assert!(cfg.uses_tls());
    }

    #[test]
    fn missing_url_and_token_are_reported_with_hints() {
        let err = Config::from_lookup(env(&[("HA_TOKEN", TOKEN)])).unwrap_err();
        assert!(matches!(err, ConfigError::Missing { var: "HA_URL", .. }));
        assert!(err.to_string().contains("HA_BASE_URL"));

        let err = Config::from_lookup(env(&[("HA_URL", BASE)])).unwrap_err();
        assert!(matches!(
            err,
            ConfigError::Missing {
                var: "HA_TOKEN",
                ..
            }
        ));
        assert!(err.to_string().contains("long-lived access token"));
    }

    #[test]
    fn blank_values_count_as_missing_rather_than_valid() {
        let err = Config::from_lookup(env(&[("HA_URL", "   "), ("HA_TOKEN", TOKEN)])).unwrap_err();
        assert!(matches!(err, ConfigError::Missing { var: "HA_URL", .. }));
    }

    #[test]
    fn url_must_be_an_http_root() {
        for bad in [
            "homeassistant.local:8123",
            "ftp://ha/",
            "http://",
            "http://user:placeholder@ha/",
        ] {
            let err =
                Config::from_lookup(env(&[("HA_URL", bad), ("HA_TOKEN", TOKEN)])).unwrap_err();
            assert!(
                matches!(&err, ConfigError::Invalid { var, .. } if *var == "HA_URL"),
                "accepted {bad:?}: {err}"
            );
        }
        let err = Config::from_lookup(env(&[
            ("HA_URL", "http://ha/?debug=1"),
            ("HA_TOKEN", TOKEN),
        ]))
        .unwrap_err();
        assert!(err.to_string().contains("query string"));
    }

    #[test]
    fn trailing_slashes_are_stripped_once_per_url() {
        assert_eq!(
            config(&[("HA_URL", "http://ha.test:8123///"), ("HA_TOKEN", TOKEN)]).base_url,
            "http://ha.test:8123"
        );
        assert_eq!(
            config(&base_pairs(&[])).api_url("/api/states"),
            "http://ha.test:8123/api/states"
        );
    }

    #[test]
    fn timeout_must_be_a_reasonable_whole_number_of_seconds() {
        assert_eq!(
            config(&base_pairs(&[("HA_MCP_TIMEOUT_SECS", "3")])).request_timeout,
            Duration::from_secs(3)
        );
        for bad in ["abc", "0", "-1", "1.5", "601"] {
            let err = config_err(&base_pairs(&[("HA_MCP_TIMEOUT_SECS", bad)]));
            assert!(
                matches!(&err, ConfigError::Invalid { var, .. } if *var == "HA_MCP_TIMEOUT_SECS"),
                "accepted {bad:?}"
            );
        }
    }

    #[test]
    fn boolean_and_size_knobs_are_validated() {
        assert!(config(&base_pairs(&[("HA_MCP_TLS_NO_VERIFY", "yes")])).tls_no_verify);
        assert!(!config(&base_pairs(&[("HA_MCP_STRICT_META", "0")])).strict_meta);
        assert_eq!(
            config(&base_pairs(&[("HA_MCP_TOOL_PAGE_SIZE", "1")])).tool_page_size,
            1
        );

        let err = config_err(&base_pairs(&[("HA_MCP_TLS_NO_VERIFY", "maybe")]));
        assert!(err.to_string().contains("HA_MCP_TLS_NO_VERIFY"));
        let err = config_err(&base_pairs(&[("HA_MCP_TOOL_PAGE_SIZE", "5000")]));
        assert!(err.to_string().contains("between 1 and 100"));
        let err = config_err(&base_pairs(&[("HA_MCP_MAX_RESPONSE_BYTES", "10")]));
        assert!(err.to_string().contains("HA_MCP_MAX_RESPONSE_BYTES"));
    }

    #[test]
    fn log_level_names_are_parsed() {
        assert_eq!(
            config(&base_pairs(&[("HA_MCP_LOG_LEVEL", "debug")])).log_level,
            Level::Debug
        );
        assert_eq!(
            config(&base_pairs(&[("HA_MCP_LOG_LEVEL", "off")])).log_level,
            Level::Off
        );
        let err = config_err(&base_pairs(&[("HA_MCP_LOG_LEVEL", "verbose")]));
        assert!(matches!(&err, ConfigError::Invalid { var, .. } if *var == "HA_MCP_LOG_LEVEL"));
    }

    #[test]
    fn error_messages_never_leak_the_token() {
        let secret = "placeholder-secret-value";
        let err = config_err(&[("HA_URL", "not a url"), ("HA_TOKEN", secret)]);
        assert!(!err.to_string().contains(secret));
        let err = config_err(&[("HA_URL", BASE), ("HA_TOKEN", "bad\n\u{7}token")]);
        assert!(!err.to_string().contains("bad"));
    }

    fn config_err(pairs: &[(&str, &str)]) -> ConfigError {
        Config::from_lookup(env(pairs)).expect_err("config should be rejected")
    }
}
