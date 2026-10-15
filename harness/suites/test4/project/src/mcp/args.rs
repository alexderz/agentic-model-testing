//! Validation of `tools/call` arguments against a tool's `inputSchema`.
//!
//! The schema written for `tools/list` is the only description of the rules:
//! this module enforces the declared type, range, enum membership and defaults,
//! and reports problems as prose a model can act on. All problems found in one
//! pass are returned together so the caller can fix them in one retry.

use serde_json::{Map, Value};

use crate::util::json_type;

/// Validated arguments, with every declared default already applied.
#[derive(Debug, Clone, Default)]
pub struct Args(Map<String, Value>);

impl Args {
    pub fn string(&self, key: &str) -> &str {
        match self.0.get(key) {
            Some(Value::String(text)) => text.as_str(),
            _ => "",
        }
    }

    pub fn integer(&self, key: &str) -> i64 {
        match self.0.get(key) {
            Some(Value::Number(number)) => number.as_i64().unwrap_or(0),
            _ => 0,
        }
    }

    pub fn boolean(&self, key: &str) -> bool {
        self.0.get(key).and_then(Value::as_bool).unwrap_or(false)
    }

    pub fn strings(&self, key: &str) -> Vec<String> {
        match self.0.get(key) {
            Some(Value::Array(items)) => items
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_string)
                .collect(),
            _ => Vec::new(),
        }
    }

    /// True when the argument holds a non-empty string, i.e. a filter is active.
    pub fn has_text(&self, key: &str) -> bool {
        !self.string(key).trim().is_empty()
    }
}

/// Checks `arguments` against `schema` and returns usable [`Args`].
///
/// The error vector is never empty; the caller renders it into a tool result
/// with `isError: true`, which is how the spec wants input validation failures.
pub fn validate(schema: &Value, arguments: Option<&Value>) -> Result<Args, Vec<String>> {
    let properties = match schema.get("properties").and_then(Value::as_object) {
        Some(properties) => properties,
        None => return Ok(Args::default()),
    };
    let required: Vec<&str> = schema
        .get("required")
        .and_then(Value::as_array)
        .map(|items| items.iter().filter_map(Value::as_str).collect())
        .unwrap_or_default();
    let closed = schema.get("additionalProperties") == Some(&Value::Bool(false));

    let provided = match arguments {
        None | Some(Value::Null) => Map::new(),
        Some(Value::Object(map)) => map.clone(),
        Some(other) => {
            return Err(vec![format!(
            "\"arguments\" must be a JSON object, got {} (for a tool with no parameters send {{}})",
            json_type(other)
        )])
        }
    };

    let mut problems: Vec<String> = Vec::new();
    let mut values = Map::new();

    for name in provided.keys() {
        if !properties.contains_key(name) && closed {
            problems.push(match closest_property(name, properties) {
                Some(suggestion) => {
                    format!("unknown argument \"{name}\"; did you mean \"{suggestion}\"?")
                }
                None => format!(
                    "unknown argument \"{name}\"; this tool accepts {}",
                    quote_all(properties.keys())
                ),
            });
        }
    }

    for (name, property) in properties {
        let given = provided.get(name).filter(|value| !value.is_null());
        match given {
            None => {
                if let Some(default) = property.get("default") {
                    values.insert(name.clone(), default.clone());
                } else if required.contains(&name.as_str()) {
                    problems.push(format!(
                        "missing required argument \"{name}\" ({})",
                        first_sentence(property.get("description").and_then(Value::as_str))
                    ));
                }
            }
            Some(value) => {
                if let Some(problem) =
                    check(name, property, value, required.contains(&name.as_str()))
                {
                    problems.push(problem);
                } else {
                    values.insert(name.clone(), value.clone());
                }
            }
        }
    }

    if problems.is_empty() {
        Ok(Args(values))
    } else {
        Err(problems)
    }
}

/// Returns a problem description for one argument, or `None` when acceptable.
fn check(name: &str, property: &Value, value: &Value, is_required: bool) -> Option<String> {
    let label = format!("argument \"{name}\"");
    let expected = property.get("type").and_then(Value::as_str);
    match expected {
        Some("string") => {
            let Some(text) = value.as_str() else {
                return Some(format!("{label} must be a string, got {}", describe(value)));
            };
            if let Some(allowed) = property.get("enum").and_then(Value::as_array) {
                let options: Vec<&str> = allowed.iter().filter_map(Value::as_str).collect();
                if !options.contains(&text) {
                    return Some(format!(
                        "{label} must be one of {}; got \"{text}\"",
                        options
                            .iter()
                            .map(|option| format!("\"{option}\""))
                            .collect::<Vec<_>>()
                            .join(", ")
                    ));
                }
            }
            if is_required && text.trim().is_empty() {
                return Some(format!("{label} must not be empty"));
            }
            None
        }
        Some("integer") => {
            let Some(number) = value.as_i64() else {
                return Some(format!(
                    "{label} must be a whole number, got {}",
                    describe(value)
                ));
            };
            let min = property.get("minimum").and_then(Value::as_i64);
            let max = property.get("maximum").and_then(Value::as_i64);
            match (min, max) {
                (Some(min), Some(max)) if number < min || number > max => Some(format!(
                    "{label} must be between {min} and {max}, got {number}"
                )),
                (Some(min), _) if number < min => {
                    Some(format!("{label} must be at least {min}, got {number}"))
                }
                (_, Some(max)) if number > max => {
                    Some(format!("{label} must be at most {max}, got {number}"))
                }
                _ => None,
            }
        }
        Some("boolean") => {
            if value.is_boolean() {
                None
            } else {
                Some(format!(
                    "{label} must be true or false, got {}",
                    describe(value)
                ))
            }
        }
        Some("array") => {
            let Some(items) = value.as_array() else {
                return Some(format!("{label} must be an array, got {}", describe(value)));
            };
            if let Some(min_items) = property.get("minItems").and_then(Value::as_u64) {
                if (items.len() as u64) < min_items {
                    return Some(format!(
                        "{label} needs at least {min_items} entr{}, got {}",
                        if min_items == 1 { "y" } else { "ies" },
                        items.len()
                    ));
                }
            }
            if let Some(max_items) = property.get("maxItems").and_then(Value::as_u64) {
                if items.len() as u64 > max_items {
                    return Some(format!(
                        "{label} accepts at most {max_items} entries, got {} (split the request into several calls)",
                        items.len()
                    ));
                }
            }
            let item_type = property.pointer("/items/type").and_then(Value::as_str);
            if item_type == Some("string") {
                if let Some(bad) = items.iter().find(|item| !item.is_string()) {
                    return Some(format!(
                        "{label} must contain only strings, {} is not a string",
                        describe(bad)
                    ));
                }
            }
            None
        }
        // No declared type: the schema imposes nothing on this argument.
        None => None,
        Some(other) => Some(format!(
            "internal error: {label} declares unknown type \"{other}\""
        )),
    }
}

/// Suggests a property name for a likely typo.
fn closest_property<'a>(given: &str, properties: &'a Map<String, Value>) -> Option<&'a str> {
    let needle = given.to_ascii_lowercase();
    let mut best: Option<(usize, &'a str)> = None;
    for name in properties.keys() {
        let candidate = name.to_ascii_lowercase();
        let score = if candidate == needle {
            0
        } else if needle.contains(&candidate) || candidate.contains(&needle) {
            1
        } else if common_prefix_len(&needle, &candidate) >= 3 {
            2
        } else {
            continue;
        };
        if best.is_none_or(|(best_score, _)| score < best_score) {
            best = Some((score, name.as_str()));
        }
    }
    best.map(|(_, name)| name)
}

fn common_prefix_len(a: &str, b: &str) -> usize {
    a.chars().zip(b.chars()).take_while(|(x, y)| x == y).count()
}

fn quote_all<'a, I: Iterator<Item = &'a String>>(names: I) -> String {
    let joined = names
        .map(|name| format!("\"{name}\""))
        .collect::<Vec<_>>()
        .join(", ");
    if joined.is_empty() {
        "no arguments at all (send {})".to_string()
    } else {
        format!("only {joined}")
    }
}

fn describe(value: &Value) -> String {
    match value {
        Value::String(text) => format!("the string \"{text}\""),
        other => json_type(other).to_string(),
    }
}

/// The first real sentence of a description, so a missing argument can be
/// explained without repeating every caveat.
fn sentence_end(text: &str) -> Option<usize> {
    let mut search = 0;
    while let Some(offset) = text[search..].find(". ") {
        let index = search + offset;
        let before = text[..index].to_ascii_lowercase();
        let abbreviation = ["e.g", "i.e", "etc", "eg", "vs", "approx"]
            .iter()
            .any(|abbreviation| before.ends_with(abbreviation));
        if !abbreviation {
            return Some(index + 1);
        }
        search = index + 2;
    }
    None
}

fn first_sentence(description: Option<&str>) -> String {
    let text = description.unwrap_or("see the tool schema").trim();
    let end = sentence_end(text).unwrap_or(text.len());
    let sentence = text[..end].trim_end_matches('.');
    if sentence.chars().count() > 160 {
        format!("{}…", crate::util::truncate_chars(sentence, 160).0)
    } else {
        sentence.to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mcp::schema::{
        boolean, input_schema, integer, prop_cursor, prop_entity_ids, prop_query, string,
        string_array, string_enum, with_max_items,
    };
    use serde_json::json;

    fn schema() -> Value {
        input_schema(
            &[
                (
                    "entity_id",
                    string("The entity id to read, e.g. \"light.living_room\"."),
                ),
                ("limit", integer("How many rows.", 1, 200, 50)),
                ("include_attributes", boolean("Include attributes.", false)),
                ("sections", string_array("Top-level config keys.", &[])),
                ("mode", string_enum("Sort mode.", &["entity_id", "state"])),
                ("cursor", prop_cursor()),
                ("query", prop_query("Substring filter.")),
            ],
            &["entity_id", "mode"],
        )
    }

    fn ok(arguments: Value) -> Args {
        validate(&schema(), Some(&arguments))
            .unwrap_or_else(|problems| panic!("rejected: {problems:?}"))
    }

    fn problems(arguments: Value) -> Vec<String> {
        validate(&schema(), Some(&arguments)).expect_err("should be rejected")
    }

    #[test]
    fn supplied_values_are_read_back_with_their_types() {
        let args = ok(json!({
            "entity_id": "light.kitchen",
            "mode": "state",
            "limit": 7,
            "include_attributes": true,
            "sections": ["unit_system"],
            "query": "kitchen"
        }));
        assert_eq!(args.string("entity_id"), "light.kitchen");
        assert_eq!(args.integer("limit"), 7);
        assert!(args.boolean("include_attributes"));
        assert_eq!(args.strings("sections"), vec!["unit_system".to_string()]);
        assert!(args.has_text("query"));
        assert!(
            !args.has_text("cursor"),
            "an omitted defaulted cursor is empty"
        );
    }

    #[test]
    fn defaults_are_applied_for_absent_optional_arguments() {
        let args = ok(json!({ "entity_id": "sun.sun", "mode": "entity_id" }));
        assert_eq!(args.integer("limit"), 50);
        assert!(!args.boolean("include_attributes"));
        assert!(args.strings("sections").is_empty());
        assert_eq!(args.string("cursor"), "");
        assert!(!args.has_text("query"));
    }

    #[test]
    fn missing_required_arguments_are_named_with_their_description() {
        let problems = problems(json!({ "limit": 3 }));
        assert_eq!(
            problems.len(),
            2,
            "both entity_id and mode are required: {problems:?}"
        );
        assert!(problems[0].starts_with("missing required argument \"entity_id\""));
        assert!(problems[0].contains("light.living_room"));
        assert!(problems.iter().any(|p| p.contains("\"mode\"")));
    }

    #[test]
    fn empty_values_are_rejected_only_for_required_arguments() {
        let problems = problems(json!({ "entity_id": "  ", "mode": "state" }));
        assert_eq!(problems, vec!["argument \"entity_id\" must not be empty"]);
        assert!(validate(
            &schema(),
            Some(&json!({ "entity_id": "a", "mode": "state", "query": "" }))
        )
        .is_ok());
    }

    #[test]
    fn wrong_types_and_out_of_range_numbers_are_reported_all_at_once() {
        let problems = problems(json!({
            "entity_id": 12,
            "mode": "state",
            "limit": "20",
            "include_attributes": "yes",
            "sections": "unit_system",
            "query": ["a"]
        }));
        assert_eq!(problems.len(), 5, "{problems:?}");
        assert!(problems
            .iter()
            .any(|p| p.contains("\"entity_id\" must be a string, got a number")));
        assert!(problems
            .iter()
            .any(|p| p.contains("\"limit\" must be a whole number, got the string \"20\"")));
        assert!(problems
            .iter()
            .any(|p| p.contains("\"include_attributes\" must be true or false")));
        assert!(problems
            .iter()
            .any(|p| p.contains("\"sections\" must be an array")));
        assert!(problems
            .iter()
            .any(|p| p.contains("\"query\" must be a string")));
    }

    #[test]
    fn integer_bounds_come_from_the_schema() {
        let first = problems(json!({ "entity_id": "a", "mode": "state", "limit": 500 }));
        assert_eq!(
            first,
            vec!["argument \"limit\" must be between 1 and 200, got 500"]
        );
        let second = problems(json!({ "entity_id": "a", "mode": "state", "limit": 0 }));
        assert_eq!(
            second,
            vec!["argument \"limit\" must be between 1 and 200, got 0"]
        );
        assert_eq!(second.len(), 1, "one problem per argument");
    }

    #[test]
    fn enum_membership_is_enumerated_in_the_message() {
        let problems = problems(json!({ "entity_id": "a", "mode": "alphabetical" }));
        assert_eq!(
            problems,
            vec![r#"argument "mode" must be one of "entity_id", "state"; got "alphabetical""#]
        );
    }

    #[test]
    fn array_items_must_all_match_the_declared_item_type() {
        let problems =
            problems(json!({ "entity_id": "a", "mode": "state", "sections": ["ok", 42] }));
        assert_eq!(
            problems,
            vec!["argument \"sections\" must contain only strings, a number is not a string"]
        );
    }

    #[test]
    fn array_length_is_bounded_when_the_schema_says_so() {
        let bounded = input_schema(&[("ids", with_max_items(string_array("Ids", &[]), 2))], &[]);
        let problems =
            validate(&bounded, Some(&json!({ "ids": ["a", "b", "c"] }))).expect_err("too long");
        assert_eq!(
            problems,
            vec!["argument \"ids\" accepts at most 2 entries, got 3 (split the request into several calls)"]
        );
        assert!(validate(&bounded, Some(&json!({ "ids": ["a", "b"] }))).is_ok());

        let floored = input_schema(&[("ids", prop_entity_ids("Ids"))], &["ids"]);
        let problems = validate(&floored, Some(&json!({ "ids": [] }))).expect_err("empty list");
        assert_eq!(
            problems,
            vec!["argument \"ids\" needs at least 1 entry, got 0"]
        );
    }

    #[test]
    fn typos_get_a_suggestion_and_unknown_names_get_a_list() {
        let typo = problems(json!({ "entity_id": "a", "mode": "state", "entitiy_id": "b" }));
        assert_eq!(
            typo,
            vec!["unknown argument \"entitiy_id\"; did you mean \"entity_id\"?"]
        );

        let listed = problems(json!({ "entity_id": "a", "mode": "state", "zzz": 1 }));
        assert!(listed[0].starts_with("unknown argument \"zzz\"; this tool accepts only "));
        assert!(listed[0].contains("\"limit\""));
    }

    #[test]
    fn non_object_arguments_and_absent_arguments_are_handled() {
        let problems = validate(&schema(), Some(&json!("light.kitchen"))).expect_err("must fail");
        assert!(problems[0].contains("must be a JSON object"));

        let empty = validate(&schema(), None).expect_err("required arguments are missing");
        assert!(empty[0].contains("entity_id"));

        let permissive = validate(&json!({}), Some(&json!({ "anything": 1 })))
            .expect("no schema means no rules");
        assert_eq!(permissive.string("anything"), "");
    }

    #[test]
    fn null_optional_values_fall_back_to_their_default() {
        let args = ok(json!({ "entity_id": "a", "mode": "state", "query": null, "limit": null }));
        assert_eq!(args.string("query"), "");
        assert_eq!(args.integer("limit"), 50);
    }
}
