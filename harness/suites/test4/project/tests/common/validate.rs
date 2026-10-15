//! A deliberately small JSON Schema checker, sufficient for the subset of the
//! dialect the server emits: types, `anyOf`, required properties, closed root
//! objects, array constraints and numeric bounds.
//!
//! A full implementation is not worth a dependency; what matters is that every
//! `structuredContent` really matches the `outputSchema` that was advertised.

#![allow(dead_code)]

use serde_json::Value;

/// Returns a human-readable problem for every rule the value breaks.
pub fn problems(schema: &Value, value: &Value) -> Vec<String> {
    let mut found = Vec::new();
    check(schema, value, "$", &mut found);
    found
}

/// `problems` but as one message, for `assert!`.
pub fn describe(schema: &Value, value: &Value) -> String {
    let found = problems(schema, value);
    if found.is_empty() {
        return String::new();
    }
    found.join("\n")
}

fn check(schema: &Value, value: &Value, path: &str, found: &mut Vec<String>) {
    if !schema.is_object() {
        return; // an open schema accepts anything
    }

    if let Some(branches) = schema.get("anyOf").and_then(Value::as_array) {
        // Any branch may carry the rest of the constraints, so a candidate passes
        // when at least one branch accepts it outright.
        let accepted = branches
            .iter()
            .any(|branch| problems(branch, value).is_empty());
        if !accepted {
            found.push(format!(
                "{path} matches none of the {} accepted shapes; got {}",
                branches.len(),
                shape(value)
            ));
        }
        return;
    }

    if let Some(types) = schema.get("type") {
        if !type_matches(types, value) {
            found.push(format!(
                "{} must be {}, got {}",
                path,
                expected(types),
                shape(value)
            ));
            return; // the deeper rules are meaningless on the wrong type
        }
    }

    if let Some(accepted) = schema.get("enum").and_then(Value::as_array) {
        if !accepted.contains(value) {
            found.push(format!("{path} must be one of {accepted:?}, got {value}"));
        }
    }

    match value {
        Value::Object(object) => {
            if let Some(required) = schema.get("required").and_then(Value::as_array) {
                for key in required.iter().filter_map(Value::as_str) {
                    if !object.contains_key(key) {
                        found.push(format!("{path} is missing the required property \"{key}\""));
                    }
                }
            }
            let properties = schema.get("properties");
            if schema.get("additionalProperties") == Some(&Value::Bool(false)) {
                let known = properties.and_then(Value::as_object);
                for key in object.keys() {
                    let declared = known.is_some_and(|known| known.contains_key(key));
                    if !declared {
                        found.push(format!("{path}.{key} is not declared by the outputSchema"));
                    }
                }
            }
            if let Some(properties) = properties.and_then(Value::as_object) {
                for (key, sub) in properties {
                    if let Some(child) = object.get(key) {
                        check(sub, child, &format!("{path}.{key}"), found);
                    }
                }
            }
        }
        Value::Array(items) => {
            if let Some(min) = schema.get("minItems").and_then(Value::as_u64) {
                if (items.len() as u64) < min {
                    found.push(format!(
                        "{path} must hold at least {min} items, holds {}",
                        items.len()
                    ));
                }
            }
            if let Some(max) = schema.get("maxItems").and_then(Value::as_u64) {
                if (items.len() as u64) > max {
                    found.push(format!(
                        "{path} holds {} items, over the limit of {max}",
                        items.len()
                    ));
                }
            }
            if schema.get("uniqueItems") == Some(&Value::Bool(true)) {
                let mut seen: Vec<&Value> = Vec::new();
                for item in items {
                    if seen.contains(&item) {
                        found.push(format!("{path} must not repeat {item}"));
                        break;
                    }
                    seen.push(item);
                }
            }
            if let Some(sub) = schema.get("items") {
                for (index, item) in items.iter().enumerate() {
                    check(sub, item, &format!("{path}[{index}]"), found);
                }
            }
        }
        Value::Number(number) => {
            if let Some(min) = schema.get("minimum").and_then(Value::as_f64) {
                if number.as_f64().unwrap_or(f64::MIN) < min {
                    found.push(format!("{path} must be >= {min}, got {number}"));
                }
            }
            if let Some(max) = schema.get("maximum").and_then(Value::as_f64) {
                if number.as_f64().unwrap_or(f64::MAX) > max {
                    found.push(format!("{path} must be <= {max}, got {number}"));
                }
            }
        }
        _ => {}
    }
}

fn type_matches(types: &Value, value: &Value) -> bool {
    match types {
        Value::String(kind) => is_a(kind, value),
        Value::Array(kinds) => kinds
            .iter()
            .filter_map(Value::as_str)
            .any(|kind| is_a(kind, value)),
        _ => true,
    }
}

fn is_a(kind: &str, value: &Value) -> bool {
    match kind {
        "object" => value.is_object(),
        "array" => value.is_array(),
        "string" => value.is_string(),
        "boolean" => value.is_boolean(),
        "null" => value.is_null(),
        "integer" => value.is_i64() || value.is_u64(),
        "number" => value.is_number(),
        _ => true,
    }
}

fn expected(types: &Value) -> String {
    match types {
        Value::String(kind) => kind.to_string(),
        Value::Array(kinds) => kinds
            .iter()
            .filter_map(Value::as_str)
            .collect::<Vec<_>>()
            .join(" or "),
        _ => "something the schema describes".to_string(),
    }
}

fn shape(value: &Value) -> String {
    match value {
        Value::Object(object) => format!("an object with {} keys", object.len()),
        Value::Array(items) => format!("an array of {} items", items.len()),
        Value::String(_) => "a string".to_string(),
        Value::Number(_) => "a number".to_string(),
        Value::Bool(_) => "a boolean".to_string(),
        Value::Null => "null".to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn reports_missing_and_extra_keys_on_a_closed_object() {
        let schema = json!({
            "type": "object",
            "required": ["a"],
            "properties": {"a": {"type": "string"}},
            "additionalProperties": false,
        });
        assert!(problems(&schema, &json!({"a": "x"})).is_empty());
        assert!(problems(&schema, &json!({}))[0].contains("required"));
        assert_eq!(problems(&schema, &json!({"a": "x", "b": 1})).len(), 1);
        assert!(describe(&schema, &json!({"a": 3})).contains("must be string"));
    }

    #[test]
    fn follows_nested_arrays_and_any_of() {
        let schema = json!({
            "type": "object",
            "properties": {
                "items": {"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "null"}]}, "maxItems": 2},
                "count": {"type": "integer", "minimum": 0},
            },
            "required": ["items", "count"],
        });
        assert!(problems(&schema, &json!({"items": ["a", null], "count": 0})).is_empty());
        assert_eq!(
            problems(&schema, &json!({"items": [1], "count": 0})).len(),
            1
        );
        assert_eq!(
            problems(&schema, &json!({"items": ["a", "b", "c"], "count": 0})).len(),
            1
        );
        assert_eq!(
            problems(&schema, &json!({"items": [], "count": -1})).len(),
            1
        );
    }
}
