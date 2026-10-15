//! The tool contract: names, prose, schemas and the code behind each tool.
//!
//! Everything a client can see about a tool lives here, so the description an
//! agent reads and the arguments it is allowed to send cannot drift apart.

use std::sync::OnceLock;

use serde_json::{json, Value};

use crate::error::HaError;
use crate::ha::HaClient;
use crate::mcp::args::{self, Args};
use crate::mcp::handlers::{self, HandlerError};
use crate::mcp::schema::{
    any_json, boolean, count, enum_with_default, flag, input_schema, integer, json_array,
    json_object, open_object_array, output_schema, paged, paged_required, prop_cursor, prop_domain,
    prop_entity_id, prop_entity_ids, prop_limit, prop_query, string, string_array, string_list,
    string_or_null, with_max_items,
};
use crate::util::{page, Page};

/// One tool, from description to implementation.
pub struct Tool {
    pub name: &'static str,
    pub title: &'static str,
    pub description: &'static str,
    pub input_schema: Value,
    pub output_schema: Value,
    pub handler: fn(&Args, &HaClient) -> Result<Value, HandlerError>,
}

impl Tool {
    /// The `tools/list` wire representation.
    pub fn definition(&self) -> Value {
        json!({
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "outputSchema": self.output_schema,
            "annotations": {
                "title": self.title,
                "readOnlyHint": true,
                "destructiveHint": false,
                "idempotentHint": true,
                "openWorldHint": false,
            },
        })
    }
}

/// Why a `tools/call` did not produce a result.
#[derive(Debug)]
pub enum CallError {
    /// No such tool: a protocol-level `-32602`, not a tool error.
    Unknown(String),
    /// The arguments did not satisfy the schema.
    Invalid(Vec<String>),
    /// Home Assistant could not answer.
    Api(HaError),
}

impl CallError {
    /// Text for the `content` block of an `isError` result.
    pub fn message(&self) -> String {
        match self {
            CallError::Unknown(name) => {
                format!("there is no tool named \"{name}\"; call tools/list to see what exists")
            }
            CallError::Invalid(problems) => problems.join("; "),
            CallError::Api(error) => HandlerError::Api(error.clone()).message(),
        }
    }

    pub fn kind(&self) -> &'static str {
        match self {
            CallError::Unknown(_) => "unknown-tool",
            CallError::Invalid(_) => "invalid-arguments",
            CallError::Api(error) => error.kind(),
        }
    }

    /// True when no other tool could succeed either (bad token).
    pub fn is_fatal_for_instance(&self) -> bool {
        matches!(self, CallError::Api(error) if error.is_fatal_for_instance())
    }
}

/// Validates `arguments` against `tool` and runs it.
pub fn call(tool: &Tool, arguments: Option<&Value>, client: &HaClient) -> Result<Value, CallError> {
    let args = args::validate(&tool.input_schema, arguments).map_err(CallError::Invalid)?;
    (tool.handler)(&args, client).map_err(|error| match error {
        HandlerError::Invalid(problems) => CallError::Invalid(problems),
        HandlerError::Api(error) => CallError::Api(error),
    })
}

pub fn find(name: &str) -> Option<&'static Tool> {
    registry().iter().find(|tool| tool.name == name)
}

pub fn registry() -> &'static [Tool] {
    static REGISTRY: OnceLock<Vec<Tool>> = OnceLock::new();
    REGISTRY.get_or_init(build)
}

/// A `tools/list` page: `{tools: [...], nextCursor: "..."}`, with `nextCursor`
/// omitted on the last page as the spec requires.
pub fn list_definitions(cursor: &str, limit: usize) -> Result<Value, String> {
    let tools = registry();
    let Page { start, next } = page(tools.len(), cursor, limit)?;
    let items: Vec<Value> = tools[start..start + tools[start..].len().min(limit)]
        .iter()
        .map(Tool::definition)
        .collect();
    let mut out = serde_json::Map::new();
    out.insert("tools".into(), Value::Array(items));
    if let Some(cursor) = next {
        out.insert("nextCursor".into(), Value::String(cursor.encode()));
    }
    Ok(Value::Object(out))
}

/// The entity projection the list tools return.
fn entity_item_properties() -> Vec<(&'static str, Value)> {
    vec![
        ("entity_id", string("Entity id, e.g. \"light.living_room\".")),
        ("domain", string("The integration domain, i.e. the part before the dot.")),
        ("state", string("The state value as a string, whatever the domain is.")),
        ("last_updated", string("When the state last changed, ISO 8601.")),
        ("friendly_name", string_or_null("Display name, when the entity has one.")),
        ("device_class", string_or_null("Semantic device class, when the entity declares one.")),
        ("unit_of_measurement", string_or_null("Unit for numeric sensors.")),
        ("icon", string_or_null("Material icon name, when set.")),
        ("hidden", flag("True when the entity is hidden in the Home Assistant UI.")),
        ("attributes", json_object("Only present when include_attributes was requested; the entity's full attribute object.")),
    ]
}

fn entity_item_required() -> Vec<&'static str> {
    vec!["entity_id", "domain", "state", "last_updated"]
}

fn build() -> Vec<Tool> {
    let mut tools = vec![
        Tool {
            name: "get_instance_info",
            title: "Instance overview",
            description: "One-shot orientation: whether the API answers, which version and location this \
             instance is, and how many entities, domains, services and event types exist. If a section \
             cannot be read it is named in `unavailable` instead of failing the whole call, so this is also \
             the cheapest way to check that the URL and token work.",
            input_schema: input_schema(&[], &[]),
            output_schema: output_schema(
                &[
                    ("api_running", flag("True when GET /api/ answered normally.")),
                    ("api_message", string_or_null("The API's own status text, or null when the probe failed.")),
                    ("instance", json_object("Selected fields from the configuration document.")),
                    ("counts", json_object("Size of the instance: components, entities, entity_domains, service_domains, services, event_types. Null when that section was unavailable.")),
                    ("unavailable", json_array("Sections that could not be read, each with the reason.")),
                ],
                &["api_running", "api_message", "instance", "counts", "unavailable"],
            ),
            handler: handlers::instance_info,
        },
        Tool {
            name: "get_config",
            title: "Configuration document",
            description: "The full configuration document from GET /api/config: version, location, unit \
             system, time zone and the list of loaded integration components. Pass `sections` to fetch only \
             the parts you need (names that do not exist come back in `missing_sections`), or set \
             `include_components` to false to drop the long integration list.",
            input_schema: input_schema(
                &[
                    ("include_components", boolean("Include the `components` list of loaded integration names.", true)),
                    ("sections", string_array("Top-level keys to return, e.g. [\"unit_system\", \"time_zone\"]. Empty means every key.", &[])),
                ],
                &[],
            ),
            output_schema: output_schema(
                &[
                    ("config", json_object("The configuration document, narrowed to the requested sections.")),
                    ("total_keys", count("How many top-level keys the whole document has.")),
                    ("returned_keys", string_list("Sorted keys actually present in `config`.")),
                    ("components_count", count("How many integration components are loaded, whether or not they are included.")),
                    ("components_included", flag("Whether `config` still contains the `components` list.")),
                    ("missing_sections", string_list("Requested section names that the document does not have.")),
                ],
                &["config", "total_keys", "returned_keys", "components_count", "components_included", "missing_sections"],
            ),
            handler: handlers::config,
        },
        Tool {
            name: "list_integrations",
            title: "Loaded integrations",
            description: "Which integrations and platforms are loaded, taken from the `components` list in \
             /api/config and grouped by top-level domain. Not the same as list_domains: an integration can be \
             loaded without producing entities, and a domain can have entities from several integrations.",
            input_schema: input_schema(
                &[
                    ("query", prop_query("Case-insensitive substring that a domain or any of its platform names must contain, e.g. \"mqtt\".")),
                    ("limit", prop_limit(200, 100)),
                    ("cursor", prop_cursor()),
                ],
                &[],
            ),
            output_schema: output_schema(
                &paged(&[
                    ("total_components", count("Integration and platform names in the whole instance.")),
                    ("total_domains", count("Distinct top-level domains before filtering.")),
                    ("domains", open_object_array(
                        "The current page of matching domains.",
                        &[
                            ("domain", string("Top-level integration name.")),
                            ("component_count", count("How many names belong to this domain.")),
                            ("components", string_list("The integration and platform names, e.g. [\"hue\", \"hue.light\"].")),
                        ],
                        &["domain", "component_count", "components"],
                    )),
                ]),
                &paged_required(&["total_components", "total_domains", "domains"]),
            ),
            handler: handlers::list_integrations,
        },
        Tool {
            name: "list_domains",
            title: "Entity domains",
            description: "Groups the current entities by domain with counts, example entity ids and the most \
             common state values. Answers \"what kinds of things does this house have?\" in one call instead \
             of paging through every entity.",
            input_schema: input_schema(
                &[
                    ("query", prop_query("Case-insensitive substring a domain name must contain, e.g. \"sen\".")),
                    ("sort_by", enum_with_default("Sort order for the result.", &["count", "domain"], "count")),
                    ("limit", prop_limit(100, 40)),
                    ("cursor", prop_cursor()),
                ],
                &[],
            ),
            output_schema: output_schema(
                &paged(&[
                    ("total_entities", count("Entities in the instance before filtering.")),
                    ("total_domains", count("Distinct entity domains before filtering.")),
                    ("domains", open_object_array(
                        "The current page of matching domains.",
                        &[
                            ("domain", string("Entity domain, i.e. the part before the dot.")),
                            ("entity_count", count("How many entities are in this domain.")),
                            ("example_entities", string_list("Up to three entity ids from this domain.")),
                            ("common_states", json_array("Up to three of the most frequent state values, as {state, count}.")),
                        ],
                        &["domain", "entity_count", "example_entities", "common_states"],
                    )),
                ]),
                &paged_required(&["total_entities", "total_domains", "domains"]),
            ),
            handler: handlers::list_domains,
        },
        Tool {
            name: "list_entities",
            title: "List and search entities",
            description: "Searches current entity states by entity id, object id or friendly name (`query`, \
             space-separated terms all match), by `domain`, and by exact state value (`state`). Home \
             Assistant's REST API has no server-side filters, so these run here over one /api/states fetch. \
             Entities hidden in the UI are included and marked `hidden`.",
            input_schema: input_schema(
                &[
                    ("query", prop_query("Terms every entity must match, case-insensitively, across its entity id and friendly name, e.g. \"living room\".")),
                    ("domain", prop_domain("Only entities in this domain, e.g. \"light\".")),
                    ("state", prop_domain("Only entities whose state equals this value, e.g. \"on\" or \"unavailable\".")),
                    ("sort_by", enum_with_default("Which field to sort on.", &["entity_id", "domain", "friendly_name", "state", "last_updated"], "entity_id")),
                    ("sort_dir", enum_with_default("Sort direction.", &["asc", "desc"], "asc")),
                    ("only_available", boolean("Skip entities hidden in the Home Assistant UI.", false)),
                    ("include_attributes", boolean("Include each entity's full attribute object (much larger responses).", false)),
                    ("limit", prop_limit(200, 50)),
                    ("cursor", prop_cursor()),
                ],
                &[],
            ),
            output_schema: output_schema(
                &paged(&[
                    ("total_entities", count("Entities in the instance before filtering.")),
                    ("entities", open_object_array("The current page of matching entities.", &entity_item_properties(), &entity_item_required())),
                ]),
                &paged_required(&["total_entities", "entities"]),
            ),
            handler: handlers::list_entities,
        },
        Tool {
            name: "get_entity",
            title: "Read one entity",
            description: "One entity's complete current state with every attribute, from \
             GET /api/states/{entity_id}. Entity ids look like \"light.living_room\"; use list_entities if you \
             are not sure of the exact id, because a wrong id is reported as not found rather than guessed at.",
            input_schema: input_schema(
                &[("entity_id", prop_entity_id("The entity id to read, exactly as Home Assistant reports it, e.g. \"light.living_room\"."))],
                &["entity_id"],
            ),
            output_schema: output_schema(
                &[
                    ("entity_id", string("The entity id as Home Assistant knows it.")),
                    ("domain", string("Domain part of the id.")),
                    ("object_id", string("Part after the dot.")),
                    ("state", string("The state value as a string.")),
                    ("friendly_name", string_or_null("Display name from the attributes, if set.")),
                    ("attributes", json_object("Every attribute Home Assistant reports for this entity, verbatim.")),
                    ("last_changed", string("When the state value last changed, ISO 8601.")),
                    ("last_reported", string("When the state was last reported, ISO 8601.")),
                    ("last_updated", string("When the state object last changed, ISO 8601.")),
                    ("hidden", flag("True when the entity is hidden in the Home Assistant UI.")),
                    ("extra", json_object("Any further fields from the API payload, such as `context`.")),
                ],
                &["entity_id", "domain", "object_id", "state", "friendly_name", "attributes", "last_changed", "last_reported", "last_updated", "hidden", "extra"],
            ),
            handler: handlers::get_entity,
        },
        Tool {
            name: "get_entities",
            title: "Read several entities",
            description: "Reads many entities in one request instead of repeating get_entity. Ids that do not \
             exist are listed in `missing` and the rest still come back, so one typo does not lose the whole \
             batch. Duplicate ids are collapsed.",
            input_schema: input_schema(
                &[
                    ("entity_ids", with_max_items(prop_entity_ids("Entity ids to read, e.g. [\"light.living_room\", \"sensor.outside_temperature\"]."), 100)),
                    ("include_attributes", boolean("Include each entity's full attribute object.", false)),
                ],
                &["entity_ids"],
            ),
            output_schema: output_schema(
                &[
                    ("requested", count("Distinct entity ids asked for.")),
                    ("found", count("How many of them exist.")),
                    ("missing", string_list("Requested entity ids the instance does not have.")),
                    ("entities", open_object_array("The entities that exist, in the order requested.", &entity_item_properties(), &entity_item_required())),
                ],
                &["requested", "found", "missing", "entities"],
            ),
            handler: handlers::get_entities,
        },
        Tool {
            name: "get_entity_history",
            title: "Entity history",
            description: "Recent logbook activity (GET /api/logbook): which entity changed, when, and what \
             caused it. Newest first. The `entity_id`, `start_time`, `end_time` and `query` filters are \
             applied by this server, so they work even when the instance ignores the query parameters it was \
             sent. An `entity_id` without a dot matches a whole domain.",
            input_schema: input_schema(
                &[
                    ("entity_id", crate::mcp::schema::prop_optional_entity_id("Only entries for this entity id, e.g. \"climate.bedroom\". Pass a domain like \"light\" to cover all its entities. Empty means every entity.")),
                    ("start_time", prop_query("Earliest entry to return, e.g. \"2026-09-21T00:00:00Z\" or \"2026-09-21\".")),
                    ("end_time", prop_query("Latest entry to return, in the same format.")),
                    ("query", prop_query("Case-insensitive terms that an entry's entity id, name, message or state must contain.")),
                    ("limit", prop_limit(500, 100)),
                    ("cursor", prop_cursor()),
                ],
                &[],
            ),
            output_schema: output_schema(
                &paged(&[
                    ("total_entries", count("Entries the logbook returned before filtering.")),
                    ("entity_filter", string_or_null("The entity filter that was applied, echoed back.")),
                    ("window_start", string_or_null("The start of the window that was applied, echoed back.")),
                    ("window_end", string_or_null("The end of the window that was applied, echoed back.")),
                    ("entries", json_array("Logbook entries, newest first, as Home Assistant reported them.")),
                ]),
                &paged_required(&["total_entries", "entity_filter", "window_start", "window_end", "entries"]),
            ),
            handler: handlers::get_entity_history,
        },
        Tool {
            name: "get_service",
            title: "Service definition",
            description: "Everything one service accepts: its fields, which of them are required, the selector \
             each field uses, the options a select offers and a plausible example value. Read this before \
             calling any service - this server can describe services but never calls them.",
            input_schema: input_schema(
                &[
                    ("domain", string("The service domain to look up, e.g. \"light\". See list_services for the available domains.")),
                    ("service", string("The service name within that domain, e.g. \"turn_on\".")),
                ],
                &["domain", "service"],
            ),
            output_schema: output_schema(
                &[
                    ("domain", string("The service domain, lowercased as matched."), ),
                    ("service", string("The service name, lowercased as matched.")),
                    ("name", string_or_null("Human-readable name, when the integration provides one.")),
                    ("description", string_or_null("What the service does, when documented.")),
                    ("target", json_object("The `target` schema this service declares (entity/area/device selectors).")),
                    ("fields", json_object("The raw field definitions, verbatim.")),
                    ("field_summaries", open_object_array(
                        "One entry per field, decoded.",
                        &[
                            ("name", string("Field name to use in a service call."), ),
                            ("required", flag("Whether the field must be supplied.")),
                            ("description", any_json("The field's own description, or null when undocumented.")),
                            ("selector", string_or_null("Selector kind driving the UI widget, e.g. \"number\" or \"entity\".")),
                            ("options", json_array("Selectable values when the field uses a select selector.")),
                            ("example", any_json("A plausible value for this field, derived from its selector.")),
                        ],
                        &["name", "required", "options"],
                    )),
                ],
                &["domain", "service", "name", "description", "target", "fields", "field_summaries"],
            ),
            handler: handlers::get_service,
        },
        Tool {
            name: "list_services",
            title: "Service catalogue",
            description: "The service catalogue (GET /api/services) flattened into one sortable list with each \
             service's field names, required fields and whether it targets entities. Filter by `domain` or by \
             words in the name/description. Listing services does not call them; this server cannot change \
             any state.",
            input_schema: input_schema(
                &[
                    ("domain", prop_domain("Only services in this domain, e.g. \"cover\".")),
                    ("query", prop_query("Case-insensitive terms a service's domain, name or description must contain, e.g. \"humidity\".")),
                    ("limit", prop_limit(300, 100)),
                    ("cursor", prop_cursor()),
                ],
                &[],
            ),
            output_schema: output_schema(
                &paged(&[
                    ("total_service_domains", count("Service domains the instance offers before filtering.")),
                    ("total_services", count("Services across every domain before filtering.")),
                    ("services", open_object_array(
                        "The current page of matching services.",
                        &[
                            ("domain", string("Service domain."), ),
                            ("service", string("Service name; call it as \"domain.service\".")),
                            ("name", string_or_null("Human-readable name, when provided.")),
                            ("description", string_or_null("What the service does, when documented.")),
                            ("targets_entities", flag("True when the service declares an entity target.")),
                            ("field_count", count("How many fields the service accepts.")),
                            ("field_names", string_list("Sorted field names; see get_service for their details.")),
                            ("required_fields", string_list("Field names the service marks as required.")),
                        ],
                        &["domain", "service", "targets_entities", "field_count", "field_names", "required_fields"],
                    )),
                ]),
                &paged_required(&["total_service_domains", "total_services", "services"]),
            ),
            handler: handlers::list_services,
        },
        Tool {
            name: "get_error_log",
            title: "Error log",
            description: "Reads Home Assistant's error log (GET /api/error_log), most recent lines last by \
             default. The raw file can be megabytes, so filter with `level` or `contains` before raising \
             `max_lines`; `truncated` says whether lines were dropped to stay within the limit.",
            input_schema: input_schema(
                &[
                    ("contains", prop_query("Case-insensitive substring a line must contain, e.g. an integration name or \"Traceback\".")),
                    ("level", enum_with_default("Only keep lines at this log level; \"any\" keeps every line.", &["any", "debug", "info", "warning", "error", "critical"], "any")),
                    ("max_lines", integer("Most lines to return. With tail=true these are the last ones.", 1, 2000, 200)),
                    ("tail", boolean("Return the end of the log rather than the beginning.", true)),
                ],
                &[],
            ),
            output_schema: output_schema(
                &[
                    ("total_lines", count("Lines in the whole log."),),
                    ("matched", count("Lines left after the filters."),),
                    ("returned", count("Lines actually returned, at most max_lines.")),
                    ("truncated", flag("True when matching lines were dropped because of max_lines.")),
                    ("tail", flag("Whether the returned slice is the end of the filtered log.")),
                    ("level_filter", string("The log level filter that was applied, echoed back.")),
                    ("contains", string_or_null("The substring filter that was applied, echoed back.")),
                    ("lines", string_list("The log lines, each capped so one traceback cannot crowd out the rest.")),
                ],
                &["total_lines", "matched", "returned", "truncated", "tail", "level_filter", "contains", "lines"],
            ),
            handler: handlers::get_error_log,
        },
        Tool {
            name: "list_events",
            title: "Event types",
            description: "The event types this instance publishes or subscribes to, with how many listeners \
             each has (GET /api/events). This is the catalogue of names, not a live stream; use \
             get_entity_history to see what actually happened.",
            input_schema: input_schema(
                &[
                    ("query", prop_query("Case-insensitive terms an event name must contain, e.g. \"state\".")),
                    ("limit", prop_limit(200, 100)),
                    ("cursor", prop_cursor()),
                ],
                &[],
            ),
            output_schema: output_schema(
                &paged(&[
                    ("total_event_types", count("Event types the instance knows about before filtering.")),
                    ("event_types", open_object_array(
                        "The current page of matching event types.",
                        &[
                            ("event", string("Event type name.")),
                            ("listener_count", count("How many listeners it currently has.")),
                        ],
                        &["event", "listener_count"],
                    )),
                ]),
                &paged_required(&["total_event_types", "event_types"]),
            ),
            handler: handlers::list_events,
        },
    ];
    tools.sort_by(|a, b| a.name.cmp(b.name));
    tools
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_registry_is_sorted_and_free_of_duplicate_names() {
        let names: Vec<&str> = registry().iter().map(|tool| tool.name).collect();
        let mut sorted = names.clone();
        sorted.sort();
        assert_eq!(names, sorted, "tools/list order must be stable");
        assert_eq!(
            names.len(),
            names.iter().collect::<std::collections::HashSet<_>>().len()
        );
        assert_eq!(
            names,
            vec![
                "get_config",
                "get_entities",
                "get_entity",
                "get_entity_history",
                "get_error_log",
                "get_instance_info",
                "get_service",
                "list_domains",
                "list_entities",
                "list_events",
                "list_integrations",
                "list_services",
            ]
        );
    }

    #[test]
    fn every_optional_input_argument_has_a_default() {
        // The argument validator relies on this: handlers read every property
        // unconditionally, so a missing default would silently become "" or 0.
        for tool in registry() {
            let properties = tool.input_schema["properties"]
                .as_object()
                .unwrap_or_else(|| panic!("{}", tool.name));
            let required: Vec<&str> = tool.input_schema["required"]
                .as_array()
                .map(|items| items.iter().filter_map(Value::as_str).collect())
                .unwrap_or_default();
            for (name, property) in properties {
                let is_optional = !required.contains(&name.as_str());
                if is_optional {
                    assert!(
                        property.get("default").is_some(),
                        "{}.{name} is optional but has no default",
                        tool.name
                    );
                } else {
                    assert!(
                        property.get("default").is_none(),
                        "{}.{name} is required yet has a default",
                        tool.name
                    );
                }
            }
        }
    }

    #[test]
    fn every_tool_is_described_for_a_model() {
        for tool in registry() {
            assert!(
                tool.description.len() > 120,
                "{}: description too short to be useful",
                tool.name
            );
            assert!(!tool.title.is_empty());
            assert!(
                tool.description.chars().count() < 1_200,
                "{}: description is too long",
                tool.name
            );
            assert_eq!(tool.input_schema["type"], "object");
            assert_eq!(
                tool.input_schema["additionalProperties"], false,
                "{} must reject unknown arguments",
                tool.name
            );
            assert_eq!(tool.output_schema["type"], "object");
            assert!(tool.input_schema.get("outputSchema").is_none());
        }
    }

    #[test]
    fn definitions_carry_the_schema_pair_and_read_only_annotations() {
        let tool = find("list_entities").expect("registered");
        let definition = tool.definition();
        assert_eq!(definition["name"], "list_entities");
        assert_eq!(definition["title"], "List and search entities");
        assert_eq!(
            definition["inputSchema"]["properties"]["domain"]["default"],
            ""
        );
        assert_eq!(
            definition["outputSchema"]["properties"]["entities"]["items"]["properties"]
                ["entity_id"]["type"],
            "string"
        );
        assert_eq!(definition["annotations"]["readOnlyHint"], true);
        assert_eq!(definition["annotations"]["destructiveHint"], false);
        assert_eq!(definition["annotations"]["idempotentHint"], true);
        assert_eq!(definition["annotations"]["openWorldHint"], false);
        assert!(find("call_service").is_none(), "no write tools are exposed");
        assert!(registry()
            .iter()
            .all(|tool| !tool.name.contains("set") && !tool.name.contains("call")));
    }

    #[test]
    fn argument_names_are_snake_case_and_documented() {
        for tool in registry() {
            let properties = tool.input_schema["properties"].as_object().unwrap();
            for (name, property) in properties {
                assert!(
                    name.chars().all(|c| c.is_ascii_lowercase() || c == '_'),
                    "{}.{name} is not snake_case",
                    tool.name
                );
                let description = property["description"].as_str().unwrap_or_default();
                assert!(
                    description.len() > 12,
                    "{}.{name} has a thin description",
                    tool.name
                );
                assert!(
                    property["type"].is_string() || property["anyOf"].is_array(),
                    "{}.{name} lacks a type",
                    tool.name
                );
            }
        }
    }

    #[test]
    fn tools_list_pages_over_the_registry() {
        let total = registry().len();
        let first = list_definitions("", 5).expect("first page");
        assert_eq!(first["tools"].as_array().unwrap().len(), 5);
        assert!(first.get("nextCursor").is_some());

        let second_cursor = first["nextCursor"].as_str().unwrap().to_string();
        let second = list_definitions(&second_cursor, 5).expect("second page");
        let names: Vec<&str> = first["tools"]
            .as_array()
            .unwrap()
            .iter()
            .chain(second["tools"].as_array().unwrap())
            .map(|tool| tool["name"].as_str().unwrap())
            .collect();
        assert!(names.windows(2).all(|pair| pair[0] < pair[1]), "{names:?}");

        let mut cursor = String::new();
        let mut seen = 0;
        loop {
            let page_result = list_definitions(&cursor, 5).expect("page");
            let items = page_result["tools"].as_array().unwrap();
            assert!(!items.is_empty() || cursor.is_empty());
            seen += items.len();
            match page_result.get("nextCursor").and_then(Value::as_str) {
                Some(next) => cursor = next.to_string(),
                None => break,
            }
        }
        assert_eq!(seen, total, "paging must visit every tool exactly once");
        assert_eq!(
            list_definitions("", total).unwrap()["tools"]
                .as_array()
                .unwrap()
                .len(),
            total
        );
        assert!(
            list_definitions("", total)
                .unwrap()
                .get("nextCursor")
                .is_none(),
            "the last page omits nextCursor"
        );
    }

    #[test]
    fn a_bad_tools_list_cursor_is_reported_not_ignored() {
        let problem = list_definitions("garbage", 5).expect_err("must be rejected");
        assert!(problem.contains("cursor"));
    }

    #[test]
    fn unknown_tools_are_named_in_the_error() {
        let message = CallError::Unknown("turn_on".into()).message();
        assert!(message.contains("turn_on"));
        assert!(message.contains("tools/list"));
        assert_eq!(CallError::Unknown("x".into()).kind(), "unknown-tool");
    }

    #[test]
    fn schemas_are_valid_json_schema_shaped_objects() {
        for tool in registry() {
            for (label, schema) in [
                ("input", &tool.input_schema),
                ("output", &tool.output_schema),
            ] {
                let object = schema
                    .as_object()
                    .unwrap_or_else(|| panic!("{} {label} schema", tool.name));
                assert_eq!(object["type"], json!("object"));
                assert!(object.contains_key("properties"));
                assert!(object.contains_key("additionalProperties"));
                for (name, property) in object["properties"].as_object().unwrap() {
                    assert!(
                        property.is_object(),
                        "{} {label}.{name} must be a subschema",
                        tool.name
                    );
                    assert!(
                        property.get("description").is_some(),
                        "{} {label}.{name} must be described",
                        tool.name
                    );
                }
                if let Some(required) = schema.get("required") {
                    for name in required.as_array().unwrap() {
                        assert!(
                            object["properties"].get(name.as_str().unwrap()).is_some(),
                            "{} {label} requires an undeclared property",
                            tool.name
                        );
                    }
                }
            }
        }
    }
}
