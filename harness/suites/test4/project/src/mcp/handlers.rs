//! Tool implementations. Every handler is read-only: one or more `GET` requests
//! against Home Assistant, projected down to what a model can actually use.
//!
//! Handlers work on already-validated [`Args`], so every argument can be read
//! unconditionally. They return `structuredContent` shaped exactly like the
//! `outputSchema` declared in [`crate::mcp::tools`].

use std::collections::{BTreeMap, HashMap, HashSet};

use serde_json::{json, Map, Value};

use crate::error::HaError;
use crate::ha::model::State;
use crate::ha::HaClient;
use crate::mcp::args::Args;
use crate::timestamp::{self, Micros};
use crate::util::{page, truncate_chars, Cursor, Page};

/// Per-line cap for the error log: a single traceback should not crowd out the
/// rest of the tail.
const MAX_LINE_CHARS: usize = 500;

/// How many example entities to show per domain.
const EXAMPLE_ENTITIES: usize = 3;

/// Failure kinds a handler can report; both become `isError: true` results.
#[derive(Debug)]
pub enum HandlerError {
    /// Rejected after schema validation, e.g. an unparseable timestamp.
    Invalid(Vec<String>),
    /// Home Assistant could not answer.
    Api(HaError),
}

impl HandlerError {
    pub fn message(&self) -> String {
        match self {
            HandlerError::Invalid(problems) => problems.join("; "),
            HandlerError::Api(error) => {
                let hint = error.hint();
                if hint.is_empty() {
                    error.to_string()
                } else {
                    format!("{error} — {}", crate::util::one_line(hint))
                }
            }
        }
    }

    /// Stable label for logs.
    pub fn kind(&self) -> &'static str {
        match self {
            HandlerError::Invalid(_) => "invalid-arguments",
            HandlerError::Api(error) => error.kind(),
        }
    }
}

impl From<HaError> for HandlerError {
    fn from(error: HaError) -> Self {
        HandlerError::Api(error)
    }
}

/// A bad cursor or any other post-validation complaint arrives as plain text.
impl From<String> for HandlerError {
    fn from(problem: String) -> Self {
        HandlerError::Invalid(vec![problem])
    }
}

// ---------------------------------------------------------------------------
// get_instance_info
// ---------------------------------------------------------------------------

/// Fields of `/api/config` worth surfacing as an instance summary.
const INSTANCE_KEYS: &[&str] = &[
    "location_name",
    "version",
    "installation_type",
    "state",
    "external_url",
    "internal_url",
    "latitude",
    "longitude",
    "elevation",
    "unit_system",
    "time_zone",
    "country",
    "currency",
    "developer_mode",
    "safe_mode",
    "recovery_mode",
];

/// A one-call orientation: what is this instance and how big is it.
pub fn instance_info(_args: &Args, client: &HaClient) -> Result<Value, HandlerError> {
    // Without the configuration document there is nothing to summarise.
    let config = client.configuration()?;

    let mut unavailable: Vec<Value> = Vec::new();
    let api = optional("api_status", &mut unavailable, || client.api_status());
    let states = optional("entities", &mut unavailable, || client.states());
    let catalog = optional("services", &mut unavailable, || client.service_catalog());
    let service_sizes = catalog.as_ref().and_then(service_sizes);
    let events = optional("event_types", &mut unavailable, || client.event_types());

    let mut counts = Map::new();
    counts.insert(
        "components".into(),
        count_of(list_len(config.get("components"))),
    );
    counts.insert("entities".into(), count_of(states.as_ref().map(Vec::len)));
    counts.insert(
        "entity_domains".into(),
        count_of(states.as_ref().map(|states| {
            let mut domains: Vec<&str> = states.iter().map(State::domain).collect();
            domains.sort_unstable();
            domains.dedup();
            domains.len()
        })),
    );
    counts.insert(
        "service_domains".into(),
        count_of(service_sizes.map(|(domains, _)| domains)),
    );
    counts.insert(
        "services".into(),
        count_of(service_sizes.map(|(_, services)| services)),
    );
    counts.insert(
        "event_types".into(),
        count_of(events.as_ref().map(Vec::len)),
    );

    let mut out = Map::new();
    out.insert("api_running".into(), json!(api.is_some()));
    out.insert(
        "api_message".into(),
        api.map(Value::String).unwrap_or(Value::Null),
    );
    out.insert(
        "instance".into(),
        Value::Object(pick(&config, INSTANCE_KEYS)),
    );
    out.insert("counts".into(), Value::Object(counts));
    out.insert("unavailable".into(), Value::Array(unavailable));
    Ok(Value::Object(out))
}

/// Runs a non-essential call, recording a failure instead of aborting.
fn optional<T>(
    section: &str,
    unavailable: &mut Vec<Value>,
    call: impl FnOnce() -> Result<T, HaError>,
) -> Option<T> {
    match call() {
        Ok(value) => Some(value),
        Err(error) => {
            crate::debug!("get_instance_info: {section} unavailable: {error}");
            unavailable.push(json!({ "section": section, "reason": error.to_string() }));
            None
        }
    }
}

fn count_of(value: Option<usize>) -> Value {
    match value {
        Some(value) => json!(value as i64),
        None => Value::Null,
    }
}

fn list_len(value: Option<&Value>) -> Option<usize> {
    value.and_then(Value::as_array).map(Vec::len)
}

fn pick(source: &Value, keys: &[&str]) -> Map<String, Value> {
    let mut out = Map::new();
    for key in keys {
        if let Some(value) = source.get(*key) {
            out.insert((*key).to_string(), value.clone());
        }
    }
    out
}

// ---------------------------------------------------------------------------
// get_config
// ---------------------------------------------------------------------------

/// The raw configuration document, optionally narrowed to a few sections.
pub fn config(args: &Args, client: &HaClient) -> Result<Value, HandlerError> {
    let document = client.configuration()?;
    let requested = args.strings("sections");

    let mut missing_sections: Vec<String> = Vec::new();
    let mut projection = if requested.is_empty() {
        match &document {
            Value::Object(map) => map.clone(),
            other => {
                let mut single = Map::new();
                single.insert("config".into(), other.clone());
                single
            }
        }
    } else {
        let mut kept = Map::new();
        for section in &requested {
            match document.get(section) {
                Some(value) => {
                    kept.insert(section.clone(), value.clone());
                }
                None => missing_sections.push(section.clone()),
            }
        }
        kept
    };

    let total_keys = match &document {
        Value::Object(map) => map.len(),
        _ => 0,
    };
    let components_count = list_len(document.get("components")).unwrap_or(0);

    if !args.boolean("include_components") {
        projection.remove("components");
    }
    let components_included = projection.contains_key("components");

    let mut returned_keys: Vec<String> = projection.keys().cloned().collect();
    returned_keys.sort();

    let mut out = Map::new();
    out.insert("config".into(), Value::Object(projection));
    out.insert("total_keys".into(), json!(total_keys as i64));
    out.insert("returned_keys".into(), json!(returned_keys));
    out.insert("components_count".into(), json!(components_count as i64));
    out.insert("components_included".into(), json!(components_included));
    out.insert("missing_sections".into(), json!(missing_sections));
    Ok(Value::Object(out))
}

// ---------------------------------------------------------------------------
// list_integrations
// ---------------------------------------------------------------------------

/// Which integrations and platforms are loaded, grouped by top-level domain.
pub fn list_integrations(args: &Args, client: &HaClient) -> Result<Value, HandlerError> {
    let document = client.configuration()?;
    let components: Vec<&str> = document
        .get("components")
        .and_then(Value::as_array)
        .map(|items| items.iter().filter_map(Value::as_str).collect())
        .unwrap_or_default();

    let mut grouped: BTreeMap<&str, Vec<&str>> = BTreeMap::new();
    for component in &components {
        let domain = component.split('.').next().unwrap_or(component);
        grouped.entry(domain).or_default().push(component);
    }

    let needle = args.string("query").trim().to_ascii_lowercase();
    let matched: Vec<(&str, &Vec<&str>)> = grouped
        .iter()
        .filter(|(domain, components)| {
            needle.is_empty()
                || domain.contains(&needle)
                || components
                    .iter()
                    .any(|component| component.contains(&needle))
        })
        .map(|(domain, components)| (*domain, components))
        .collect();

    let limit = args.integer("limit") as usize;
    let Page { start, next } = page(matched.len(), args.string("cursor"), limit)?;
    let items: Vec<Value> = matched[start..start + matched[start..].len().min(limit)]
        .iter()
        .map(|(domain, components)| {
            json!({
                "domain": domain,
                "component_count": components.len() as i64,
                "components": components.iter().map(|component| component.to_string()).collect::<Vec<_>>(),
            })
        })
        .collect();

    let mut out = page_fields(matched.len(), items.len(), &next);
    out.insert("total_components".into(), json!(components.len() as i64));
    out.insert("total_domains".into(), json!(grouped.len() as i64));
    out.insert("domains".into(), Value::Array(items));
    Ok(Value::Object(out))
}

// ---------------------------------------------------------------------------
// list_domains
// ---------------------------------------------------------------------------

/// Entity domains with their sizes and a few representative entities.
pub fn list_domains(args: &Args, client: &HaClient) -> Result<Value, HandlerError> {
    let states = client.states()?;
    let total_entities = states.len();

    let mut grouped: BTreeMap<&str, Vec<&State>> = BTreeMap::new();
    for state in &states {
        grouped.entry(state.domain()).or_default().push(state);
    }
    for entities in grouped.values_mut() {
        entities.sort_by(|a, b| a.entity_id.cmp(&b.entity_id));
    }

    let rows: Vec<DomainRow> = grouped
        .into_iter()
        .map(|(domain, entities)| DomainRow {
            entity_count: entities.len(),
            examples: entities
                .iter()
                .take(EXAMPLE_ENTITIES)
                .map(|state| state.entity_id.clone())
                .collect(),
            common_states: top_states(&entities),
            domain: domain.to_string(),
        })
        .collect();

    let needle = args.string("query").trim().to_ascii_lowercase();
    let mut matched: Vec<&DomainRow> = rows
        .iter()
        .filter(|row| needle.is_empty() || row.domain.contains(&needle))
        .collect();

    if args.string("sort_by") == "domain" {
        matched.sort_by(|a, b| a.domain.cmp(&b.domain));
    } else {
        matched.sort_by(|a, b| {
            b.entity_count
                .cmp(&a.entity_count)
                .then_with(|| a.domain.cmp(&b.domain))
        });
    }

    let limit = args.integer("limit") as usize;
    let Page { start, next } = page(matched.len(), args.string("cursor"), limit)?;
    let items: Vec<Value> = matched[start..start + matched[start..].len().min(limit)]
        .iter()
        .map(|row| {
            json!({
                "domain": row.domain,
                "entity_count": row.entity_count as i64,
                "example_entities": row.examples,
                "common_states": row.common_states,
            })
        })
        .collect();

    let mut out = page_fields(matched.len(), items.len(), &next);
    out.insert("total_entities".into(), json!(total_entities as i64));
    out.insert("total_domains".into(), json!(rows.len() as i64));
    out.insert("domains".into(), Value::Array(items));
    Ok(Value::Object(out))
}

struct DomainRow {
    domain: String,
    entity_count: usize,
    examples: Vec<String>,
    common_states: Vec<Value>,
}

/// The three most frequent `state` values in a domain.
fn top_states(states: &[&State]) -> Vec<Value> {
    let mut counts: BTreeMap<&str, usize> = BTreeMap::new();
    for state in states {
        *counts.entry(state.state.as_str()).or_default() += 1;
    }
    let mut ranked: Vec<(&str, usize)> = counts.into_iter().collect();
    ranked.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(b.0)));
    ranked
        .into_iter()
        .take(3)
        .map(|(state, count)| json!({ "state": state, "count": count as i64 }))
        .collect()
}

// ---------------------------------------------------------------------------
// list_entities / get_entity / get_entities
// ---------------------------------------------------------------------------

/// Searches the current states with filters that Home Assistant's REST API does
/// not offer server-side.
pub fn list_entities(args: &Args, client: &HaClient) -> Result<Value, HandlerError> {
    let mut states = client.states()?;
    let total_entities = states.len();

    let needle = terms(args.string("query"));
    let domain = args.string("domain").trim().to_ascii_lowercase();
    let wanted_state = args.string("state").trim().to_ascii_lowercase();
    let include_attributes = args.boolean("include_attributes");
    let hide_unavailable = args.boolean("only_available");

    states.retain(|state| {
        (domain.is_empty() || state.domain().eq_ignore_ascii_case(&domain))
            && (wanted_state.is_empty() || state.state.eq_ignore_ascii_case(&wanted_state))
            && (!hide_unavailable || !state.is_hidden())
            && (needle.is_empty()
                || matches(
                    &needle,
                    &[
                        state.entity_id.as_str(),
                        state.object_id(),
                        state.friendly_name().unwrap_or(""),
                    ],
                ))
    });

    sort_states(
        &mut states,
        args.string("sort_by"),
        args.string("sort_dir") != "desc",
    );

    let limit = args.integer("limit") as usize;
    let Page { start, next } = page(states.len(), args.string("cursor"), limit)?;
    let selected = &states[start..start + states[start..].len().min(limit)];
    let items: Vec<Value> = selected
        .iter()
        .map(|state| entity_item(state, include_attributes))
        .collect();

    let mut out = page_fields(states.len(), items.len(), &next);
    out.insert("total_entities".into(), json!(total_entities as i64));
    out.insert("entities".into(), Value::Array(items));
    Ok(Value::Object(out))
}

/// One entity in full, including every attribute.
pub fn get_entity(args: &Args, client: &HaClient) -> Result<Value, HandlerError> {
    let entity_id = args.string("entity_id").trim();
    let state = client.state(entity_id)?;

    let mut out = Map::new();
    out.insert("entity_id".into(), state.entity_id.clone().into());
    out.insert("domain".into(), state.domain().into());
    out.insert("object_id".into(), state.object_id().into());
    out.insert("state".into(), state.state.clone().into());
    out.insert(
        "friendly_name".into(),
        state
            .friendly_name()
            .map(|name| Value::String(name.to_string()))
            .unwrap_or(Value::Null),
    );
    out.insert("attributes".into(), state.attributes.clone());
    out.insert("last_changed".into(), state.last_changed.clone().into());
    out.insert("last_reported".into(), state.last_reported.clone().into());
    out.insert("last_updated".into(), state.last_updated.clone().into());
    out.insert("hidden".into(), json!(state.is_hidden()));
    out.insert("extra".into(), Value::Object(state.extra.clone()));
    Ok(Value::Object(out))
}

/// Several entities at once, in one request.
pub fn get_entities(args: &Args, client: &HaClient) -> Result<Value, HandlerError> {
    let requested: Vec<String> = dedupe(args.strings("entity_ids"));
    if requested.is_empty() {
        return Err(HandlerError::Invalid(vec![
            "argument \"entity_ids\" must contain at least one entity id".to_string(),
        ]));
    }
    let include_attributes = args.boolean("include_attributes");

    let states = client.states()?;
    let index: HashMap<&str, &State> = states
        .iter()
        .map(|state| (state.entity_id.as_str(), state))
        .collect();

    let mut entities = Vec::new();
    let mut missing = Vec::new();
    for entity_id in &requested {
        match index.get(entity_id.as_str()) {
            Some(state) => entities.push(entity_item(state, include_attributes)),
            None => missing.push(Value::String(entity_id.clone())),
        }
    }

    let mut out = Map::new();
    out.insert("requested".into(), json!(requested.len() as i64));
    out.insert("found".into(), json!(entities.len() as i64));
    out.insert("missing".into(), Value::Array(missing));
    out.insert("entities".into(), Value::Array(entities));
    Ok(Value::Object(out))
}

/// The compact entity projection used by the list tools.
fn entity_item(state: &State, include_attributes: bool) -> Value {
    let mut item = state.summary();
    if include_attributes {
        if let Some(object) = item.as_object_mut() {
            object.insert("attributes".into(), state.attributes.clone());
        }
    }
    item
}

fn sort_states(states: &mut [State], sort_by: &str, ascending: bool) {
    let ordering = |a: &State, b: &State| match sort_by {
        "domain" => a
            .domain()
            .cmp(b.domain())
            .then_with(|| a.entity_id.cmp(&b.entity_id)),
        "friendly_name" => a
            .friendly_name()
            .unwrap_or("")
            .to_ascii_lowercase()
            .cmp(&b.friendly_name().unwrap_or("").to_ascii_lowercase())
            .then_with(|| a.entity_id.cmp(&b.entity_id)),
        "state" => a
            .state
            .to_ascii_lowercase()
            .cmp(&b.state.to_ascii_lowercase())
            .then_with(|| a.entity_id.cmp(&b.entity_id)),
        "last_updated" => a
            .last_updated
            .cmp(&b.last_updated)
            .then_with(|| a.entity_id.cmp(&b.entity_id)),
        _ => a.entity_id.cmp(&b.entity_id),
    };
    states.sort_by(|a, b| {
        let result = ordering(a, b);
        if ascending {
            result
        } else {
            result.reverse()
        }
    });
}

// ---------------------------------------------------------------------------
// list_services / get_service
// ---------------------------------------------------------------------------

/// The service catalog as a flat, filterable list.
pub fn list_services(args: &Args, client: &HaClient) -> Result<Value, HandlerError> {
    let catalog = client.service_catalog()?;
    let domains = service_domains(&catalog)?;
    let total_services: usize = domains.values().map(|services| services.len()).sum();

    let needle = terms(args.string("query"));
    let domain_filter = args.string("domain").trim().to_ascii_lowercase();

    let mut rows: Vec<ServiceRow> = Vec::new();
    for (domain, services) in &domains {
        for (service, definition) in services.iter() {
            let field_names: Vec<String> = definition
                .get("fields")
                .and_then(Value::as_object)
                .map(|fields| fields.keys().cloned().collect())
                .unwrap_or_default();
            rows.push(ServiceRow {
                domain: domain.clone(),
                service: service.clone(),
                name: definition
                    .get("name")
                    .and_then(Value::as_str)
                    .map(str::to_string),
                description: definition
                    .get("description")
                    .and_then(Value::as_str)
                    .map(str::to_string),
                targets_entities: definition.pointer("/target/entity_id").is_some(),
                field_count: field_names.len() as i64,
                field_names: sorted(field_names),
                required_fields: required_fields(definition),
            });
        }
    }
    rows.sort_by(|a, b| {
        (a.domain.as_str(), a.service.as_str()).cmp(&(b.domain.as_str(), b.service.as_str()))
    });

    let total_service_domains = domains.len();
    let matched: Vec<&ServiceRow> = rows
        .iter()
        .filter(|row| {
            (domain_filter.is_empty() || row.domain.eq_ignore_ascii_case(&domain_filter))
                && (needle.is_empty()
                    || matches(
                        &needle,
                        &[
                            row.domain.as_str(),
                            row.service.as_str(),
                            row.name.as_deref().unwrap_or(""),
                            row.description.as_deref().unwrap_or(""),
                        ],
                    ))
        })
        .collect();

    let limit = args.integer("limit") as usize;
    let Page { start, next } = page(matched.len(), args.string("cursor"), limit)?;
    let items: Vec<Value> = matched[start..start + matched[start..].len().min(limit)]
        .iter()
        .map(|row| {
            json!({
                "domain": row.domain,
                "service": row.service,
                "name": row.name,
                "description": row.description,
                "targets_entities": row.targets_entities,
                "field_count": row.field_count,
                "field_names": row.field_names,
                "required_fields": row.required_fields,
            })
        })
        .collect();

    let mut out = page_fields(matched.len(), items.len(), &next);
    out.insert(
        "total_service_domains".into(),
        json!(total_service_domains as i64),
    );
    out.insert("total_services".into(), json!(total_services as i64));
    out.insert("services".into(), Value::Array(items));
    Ok(Value::Object(out))
}

/// Everything one service accepts, including a worked example per field.
pub fn get_service(args: &Args, client: &HaClient) -> Result<Value, HandlerError> {
    let domain = args.string("domain").trim().to_ascii_lowercase();
    let service = args.string("service").trim().to_ascii_lowercase();
    let catalog = client.service_catalog()?;
    let domains = service_domains(&catalog)?;

    let services = domains.get(&domain).ok_or_else(|| HaError::NotFound {
        url: format!("service://{domain}"),
        detail: format!(
            "\"{domain}\" has no services in this instance; close domains: {}",
            nearest(&domain, domains.keys().map(String::as_str), 5)
        ),
    })?;
    let definition = services.get(&service).ok_or_else(|| HaError::NotFound {
        url: format!("service://{domain}.{service}"),
        detail: format!(
            "\"{domain}.{service}\" does not exist; services in \"{domain}\": {}",
            nearest(&service, services.keys().map(String::as_str), 8)
        ),
    })?;

    let fields = definition
        .get("fields")
        .cloned()
        .unwrap_or_else(|| Value::Object(Map::new()));
    let summaries: Vec<Value> = fields
        .as_object()
        .map(|fields| {
            fields
                .iter()
                .map(|(name, field)| {
                    let selector = field.get("selector");
                    json!({
                        "name": name,
                        "required": field.get("required").and_then(Value::as_bool).unwrap_or(false),
                        "description": field.get("description").cloned().unwrap_or(Value::Null),
                        "selector": selector.and_then(Value::as_object).and_then(|map| map.keys().next()).cloned().map(Value::String).unwrap_or(Value::Null),
                        "options": select_options(selector),
                        "example": example_for(field),
                    })
                })
                .collect()
        })
        .unwrap_or_default();

    let mut out = Map::new();
    out.insert("domain".into(), domain.into());
    out.insert("service".into(), service.into());
    out.insert(
        "name".into(),
        definition.get("name").cloned().unwrap_or(Value::Null),
    );
    out.insert(
        "description".into(),
        definition
            .get("description")
            .cloned()
            .unwrap_or(Value::Null),
    );
    out.insert(
        "target".into(),
        definition
            .get("target")
            .cloned()
            .unwrap_or_else(|| Value::Object(Map::new())),
    );
    out.insert("fields".into(), fields);
    out.insert("field_summaries".into(), Value::Array(summaries));
    Ok(Value::Object(out))
}

struct ServiceRow {
    domain: String,
    service: String,
    name: Option<String>,
    description: Option<String>,
    targets_entities: bool,
    field_count: i64,
    field_names: Vec<String>,
    required_fields: Vec<String>,
}

/// Number of service domains and of services overall, for the instance summary.
/// `/api/services` is a list, not a map, so it goes through the same parsing the
/// service tools use.
fn service_sizes(catalog: &Value) -> Option<(usize, usize)> {
    let domains = service_domains(catalog).ok()?;
    let services = domains.values().map(|services| services.len()).sum();
    Some((domains.len(), services))
}

/// `/api/services` is a list of `{domain, services}` entries keyed by domain.
fn service_domains(catalog: &Value) -> Result<BTreeMap<String, &Map<String, Value>>, HandlerError> {
    let entries = catalog.as_array().ok_or_else(|| HaError::InvalidResponse {
        url: "GET /api/services".into(),
        reason: "expected an array of {domain, services} entries".into(),
    })?;
    let mut out: BTreeMap<String, &Map<String, Value>> = BTreeMap::new();
    for entry in entries {
        let Some(domain) = entry.get("domain").and_then(Value::as_str) else {
            continue;
        };
        if let Some(services) = entry.get("services").and_then(Value::as_object) {
            out.insert(domain.to_string(), services);
        }
    }
    Ok(out)
}

fn required_fields(definition: &Value) -> Vec<String> {
    definition
        .get("fields")
        .and_then(Value::as_object)
        .map(|fields| {
            fields
                .iter()
                .filter(|(_, field)| {
                    field
                        .get("required")
                        .and_then(Value::as_bool)
                        .unwrap_or(false)
                })
                .map(|(name, _)| name.clone())
                .collect()
        })
        .unwrap_or_default()
}

/// Options offered by a `select` selector, if the field has one.
fn select_options(selector: Option<&Value>) -> Vec<Value> {
    selector
        .and_then(|selector| selector.pointer("/select/options"))
        .and_then(Value::as_array)
        .map(|options| {
            options
                .iter()
                .map(|option| match option {
                    Value::Object(map) => map.get("value").cloned().unwrap_or(Value::Null),
                    other => other.clone(),
                })
                .collect()
        })
        .unwrap_or_default()
}

/// A plausible value for a field, derived from its selector.
/// An illustrative value for a field. Home Assistant's own `example` wins; when
/// there is none, something is derived from the selector, and a field whose
/// sensible value cannot be guessed (an entity id, a text field) gets `null`
/// rather than an invention.
fn example_for(field: &Value) -> Value {
    if let Some(example) = field.get("example") {
        if !example.is_null() {
            return example.clone();
        }
    }
    let selector = field.get("selector");
    let Some(selector) = selector.and_then(Value::as_object) else {
        return Value::Null;
    };
    if let Some(options) = selector
        .get("select")
        .and_then(Value::as_object)
        .and_then(|select| select.get("options"))
        .and_then(Value::as_array)
        .and_then(|options| options.first())
    {
        return match options {
            Value::Object(map) => map.get("value").cloned().unwrap_or(Value::Null),
            other => other.clone(),
        };
    }
    if let Some(number) = selector.get("number").and_then(Value::as_object) {
        // The midpoint illustrates a bounded number better than an extreme.
        if let (Some(min), Some(max)) = (
            number.get("min").and_then(Value::as_f64),
            number.get("max").and_then(Value::as_f64),
        ) {
            return json!(((min + max) / 2.0) as i64);
        }
    }
    for (kind, example) in [
        ("number", json!(1)),
        ("boolean", json!(true)),
        ("time", json!("18:30:00")),
        ("date", json!("2026-01-01")),
        ("datetime", json!("2026-01-01T18:30:00Z")),
        ("color_rgb", json!("#ffaa00")),
        ("color_hex", json!("ffaa00")),
        ("entity", json!("light.living_room")),
        ("target", json!({ "entity_id": "light.living_room" })),
        ("area", json!("living_room")),
        ("device", json!("abcdef1234567890")),
        ("text", json!("some text")),
        ("object", json!({})),
    ] {
        if selector.contains_key(kind) {
            return example;
        }
    }
    Value::Null
}

// ---------------------------------------------------------------------------
// get_entity_history
// ---------------------------------------------------------------------------

/// Recent logbook entries, narrowed to an entity and/or a time window.
pub fn get_entity_history(args: &Args, client: &HaClient) -> Result<Value, HandlerError> {
    let entity_filter = args.string("entity_id").trim().to_ascii_lowercase();
    // Kept as written: the window is echoed back to the caller verbatim, and the
    // parser accepts both `Z` and `z`.
    let start_text = args.string("start_time").trim();
    let end_text = args.string("end_time").trim();

    let start = window_bound("start_time", start_text)?;
    let end = window_bound("end_time", end_text)?;
    if let (Some(start), Some(end)) = (start, end) {
        if end <= start {
            return Err(HandlerError::Invalid(vec![format!(
                "argument \"end_time\" ({end_text}) must be after \"start_time\" ({start_text})"
            )]));
        }
    }

    let entries = client.logbook(text_arg(start_text), text_arg(end_text))?;
    let total_entries = entries.len();

    let needle = terms(args.string("query"));
    let mut matched: Vec<&Value> = entries
        .iter()
        .filter(|entry| {
            entry_matches_entity(entry, &entity_filter)
                && within_window(entry, start, end)
                && (needle.is_empty()
                    || matches(
                        &needle,
                        &[
                            entry.get("entity_id").and_then(Value::as_str).unwrap_or(""),
                            entry.get("name").and_then(Value::as_str).unwrap_or(""),
                            entry.get("message").and_then(Value::as_str).unwrap_or(""),
                            entry.get("state").and_then(Value::as_str).unwrap_or(""),
                        ],
                    ))
        })
        .collect();

    matched.sort_by(|a, b| {
        let key = |entry: &&Value| {
            (
                entry
                    .get("when")
                    .and_then(Value::as_str)
                    .and_then(|text| timestamp::parse(text).ok())
                    .unwrap_or(i128::MIN),
                entry
                    .get("entity_id")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string(),
            )
        };
        key(b).cmp(&key(a))
    });

    let limit = args.integer("limit") as usize;
    let Page {
        start: offset,
        next,
    } = page(matched.len(), args.string("cursor"), limit)?;
    let items: Vec<Value> = matched[offset..offset + matched[offset..].len().min(limit)]
        .iter()
        .map(|entry| (*entry).clone())
        .collect();

    let mut out = page_fields(matched.len(), items.len(), &next);
    out.insert("total_entries".into(), json!(total_entries as i64));
    out.insert("entity_filter".into(), optional_echo(&entity_filter));
    out.insert("window_start".into(), optional_echo(start_text));
    out.insert("window_end".into(), optional_echo(end_text));
    out.insert("entries".into(), Value::Array(items));
    Ok(Value::Object(out))
}

/// Parses an optional time argument, naming it in the failure message.
fn window_bound(name: &str, text: &str) -> Result<Option<Micros>, HandlerError> {
    if text.is_empty() {
        return Ok(None);
    }
    timestamp::parse(text)
        .map(Some)
        .map_err(|error| HandlerError::Invalid(vec![format!("argument \"{name}\": {error}")]))
}

fn text_arg(text: &str) -> Option<&str> {
    if text.is_empty() {
        None
    } else {
        Some(text)
    }
}

fn optional_echo(text: &str) -> Value {
    if text.is_empty() {
        Value::Null
    } else {
        Value::String(text.to_string())
    }
}

/// An empty filter matches everything; a filter without a dot matches a domain.
fn entry_matches_entity(entry: &Value, filter: &str) -> bool {
    if filter.is_empty() {
        return true;
    }
    match entry.get("entity_id").and_then(Value::as_str) {
        Some(entity_id) => {
            entity_id.eq_ignore_ascii_case(filter)
                || (!filter.contains('.')
                    && entity_id
                        .to_ascii_lowercase()
                        .starts_with(&format!("{filter}.")))
        }
        None => false,
    }
}

fn within_window(entry: &Value, start: Option<Micros>, end: Option<Micros>) -> bool {
    if start.is_none() && end.is_none() {
        return true;
    }
    let Some(when) = entry
        .get("when")
        .and_then(Value::as_str)
        .and_then(|text| timestamp::parse(text).ok())
    else {
        // Entries that look nothing like an event (no `when`) cannot be placed
        // in a requested window, so they are left out rather than guessed at.
        return false;
    };
    start.is_none_or(|start| when >= start) && end.is_none_or(|end| when <= end)
}

// ---------------------------------------------------------------------------
// get_error_log
// ---------------------------------------------------------------------------

/// The tail of Home Assistant's error log, filtered line by line.
pub fn get_error_log(args: &Args, client: &HaClient) -> Result<Value, HandlerError> {
    let text = client.error_log()?;
    let contains = args.string("contains").trim().to_ascii_lowercase();
    let level = args.string("level").to_ascii_lowercase();
    let max_lines = args.integer("max_lines").max(1) as usize;
    let tail = args.boolean("tail");

    let lines: Vec<&str> = text.lines().collect();
    let matched: Vec<&str> = lines
        .iter()
        .copied()
        .filter(|line| {
            (level == "any"
                || line
                    .to_ascii_uppercase()
                    .contains(&format!("{} ", level.to_ascii_uppercase())))
                && (contains.is_empty() || line.to_ascii_lowercase().contains(&contains))
        })
        .collect();

    let truncated = matched.len() > max_lines;
    let selected: &[&str] = if truncated {
        if tail {
            &matched[matched.len() - max_lines..]
        } else {
            &matched[..max_lines]
        }
    } else {
        &matched[..]
    };

    let mut out = Map::new();
    out.insert("total_lines".into(), json!(lines.len() as i64));
    out.insert("matched".into(), json!(matched.len() as i64));
    out.insert("returned".into(), json!(selected.len() as i64));
    out.insert("truncated".into(), json!(truncated));
    out.insert("tail".into(), json!(tail));
    out.insert("level_filter".into(), level.into());
    out.insert(
        "contains".into(),
        optional_echo(args.string("contains").trim()),
    );
    out.insert(
        "lines".into(),
        Value::Array(
            selected
                .iter()
                .map(|line| truncate_chars(line, MAX_LINE_CHARS).0.into())
                .collect(),
        ),
    );
    Ok(Value::Object(out))
}

// ---------------------------------------------------------------------------
// list_events
// ---------------------------------------------------------------------------

/// Event types the instance knows about, with listener counts.
pub fn list_events(args: &Args, client: &HaClient) -> Result<Value, HandlerError> {
    let events = client.event_types()?;
    let needle = terms(args.string("query"));

    let mut matched: Vec<&crate::ha::model::EventTypeInfo> = events
        .iter()
        .filter(|event| needle.is_empty() || matches(&needle, &[event.event.as_str()]))
        .collect();
    matched.sort_by(|a, b| a.event.cmp(&b.event));

    let limit = args.integer("limit") as usize;
    let Page { start, next } = page(matched.len(), args.string("cursor"), limit)?;
    let items: Vec<Value> = matched[start..start + matched[start..].len().min(limit)]
        .iter()
        .map(|event| json!({ "event": event.event, "listener_count": event.listener_count as i64 }))
        .collect();

    let mut out = page_fields(matched.len(), items.len(), &next);
    out.insert("total_event_types".into(), json!(events.len() as i64));
    out.insert("event_types".into(), Value::Array(items));
    Ok(Value::Object(out))
}

// ---------------------------------------------------------------------------
// shared helpers
// ---------------------------------------------------------------------------

/// The `matched` / `returned` / `next_cursor` trio every list result carries.
fn page_fields(matched: usize, returned: usize, next: &Option<Cursor>) -> Map<String, Value> {
    let mut fields = Map::new();
    fields.insert("matched".into(), json!(matched as i64));
    fields.insert("returned".into(), json!(returned as i64));
    fields.insert(
        "next_cursor".into(),
        match next {
            Some(cursor) => Value::String(cursor.encode()),
            None => Value::Null,
        },
    );
    fields
}

/// Lowercase search terms; every term must match somewhere (AND).
fn terms(query: &str) -> Vec<String> {
    query
        .trim()
        .to_ascii_lowercase()
        .split_whitespace()
        .map(str::to_string)
        .collect()
}

fn matches(terms: &[String], haystacks: &[&str]) -> bool {
    let haystacks: Vec<String> = haystacks
        .iter()
        .map(|haystack| haystack.to_ascii_lowercase())
        .collect();
    terms.iter().all(|term| {
        haystacks
            .iter()
            .any(|haystack| haystack.contains(term.as_str()))
    })
}

fn dedupe(values: Vec<String>) -> Vec<String> {
    let mut seen = HashSet::new();
    let mut out = Vec::new();
    for value in values {
        let trimmed = value.trim();
        if trimmed.is_empty() || !seen.insert(trimmed.to_ascii_lowercase()) {
            continue;
        }
        out.push(trimmed.to_string());
    }
    out
}

fn sorted(mut values: Vec<String>) -> Vec<String> {
    values.sort();
    values
}

/// A comma-separated list of the closest names, for "did you mean" messages.
fn nearest<'a, I: Iterator<Item = &'a str>>(wanted: &str, candidates: I, take: usize) -> String {
    let candidates: Vec<&str> = candidates.collect();
    let mut scored: Vec<(usize, String)> = candidates
        .iter()
        .filter_map(|candidate| {
            let score = crate::util::edit_distance(wanted, candidate);
            if score <= 4 || candidate.contains(wanted) || wanted.contains(candidate) {
                Some((score, (*candidate).to_string()))
            } else {
                None
            }
        })
        .collect();
    scored.sort();
    let names: Vec<String> = scored
        .into_iter()
        .take(take)
        .map(|(_, name)| name)
        .collect();
    if !names.is_empty() {
        return names.join(", ");
    }
    // Nothing resembles what was asked for. Listing what does exist is still the
    // fastest way out for a caller that invented a plausible-sounding name.
    let mut fallback = candidates
        .iter()
        .map(|candidate| candidate.to_string())
        .collect::<Vec<_>>();
    fallback.sort();
    fallback.truncate(take);
    if fallback.is_empty() {
        "there are no names to suggest".to_string()
    } else {
        format!(
            "none of these resemble \"{wanted}\"; available: {}",
            fallback.join(", ")
        )
    }
}
