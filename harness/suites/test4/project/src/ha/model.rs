//! Typed views over the JSON documents the Home Assistant REST API returns.
//!
//! Only the fields this server actually reasons about are modelled; anything
//! else lands in [`State::extra`] so a round trip back to JSON is lossless.

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

/// One entity's current state, as returned by `/api/states`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct State {
    pub entity_id: String,
    pub state: String,
    #[serde(default = "empty_object")]
    pub attributes: Value,
    #[serde(rename = "last_changed", default)]
    pub last_changed: String,
    #[serde(rename = "last_reported", default)]
    pub last_reported: String,
    #[serde(rename = "last_updated", default)]
    pub last_updated: String,
    /// Fields this server does not model (for example `context`) are carried
    /// through untouched so callers still see them.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

impl State {
    /// The integration domain, i.e. `light` in `light.living_room`.
    pub fn domain(&self) -> &str {
        match self.entity_id.find('.') {
            Some(index) => &self.entity_id[..index],
            None => self.entity_id.as_str(),
        }
    }

    /// The part after the dot, i.e. `living_room` in `light.living_room`.
    pub fn object_id(&self) -> &str {
        match self.entity_id.find('.') {
            Some(index) => &self.entity_id[index + 1..],
            None => "",
        }
    }

    pub fn friendly_name(&self) -> Option<&str> {
        self.string_attribute("friendly_name")
    }

    /// An attribute's value when it is a string.
    pub fn string_attribute(&self, key: &str) -> Option<&str> {
        self.attributes.get(key).and_then(Value::as_str)
    }

    /// True when Home Assistant marks the entity as hidden from the UI.
    pub fn is_hidden(&self) -> bool {
        matches!(self.attributes.get("hidden_by"), Some(value) if !value.is_null())
    }

    /// Compact projection used by the list-oriented tools: enough to identify
    /// and characterise an entity without shipping every attribute.
    pub fn summary(&self) -> Value {
        let mut out = Map::new();
        out.insert("entity_id".into(), self.entity_id.clone().into());
        out.insert("domain".into(), self.domain().into());
        out.insert("state".into(), self.state.clone().into());
        insert_if_some(&mut out, "friendly_name", self.friendly_name());
        for key in ["device_class", "unit_of_measurement", "icon"] {
            if let Some(value) = self.attributes.get(key) {
                if !value.is_null() {
                    out.insert(key.into(), value.clone());
                }
            }
        }
        out.insert("last_updated".into(), self.last_updated.clone().into());
        if self.is_hidden() {
            out.insert("hidden".into(), true.into());
        }
        Value::Object(out)
    }
}

/// One entry of `GET /api/events`: an event type and how many listeners it has.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EventTypeInfo {
    pub event: String,
    #[serde(rename = "listener_count", default)]
    pub listener_count: u64,
}

fn empty_object() -> Value {
    Value::Object(Map::new())
}

fn insert_if_some(map: &mut Map<String, Value>, key: &str, value: Option<&str>) {
    if let Some(value) = value {
        map.insert(key.into(), value.into());
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn sample() -> State {
        serde_json::from_value(json!({
            "entity_id": "light.living_room_strip",
            "state": "on",
            "attributes": {
                "friendly_name": "Living Room Strip",
                "brightness": 180,
                "color_temp_kelvin": 3500,
                "supported_features": 63,
                "hidden_by": null
            },
            "last_changed": "2026-09-22T12:25:55.216357+00:00",
            "last_reported": "2026-09-26T05:06:13.499017+00:00",
            "last_updated": "2026-09-26T05:06:13.499017+00:00",
            "context": { "id": "01ABC", "parent_id": null, "user_id": null }
        }))
        .expect("sample should deserialize")
    }

    #[test]
    fn splits_domain_and_object_id() {
        let state = sample();
        assert_eq!(state.domain(), "light");
        assert_eq!(state.object_id(), "living_room_strip");

        let odd = State {
            entity_id: "novalue".into(),
            state: "unknown".into(),
            attributes: empty_object(),
            last_changed: String::new(),
            last_reported: String::new(),
            last_updated: String::new(),
            extra: Map::new(),
        };
        assert_eq!(odd.domain(), "novalue");
        assert_eq!(odd.object_id(), "");
    }

    #[test]
    fn summary_keeps_identifying_attributes_and_drops_the_rest() {
        let summary = sample().summary();
        assert_eq!(summary["entity_id"], "light.living_room_strip");
        assert_eq!(summary["domain"], "light");
        assert_eq!(summary["state"], "on");
        assert_eq!(summary["friendly_name"], "Living Room Strip");
        assert!(
            summary.get("brightness").is_none(),
            "bulk attributes must not leak into summaries"
        );
        assert!(
            summary.get("hidden").is_none(),
            "a null hidden_by is not hidden"
        );
    }

    #[test]
    fn hidden_entities_are_flagged() {
        let mut state = sample();
        state.attributes["hidden_by"] = json!("integration");
        assert!(state.is_hidden());
        assert_eq!(state.summary()["hidden"], true);
    }

    #[test]
    fn unmodelled_fields_survive_a_round_trip() {
        let state = sample();
        let restored: State =
            serde_json::from_value(serde_json::to_value(&state).unwrap()).expect("round trip");
        assert_eq!(state, restored);
        assert!(state.extra.contains_key("context"));
    }

    #[test]
    fn missing_attributes_default_to_an_empty_object() {
        let state: State =
            serde_json::from_value(json!({ "entity_id": "sun.sun", "state": "above_horizon" }))
                .expect("minimal state");
        assert_eq!(state.attributes, empty_object());
        assert_eq!(state.friendly_name(), None);
        assert_eq!(state.summary()["domain"], "sun");
    }

    #[test]
    fn event_types_deserialize_with_listener_counts() {
        let types: Vec<EventTypeInfo> = serde_json::from_value(json!([
            { "event": "*", "listener_count": 1 },
            { "event": "call_service", "listener_count": 7 }
        ]))
        .expect("event types");
        assert_eq!(types[1].event, "call_service");
        assert_eq!(types[1].listener_count, 7);
    }
}
