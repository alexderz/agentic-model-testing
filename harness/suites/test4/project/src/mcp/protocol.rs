//! MCP protocol identity: versions, capabilities, server info and the
//! instructions handed to clients so a model can use the tools well.

use serde_json::{json, Value};

use crate::config::{SERVER_DESCRIPTION, SERVER_NAME, SERVER_TITLE, SERVER_VERSION};

/// The newest protocol revision this server implements.
pub const LATEST_VERSION: &str = "2026-07-28";

/// Protocol revisions accepted in `initialize` / per-request `_meta`.
///
/// The older entries exist so that clients pinned to a previous revision can
/// still complete a handshake; the semantics this server offers are identical
/// for all of them.
pub const KNOWN_VERSIONS: &[&str] = &[
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
    LATEST_VERSION,
];

/// Versions advertised by `server/discover`, i.e. the modern, stateless era.
pub const DISCOVERABLE_VERSIONS: &[&str] = &[LATEST_VERSION];

/// `ttlMs` advertised for `tools/list`: the tool set is fixed at compile time.
pub const TOOL_LIST_TTL_MS: u64 = 60 * 60 * 1000;

pub fn is_known(version: &str) -> bool {
    KNOWN_VERSIONS.contains(&version)
}

/// Version to answer an `initialize` with: the client's if we know it, ours otherwise.
pub fn negotiate(requested: Option<&str>) -> &'static str {
    requested
        .and_then(|wanted| {
            KNOWN_VERSIONS
                .iter()
                .find(|known| **known == wanted)
                .copied()
        })
        .unwrap_or(LATEST_VERSION)
}

/// `serverInfo` / `_meta.io.modelcontextprotocol/serverInfo` payload.
pub fn server_info() -> Value {
    json!({
        "name": SERVER_NAME,
        "title": SERVER_TITLE,
        "version": SERVER_VERSION,
        "description": SERVER_DESCRIPTION,
    })
}

/// Metadata every result carries.
pub fn result_meta() -> Value {
    json!({ "io.modelcontextprotocol/serverInfo": server_info() })
}

/// Declared server capabilities. Only tools are implemented, and the tool set
/// never changes, so `listChanged` is honestly `false`.
pub fn capabilities() -> Value {
    json!({ "tools": { "listChanged": false } })
}

/// Short guidance for clients to fold into a system prompt.
pub fn instructions() -> &'static str {
    "Read-only view of one Home Assistant installation through its REST API. Every tool is a \
     GET; nothing here can change the house.\n\
     A good first pass is: get_instance_info (version, units, sizes), list_domains (which \
     integrations have entities), then list_entities with a domain or query filter, then \
     get_entity for one entity's attributes. list_services and get_service describe what the \
     installation could do; this server never performs those calls. get_entity_history and \
     get_error_log reach back in time, list_events shows internal event types.\n\
     Lists are filtered and paginated: honour next_cursor rather than raising limit until you \
     have to. Failures come back as a result with isError=true whose text names the cause and \
     what to do next - read it and adjust the arguments instead of retrying unchanged."
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn advertises_only_the_modern_version_via_discover() {
        assert_eq!(DISCOVERABLE_VERSIONS, &[LATEST_VERSION]);
        assert!(is_known(LATEST_VERSION));
        assert!(is_known("2025-06-18"));
        assert!(!is_known("2023-01-01"));
    }

    #[test]
    fn negotiation_echoes_known_versions_and_falls_back_to_ours() {
        assert_eq!(negotiate(Some("2025-06-18")), "2025-06-18");
        assert_eq!(negotiate(Some(LATEST_VERSION)), LATEST_VERSION);
        assert_eq!(negotiate(Some("1999-01-01")), LATEST_VERSION);
        assert_eq!(negotiate(None), LATEST_VERSION);
    }

    #[test]
    fn server_info_has_the_fields_the_schema_requires() {
        let info = server_info();
        assert_eq!(info["name"], SERVER_NAME);
        assert!(info["version"].as_str().is_some_and(|v| !v.is_empty()));
        assert!(info["title"].as_str().is_some());
        assert!(info["description"].as_str().is_some());
    }

    #[test]
    fn capabilities_declare_only_tools_without_list_changes() {
        assert_eq!(capabilities(), json!({ "tools": { "listChanged": false } }));
    }

    #[test]
    fn instructions_mention_the_orientation_tools_and_the_read_only_contract() {
        let text = instructions();
        for expected in [
            "get_instance_info",
            "list_entities",
            "isError",
            "next_cursor",
            "GET",
        ] {
            assert!(
                text.contains(expected),
                "instructions do not mention {expected}"
            );
        }
        assert!(text.len() < 1_600, "instructions should stay brief");
    }
}
