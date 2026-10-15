//! JSON Schema construction for tool `inputSchema` / `outputSchema`.
//!
//! The builders exist so that the argument *contract* (type, range, default,
//! description) is written once here and then enforced by
//! [`crate::mcp::args`] at call time - the schema is the single source of truth.

use serde_json::{json, Map, Value};

/// An `inputSchema` for an object whose properties are all described.
///
/// `additionalProperties` is closed so a misspelled argument is reported
/// instead of silently ignored.
pub fn input_schema(properties: &[(&str, Value)], required: &[&str]) -> Value {
    let mut schema = describe(json!({ "type": "object" }))
        .with_description("Every argument this tool accepts. Unknown arguments are rejected.");
    schema["properties"] = properties_to_object(properties);
    schema["additionalProperties"] = json!(false);
    if !required.is_empty() {
        schema["required"] = json!(required);
    }
    schema
}

/// Same shape as [`input_schema`], used to describe `structuredContent`.
///
/// `default` is dropped: it describes input convenience, not output, and leaving
/// it in would suggest the server fills fields in after the fact.
pub fn output_schema(properties: &[(&str, Value)], required: &[&str]) -> Value {
    let stripped: Vec<(&str, Value)> = properties
        .iter()
        .map(|(name, schema)| (*name, without_default(schema)))
        .collect();
    input_schema(&stripped, required)
}

/// A string property.
pub fn string(description: &str) -> Value {
    describe(json!({ "type": "string" })).with_description(description)
}

/// A string property restricted to a fixed set of values.
pub fn string_enum(description: &str, values: &[&str]) -> Value {
    describe(json!({ "type": "string", "enum": values })).with_description(description)
}

/// An integer property with an inclusive range and a default.
pub fn integer(description: &str, minimum: i64, maximum: i64, default: i64) -> Value {
    describe(
        json!({ "type": "integer", "minimum": minimum, "maximum": maximum, "default": default }),
    )
    .with_description(description)
}

/// A boolean property with a default.
pub fn boolean(description: &str, default: bool) -> Value {
    describe(json!({ "type": "boolean", "default": default })).with_description(description)
}

/// An array of strings with a default (usually empty).
pub fn string_array(description: &str, default: &[&str]) -> Value {
    describe(json!({
        "type": "array",
        "items": { "type": "string" },
        "default": default,
        "uniqueItems": true,
    }))
    .with_description(description)
}

/// An array of arbitrary JSON objects, used when the payload is passed through
/// from Home Assistant and therefore cannot be described field by field.
pub fn json_array(description: &str) -> Value {
    describe(json!({ "type": "array", "items": true })).with_description(description)
}

/// An arbitrary JSON object passed through from Home Assistant.
pub fn json_object(description: &str) -> Value {
    describe(json!({ "type": "object" })).with_description(description)
}

/// Like [`string_enum`] but with one of the values as the default, which is what
/// an optional filter argument needs.
pub fn enum_with_default(description: &str, values: &[&str], default: &str) -> Value {
    with_default(
        string_enum(description, values),
        Value::String(default.into()),
    )
}

/// A value that is either of the given JSON type or explicitly `null`.
///
/// Used for output fields that report "not available" instead of a guess.
pub fn nullable(type_name: &str) -> Value {
    json!({ "anyOf": [{ "type": type_name }, { "type": "null" }] })
}

pub fn string_or_null(description: &str) -> Value {
    describe(nullable("string")).with_description(description)
}

pub fn integer_or_null(description: &str) -> Value {
    describe(nullable("integer")).with_description(description)
}

/// Attaches a `maxItems` bound to an array property.
pub fn with_max_items(mut schema: Value, maximum: u64) -> Value {
    schema
        .as_object_mut()
        .expect("property builders always return objects")
        .insert("maxItems".into(), json!(maximum));
    schema
}

/// A non-negative count, for output fields.
pub fn count(description: &str) -> Value {
    describe(json!({ "type": "integer", "minimum": 0 })).with_description(description)
}

/// A true/false field, for output fields.
pub fn flag(description: &str) -> Value {
    describe(json!({ "type": "boolean" })).with_description(description)
}

/// An array of strings without a default, for describing output payloads.
pub fn string_list(description: &str) -> Value {
    describe(json!({ "type": "array", "items": { "type": "string" } }))
        .with_description(description)
}

/// Anything at all. Used for payloads copied out of Home Assistant whose shape
/// varies by integration.
pub fn any_json(description: &str) -> Value {
    json!({ "description": description })
}

/// An object whose known properties are described but which may carry others.
pub fn open_object(description: &str, properties: &[(&str, Value)], required: &[&str]) -> Value {
    let mut schema = describe(json!({ "type": "object" })).with_description(description);
    schema["properties"] = properties_to_object(properties);
    schema["additionalProperties"] = json!(true);
    if !required.is_empty() {
        schema["required"] = json!(required);
    }
    schema
}

/// Output properties for a paginated list: the caller's totals plus the trio.
pub fn paged(extra: &[(&'static str, Value)]) -> Vec<(&'static str, Value)> {
    let mut out = page_properties();
    out.extend_from_slice(extra);
    out
}

/// The matching `required` list for [`paged`].
pub fn paged_required(extra: &[&'static str]) -> Vec<&'static str> {
    let mut out: Vec<&'static str> = page_properties().iter().map(|(name, _)| *name).collect();
    out.extend_from_slice(extra);
    out
}

/// An array of [`open_object`] items.
pub fn open_object_array(
    description: &str,
    properties: &[(&str, Value)],
    required: &[&str],
) -> Value {
    describe(json!({ "type": "array", "items": open_object("", properties, required) }))
        .with_description(description)
}

/// The pagination fields every list-shaped result carries.
pub fn page_properties() -> Vec<(&'static str, Value)> {
    vec![
        (
            "matched",
            count("How many items matched the filters, before pagination."),
        ),
        (
            "returned",
            count("How many items this response contains, at most `limit`."),
        ),
        ("next_cursor", prop_next_cursor()),
    ]
}

// ---------------------------------------------------------------------------
// Arguments shared by several tools. Keeping them here stops descriptions and
// limits from drifting apart between tools.
// ---------------------------------------------------------------------------

/// An entity id filter that may be left empty to mean "no filter".
pub fn prop_optional_entity_id(description: &str) -> Value {
    with_default(string(description), json!(""))
}

pub fn prop_entity_id(description: &str) -> Value {
    string(description)
}

/// A required list of entity ids. Unlike [`string_array`] it carries no default:
/// a caller that names no entity has said nothing, which must be reported.
pub fn prop_entity_ids(description: &str) -> Value {
    describe(json!({
        "type": "array",
        "items": { "type": "string" },
        "minItems": 1,
        "uniqueItems": true,
    }))
    .with_description(description)
}

/// A substring filter that may be left empty to mean "match everything".
pub fn prop_query(description: &str) -> Value {
    with_default(string(description), json!(""))
}

pub fn prop_limit(maximum: i64, default: i64) -> Value {
    integer(
        "Maximum number of items to return in this response. Use next_cursor to continue.",
        1,
        maximum,
        default,
    )
}

pub fn prop_cursor() -> Value {
    with_default(
        string(
            "Opaque cursor from a previous response's next_cursor. Leave empty for the \
                first page. Keep every other argument identical between pages.",
        ),
        json!(""),
    )
}

/// A domain filter that may be left empty to mean "every domain".
pub fn prop_domain(description: &str) -> Value {
    with_default(string(description), json!(""))
}

/// `nextCursor`-style pagination field for output schemas.
pub fn prop_next_cursor() -> Value {
    describe(nullable("string")).with_description(
        "Opaque cursor for the next page, or null when the result set is exhausted.",
    )
}

fn without_default(schema: &Value) -> Value {
    let mut schema = schema.clone();
    if let Some(object) = schema.as_object_mut() {
        object.remove("default");
    }
    schema
}

fn with_default(mut schema: Value, default: Value) -> Value {
    schema
        .as_object_mut()
        .expect("property builders always return objects")
        .insert("default".into(), default);
    schema
}

fn properties_to_object(properties: &[(&str, Value)]) -> Value {
    let mut map = Map::new();
    for (name, schema) in properties {
        map.insert((*name).to_string(), schema.clone());
    }
    Value::Object(map)
}

struct SchemaBuilder(Value);

impl SchemaBuilder {
    fn with_description(mut self, description: &str) -> Value {
        self.0
            .as_object_mut()
            .expect("builder always wraps an object")
            .insert("description".into(), description.into());
        self.0
    }
}

fn describe(schema: Value) -> SchemaBuilder {
    SchemaBuilder(schema)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn input_schemas_are_closed_objects_with_described_properties() {
        let schema = input_schema(
            &[("name", string("The name")), ("limit", prop_limit(50, 10))],
            &["name"],
        );
        assert_eq!(schema["type"], "object");
        assert_eq!(schema["additionalProperties"], false);
        assert_eq!(schema["required"][0], "name");
        assert_eq!(schema["properties"]["name"]["description"], "The name");
        assert_eq!(schema["properties"]["limit"]["default"], 10);
    }

    #[test]
    fn optional_arguments_always_carry_a_default() {
        // The argument validator applies these defaults, so handlers may read
        // every property unconditionally. `mcp::tools` tests assert this holds
        // for the real tool set.
        let schema = input_schema(
            &[
                ("query", prop_query("Substring filter")),
                ("limit", prop_limit(50, 20)),
                ("flag", boolean("A flag", true)),
                ("sections", string_array("Sections", &[])),
                ("mode", string_enum("Mode", &["a", "b"])),
            ],
            &[],
        );
        assert!(schema.get("required").is_none());
        let properties = schema["properties"].as_object().unwrap();
        assert_eq!(properties["query"]["default"], "");
        assert_eq!(properties["sections"]["default"], json!([]));
        assert_eq!(properties["flag"]["default"], true);
        assert_eq!(
            properties["mode"].get("default"),
            None::<&Value>,
            "an enum without a default must be required"
        );
    }

    #[test]
    fn pass_through_payloads_accept_any_json() {
        assert_eq!(json_array("raw")["items"], json!(true));
        assert_eq!(json_object("raw")["type"], "object");
        assert_eq!(prop_next_cursor()["anyOf"][1]["type"], "null");
        assert_eq!(string_or_null("x")["anyOf"][1]["type"], "null");
        assert_eq!(integer_or_null("x")["anyOf"][0]["type"], "integer");
        assert_eq!(with_max_items(string_array("a", &[]), 42)["maxItems"], 42);
        assert_eq!(enum_with_default("m", &["a", "b"], "b")["default"], "b");
    }

    #[test]
    fn open_objects_describe_known_fields_but_stay_extendable() {
        let schema = open_object(
            "A state.",
            &[
                ("entity_id", string("The id")),
                ("unit", string_or_null("Unit")),
            ],
            &["entity_id"],
        );
        assert_eq!(schema["additionalProperties"], true);
        assert_eq!(schema["required"][0], "entity_id");
        assert_eq!(schema["properties"]["unit"]["anyOf"][1]["type"], "null");

        let array = open_object_array(
            "States.",
            &[("entity_id", string("The id"))],
            &["entity_id"],
        );
        assert_eq!(array["type"], "array");
        assert_eq!(array["items"]["additionalProperties"], true);
        assert_eq!(array["items"]["properties"]["entity_id"]["type"], "string");

        assert_eq!(
            any_json("varying")["type"],
            Value::Null,
            "no type constraint is declared"
        );
        assert_eq!(any_json("varying")["description"], "varying");
        assert_eq!(string_list("names")["items"]["type"], "string");
        assert!(string_list("names").get("default").is_none());

        let names: Vec<&str> = page_properties().iter().map(|(name, _)| *name).collect();
        assert_eq!(names, vec!["matched", "returned", "next_cursor"]);
    }

    #[test]
    fn output_schemas_do_not_advertise_defaults() {
        let schema = output_schema(
            &[
                ("limit", integer("Rows.", 1, 10, 5)),
                ("matched", count("Matches.")),
                ("flag", flag("A flag.")),
            ],
            &["matched"],
        );
        assert!(schema["properties"]["limit"].get("default").is_none());
        assert_eq!(
            schema["properties"]["limit"]["maximum"], 10,
            "bounds still describe the output"
        );
        assert_eq!(schema["properties"]["matched"]["minimum"], 0);
        assert_eq!(schema["properties"]["flag"]["type"], "boolean");
        assert_eq!(
            schema["additionalProperties"], false,
            "structuredContent must match exactly"
        );
    }

    #[test]
    fn optional_filters_default_to_empty_values() {
        assert_eq!(prop_query("q")["default"], "");
        assert_eq!(prop_domain("d")["default"], "");
        assert_eq!(prop_cursor()["default"], "");
        assert_eq!(prop_optional_entity_id("e")["default"], "");
        assert!(prop_entity_id("e").get("default").is_none());
        assert_eq!(prop_entity_ids("e")["minItems"], 1);
        assert!(prop_entity_ids("e").get("default").is_none());
    }
}
