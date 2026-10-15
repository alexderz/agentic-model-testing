//! Every tool, driven through the real binary against a fake Home Assistant, and
//! checked against the `outputSchema` each tool advertises.

mod common;

use std::collections::BTreeMap;
use std::time::Duration;

use common::{all_tools, validate, FakeHa, Message, TOKEN};
use serde_json::{json, Value};

/// Arguments for each tool that needs some, so one loop can exercise all twelve.
fn arguments_for(name: &str) -> Value {
    match name {
        "get_entity" => json!({"entity_id": "light.living_room"}),
        "get_entities" => {
            json!({"entity_ids": ["light.living_room", "sensor.outside_temperature"]})
        }
        "get_service" => json!({"domain": "light", "service": "turn_on"}),
        _ => json!({}),
    }
}

fn call(client: &common::Client, name: &str, arguments: Value) -> Value {
    client.request("tools/call", json!({"name": name, "arguments": arguments}))
}

#[test]
fn every_tool_returns_content_that_matches_its_declared_output_schema() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);

    let schemas: BTreeMap<String, Value> = all_tools(&client)
        .into_iter()
        .map(|tool| {
            (
                tool["name"].as_str().expect("a tool name").to_string(),
                tool["outputSchema"].clone(),
            )
        })
        .collect();
    assert_eq!(
        schemas.len(),
        12,
        "the suite must cover every advertised tool"
    );

    for (name, schema) in &schemas {
        let message = call(&client, name, arguments_for(name));
        let structured = message.expect_structured(&format!("{name} against the fake instance"));
        let problems = validate::problems(schema, &structured);
        assert!(
            problems.is_empty(),
            "{name} returned content its outputSchema rejects:\n{}",
            validate::describe(schema, &structured)
        );
        assert_eq!(message["result"]["resultType"], "complete");
    }
}

#[test]
fn get_instance_info_describes_and_counts_the_instance() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);

    let info = call(&client, "get_instance_info", json!({})).expect_structured("get_instance_info");
    assert_eq!(info["api_running"], true);
    assert_eq!(info["api_message"], "API running.");
    assert_eq!(info["instance"]["location_name"], "Home");
    assert_eq!(info["instance"]["version"], "2026.9.1");
    assert_eq!(info["instance"]["unit_system"]["temperature"], "°C");
    // Nothing was invented: only the documented summary keys are present.
    assert!(
        info["instance"].get("uuid").is_none(),
        "internal identifiers stay out"
    );
    assert!(info["instance"].get("config_dir").is_none());
    assert_eq!(info["counts"]["components"], 8);
    assert_eq!(info["counts"]["entities"], 6);
    assert_eq!(info["counts"]["entity_domains"], 4);
    assert_eq!(info["counts"]["service_domains"], 3);
    assert_eq!(info["counts"]["services"], 5);
    assert_eq!(info["counts"]["event_types"], 5);
    assert_eq!(info["unavailable"], json!([]));
}

#[test]
fn get_config_projects_sections_and_says_which_ones_are_missing() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);

    let whole = call(&client, "get_config", json!({})).expect_structured("get_config");
    assert_eq!(whole["total_keys"], 20);
    assert_eq!(whole["components_count"], 8);
    assert_eq!(whole["components_included"], true);
    assert_eq!(whole["missing_sections"], json!([]));
    let keys = whole["returned_keys"].as_array().unwrap();
    assert_eq!(keys.len(), 20);
    assert_eq!(
        keys.first().unwrap(),
        "components",
        "the key list is sorted"
    );

    let slim = call(&client, "get_config", json!({"include_components": false}))
        .expect_structured("get_config without components");
    assert_eq!(
        slim["components_included"], false,
        "the long component list can be dropped"
    );
    assert_eq!(
        slim["components_count"], 8,
        "the count survives, so the caller knows what was left out"
    );
    assert!(slim["config"].get("components").is_none());
    assert_eq!(slim["returned_keys"].as_array().unwrap().len(), 19);

    let narrowed = call(
        &client,
        "get_config",
        json!({"sections": ["unit_system", "time_zone", "unit_systems"]}),
    )
    .expect_structured("get_config with sections");
    assert_eq!(narrowed["config"].as_object().unwrap().len(), 2);
    assert_eq!(narrowed["config"]["time_zone"], "Europe/Amsterdam");
    assert_eq!(narrowed["missing_sections"], json!(["unit_systems"]));
    assert_eq!(
        narrowed["total_keys"], 20,
        "the instance still has everything; only the view is narrower"
    );

    assert_eq!(whole["config"]["components"].as_array().unwrap().len(), 8);
}

#[test]
fn list_integrations_groups_components_by_their_first_segment() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);

    let all = call(&client, "list_integrations", json!({})).expect_structured("list_integrations");
    assert_eq!(all["total_components"], 8);
    assert_eq!(all["total_domains"], 8);
    assert_eq!(all["matched"], 8);
    let domains: Vec<&str> = all["domains"]
        .as_array()
        .unwrap()
        .iter()
        .map(|row| row["domain"].as_str().unwrap())
        .collect();
    assert!(
        domains.contains(&"mqtt"),
        "mqtt.light must group under mqtt: {domains:?}"
    );
    let mqtt = all["domains"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["domain"] == "mqtt")
        .expect("mqtt");
    assert_eq!(mqtt["components"], json!(["mqtt.light"]));
    assert_eq!(mqtt["component_count"], 1);

    let filtered = call(&client, "list_integrations", json!({"query": "mqtt"}))
        .expect_structured("list_integrations filtered");
    assert_eq!(filtered["matched"], 1);
    assert_eq!(filtered["domains"].as_array().unwrap().len(), 1);
}

#[test]
fn list_domains_reports_sizes_examples_and_common_states() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);

    let rows = call(&client, "list_domains", json!({})).expect_structured("list_domains");
    assert_eq!(rows["total_entities"], 6);
    assert_eq!(rows["total_domains"], 4);
    let first = &rows["domains"].as_array().unwrap()[0];
    assert_eq!(
        first["domain"], "light",
        "the biggest domain leads, ties break alphabetically"
    );
    assert_eq!(first["entity_count"], 2);
    assert_eq!(
        first["example_entities"],
        json!(["light.bedroom", "light.living_room"])
    );
    assert_eq!(first["common_states"][0]["count"], 1);

    let sorted = call(&client, "list_domains", json!({"sort_by": "domain"}))
        .expect_structured("list_domains sorted");
    let names: Vec<&str> = sorted["domains"]
        .as_array()
        .unwrap()
        .iter()
        .map(|row| row["domain"].as_str().unwrap())
        .collect();
    assert_eq!(names, vec!["climate", "light", "sensor", "switch"]);

    let limited = call(&client, "list_domains", json!({"limit": 2}))
        .expect_structured("list_domains limited");
    assert_eq!(limited["returned"], 2);
    assert_eq!(limited["matched"], 4);
    assert!(limited["next_cursor"].is_string());
}

#[test]
fn list_entities_filters_sorts_and_hides_hidden_entities() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);

    let default_page = call(&client, "list_entities", json!({})).expect_structured("list_entities");
    assert_eq!(default_page["total_entities"], 6);
    assert_eq!(
        default_page["matched"], 6,
        "nothing is silently withheld by default"
    );
    assert_eq!(
        default_page["entities"][0]["entity_id"], "climate.thermostat",
        "the default order is by entity id"
    );
    let battery = default_page["entities"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["entity_id"] == "sensor.battery_unknown")
        .expect("the hidden entity");
    assert_eq!(
        battery["hidden"], true,
        "hidden entities are still listed, but flagged"
    );
    assert!(default_page["entities"][0]["device_class"].is_null());
    let temperature = default_page["entities"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["entity_id"] == "sensor.outside_temperature")
        .expect("the sensor");
    assert_eq!(temperature["device_class"], "temperature");
    assert_eq!(temperature["unit_of_measurement"], "°C");
    assert_eq!(temperature["friendly_name"], "Outside temperature");

    let visible = call(&client, "list_entities", json!({"only_available": true}))
        .expect_structured("list_entities narrowed");
    assert_eq!(visible["matched"], 5);
    let ids: Vec<&str> = visible["entities"]
        .as_array()
        .unwrap()
        .iter()
        .map(|row| row["entity_id"].as_str().unwrap())
        .collect();
    assert!(!ids.contains(&"sensor.battery_unknown"));

    let lights = call(&client, "list_entities", json!({"domain": "light"}))
        .expect_structured("list_entities domain");
    assert_eq!(lights["matched"], 2);
    let turned_off = call(&client, "list_entities", json!({"state": "off"}))
        .expect_structured("list_entities state");
    assert_eq!(turned_off["matched"], 2);
    let searched = call(&client, "list_entities", json!({"query": "coffee"}))
        .expect_structured("list_entities query");
    assert_eq!(searched["matched"], 1);
    assert_eq!(
        searched["entities"][0]["entity_id"],
        "switch.coffee_machine"
    );

    let attributed = call(
        &client,
        "list_entities",
        json!({"domain": "light", "include_attributes": true}),
    )
    .expect_structured("list_entities with attributes");
    assert!(attributed["entities"][0]["attributes"]["supported_color_modes"].is_array());

    let second_page = call(&client, "list_entities", json!({"limit": 2}))
        .expect_structured("list_entities page one");
    assert_eq!(second_page["returned"], 2);
    let cursor = second_page["next_cursor"].as_str().unwrap().to_string();
    let continuation = call(
        &client,
        "list_entities",
        json!({"limit": 2, "cursor": &cursor}),
    )
    .expect_structured("list_entities page two");
    assert_eq!(continuation["returned"], 2);
    let first_ids: Vec<String> = second_page["entities"]
        .as_array()
        .unwrap()
        .iter()
        .map(|row| row["entity_id"].as_str().unwrap().to_string())
        .collect();
    let next_ids: Vec<String> = continuation["entities"]
        .as_array()
        .unwrap()
        .iter()
        .map(|row| row["entity_id"].as_str().unwrap().to_string())
        .collect();
    assert!(
        first_ids.iter().all(|id| !next_ids.contains(id)),
        "pages must not overlap: {first_ids:?} vs {next_ids:?}"
    );
}

#[test]
fn get_entity_returns_everything_about_one_entity() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);

    let entity = call(
        &client,
        "get_entity",
        json!({"entity_id": "light.living_room"}),
    )
    .expect_structured("get_entity");
    assert_eq!(entity["entity_id"], "light.living_room");
    assert_eq!(entity["domain"], "light");
    assert_eq!(entity["object_id"], "living_room");
    assert_eq!(entity["state"], "on");
    assert_eq!(entity["friendly_name"], "Living room");
    assert_eq!(entity["attributes"]["brightness"], 180);
    assert_eq!(entity["hidden"], false);
    assert_eq!(entity["last_changed"], "2026-09-22T18:04:11.250612+00:00");
    assert_eq!(
        entity["extra"]["context"]["id"], "01HZY0A",
        "unmodelled members are kept under extra"
    );

    let hidden = call(
        &client,
        "get_entity",
        json!({"entity_id": "sensor.battery_unknown"}),
    )
    .expect_structured("get_entity hidden");
    assert_eq!(hidden["hidden"], true);
}

#[test]
fn get_entity_reports_a_missing_entity_as_a_tool_error() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);

    let message = call(
        &client,
        "get_entity",
        json!({"entity_id": "light.does_not_exist"}),
    );
    let result = message.expect_tool_error("a missing entity");
    assert_eq!(result["_meta"]["errorKind"], "not-found");
    assert_eq!(result["_meta"]["httpStatus"], 404);
    assert!(
        message.text().contains("light.does_not_exist"),
        "the message should name what was asked for"
    );

    // The tool still refuses nonsense before reaching the network.
    let nonsense = call(&client, "get_entity", json!({"entity_id": "   "}));
    let result = nonsense.expect_tool_error("a blank entity id");
    assert_eq!(result["_meta"]["errorKind"], "invalid-arguments");
    assert_eq!(
        fake.requests(),
        vec!["/api/states/light.does_not_exist".to_string()],
        "a rejected call must not reach Home Assistant"
    );
}

#[test]
fn get_entities_separates_found_from_missing() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);

    let batch = call(
        &client,
        "get_entities",
        json!({"entity_ids": ["light.living_room", "light.bedroom", "light.attic", "light.living_room"]}),
    )
    .expect_structured("get_entities");
    assert_eq!(batch["requested"], 3, "duplicates are folded away");
    assert_eq!(batch["found"], 2);
    assert_eq!(batch["missing"], json!(["light.attic"]));
    assert_eq!(batch["entities"].as_array().unwrap().len(), 2);
    assert_eq!(
        fake.count("/api/states"),
        1,
        "one request, whatever the number of ids"
    );
}

#[test]
fn list_services_flattens_the_catalog_and_marks_required_fields() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);

    let all = call(&client, "list_services", json!({})).expect_structured("list_services");
    assert_eq!(all["total_service_domains"], 3);
    assert_eq!(all["total_services"], 5);
    assert_eq!(all["matched"], 5);
    let first = &all["services"].as_array().unwrap()[0];
    assert_eq!(
        first["domain"], "homeassistant",
        "services are listed by domain and service name"
    );
    assert_eq!(first["service"], "restart");
    assert_eq!(first["field_count"], 0);

    let turn_on = all["services"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["service"] == "turn_on")
        .expect("light.turn_on");
    assert_eq!(
        turn_on["targets_entities"], true,
        "a target.entity_id selector means it takes entities"
    );
    assert_eq!(turn_on["field_count"], 3);
    assert_eq!(
        turn_on["field_names"],
        json!(["brightness", "rgb_color", "transition"])
    );
    assert_eq!(turn_on["required_fields"], json!([]));

    let forecast = all["services"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["service"] == "get_forecasts")
        .expect("weather.get_forecasts");
    assert_eq!(forecast["required_fields"], json!(["is_daily"]));

    let filtered = call(&client, "list_services", json!({"domain": "light"}))
        .expect_structured("list_services by domain");
    assert_eq!(filtered["matched"], 2);
    let searched = call(&client, "list_services", json!({"query": "restart"}))
        .expect_structured("list_services search");
    assert_eq!(searched["matched"], 1);
    assert_eq!(searched["services"][0]["domain"], "homeassistant");
}

#[test]
fn get_service_explains_fields_and_suggests_corrections() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);

    let service = call(
        &client,
        "get_service",
        json!({"domain": "LIGHT", "service": "Turn_On"}),
    )
    .expect_structured("get_service");
    assert_eq!(
        service["domain"], "light",
        "the lookup is case-insensitive and echoes what was found"
    );
    assert_eq!(service["name"], "Turn on");
    assert!(
        service["target"]["entity_id"].is_object(),
        "the target selector is passed through"
    );
    assert_eq!(service["fields"].as_object().unwrap().len(), 3);
    let brightness = service["field_summaries"]
        .as_array()
        .unwrap()
        .iter()
        .find(|field| field["name"] == "brightness")
        .expect("brightness");
    assert_eq!(brightness["selector"], "number");
    assert_eq!(brightness["required"], false);
    assert!(
        brightness["example"]
            .as_i64()
            .is_some_and(|value| value > 0 && value < 255),
        "an invented example should sit inside the selector's bounds: {}",
        brightness["example"]
    );
    let transition = service["field_summaries"]
        .as_array()
        .unwrap()
        .iter()
        .find(|field| field["name"] == "transition")
        .expect("transition");
    assert_eq!(
        transition["example"], 2,
        "a declared example beats a derived one"
    );
    let rgb = service["field_summaries"]
        .as_array()
        .unwrap()
        .iter()
        .find(|field| field["name"] == "rgb_color")
        .expect("rgb_color");
    assert_eq!(
        rgb["example"],
        json!([255, 160, 122]),
        "an example beats a guess"
    );
    let forecast = call(
        &client,
        "get_service",
        json!({"domain": "weather", "service": "get_forecasts"}),
    )
    .expect_structured("weather.get_forecasts");
    let kind = forecast["field_summaries"]
        .as_array()
        .unwrap()
        .iter()
        .find(|field| field["name"] == "type")
        .expect("type");
    assert_eq!(kind["options"], json!(["today", "twice_daily"]));
    let daily = forecast["field_summaries"]
        .as_array()
        .unwrap()
        .iter()
        .find(|field| field["name"] == "is_daily")
        .expect("is_daily");
    assert_eq!(daily["required"], true);

    let typo = call(
        &client,
        "get_service",
        json!({"domain": "ligth", "service": "turn_on"}),
    );
    let result = typo.expect_tool_error("a misspelled domain");
    assert_eq!(result["_meta"]["errorKind"], "not-found");
    assert!(
        typo.text().contains("light"),
        "the client should be offered the right domain: {}",
        typo.text()
    );

    let wrong_service = call(
        &client,
        "get_service",
        json!({"domain": "light", "service": "set_brightness"}),
    );
    assert!(
        wrong_service.text().contains("turn_on"),
        "the client should be offered a service that exists: {}",
        wrong_service.text()
    );
}

#[test]
fn get_entity_history_sorts_filters_and_pages() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);

    let all =
        call(&client, "get_entity_history", json!({})).expect_structured("get_entity_history");
    assert_eq!(all["total_entries"], 5);
    assert_eq!(all["matched"], 5);
    assert_eq!(all["returned"], 5);
    assert!(all["next_cursor"].is_null());
    assert_eq!(
        all["entries"][0]["entity_id"], "light.living_room",
        "newest first"
    );
    assert_eq!(
        all["entries"][0]["when"],
        "2026-09-22T18:04:11.250612+00:00"
    );
    assert!(
        all["entity_filter"].is_null()
            && all["window_start"].is_null()
            && all["window_end"].is_null()
    );

    let domain = call(&client, "get_entity_history", json!({"entity_id": "light"}))
        .expect_structured("history by domain");
    assert_eq!(domain["matched"], 3);
    assert_eq!(domain["entity_filter"], "light");

    let entity = call(
        &client,
        "get_entity_history",
        json!({"entity_id": "light.living_room"}),
    )
    .expect_structured("history by entity");
    assert_eq!(entity["matched"], 2);
    assert_eq!(entity["entries"][1]["state"], "off");

    let windowed = call(
        &client,
        "get_entity_history",
        json!({"start_time": "2026-09-22T06:30:00Z", "end_time": "2026-09-22T07:02:00Z"}),
    )
    .expect_structured("history in a window");
    assert_eq!(
        windowed["matched"], 2,
        "both bounds are inclusive: 06:31 and 07:02"
    );
    assert_eq!(
        windowed["window_start"], "2026-09-22T06:30:00Z",
        "the filter is echoed back as sent"
    );

    let searched = call(&client, "get_entity_history", json!({"query": "turned on"}))
        .expect_structured("history search");
    assert_eq!(searched["matched"], 2);

    let page = call(&client, "get_entity_history", json!({"limit": 2}))
        .expect_structured("history page one");
    assert_eq!(page["returned"], 2);
    let cursor = page["next_cursor"].as_str().unwrap().to_string();
    let next = call(
        &client,
        "get_entity_history",
        json!({"limit": 2, "cursor": &cursor}),
    )
    .expect_structured("history page two");
    assert_eq!(next["returned"], 2);
    assert_ne!(page["entries"][0]["when"], next["entries"][0]["when"]);

    // The query string reaching Home Assistant is the one that was asked for.
    let requested = fake
        .requests()
        .iter()
        .any(|target| target.contains("start_time=2026-09-22T06%3A30%3A00Z"));
    assert!(
        requested,
        "the window is pushed to the server too: {:?}",
        fake.requests()
    );
}

#[test]
fn history_rejects_nonsense_windows_with_readable_advice() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);

    let unparseable = call(
        &client,
        "get_entity_history",
        json!({"start_time": "last tuesday"}),
    );
    let result = unparseable.expect_tool_error("an unparseable start_time");
    assert_eq!(result["_meta"]["errorKind"], "invalid-arguments");
    assert!(unparseable.text().contains("start_time"));

    let backwards = call(
        &client,
        "get_entity_history",
        json!({"start_time": "2026-09-22T12:00:00Z", "end_time": "2026-09-22T01:00:00Z"}),
    );
    assert!(
        backwards.text().contains("end_time"),
        "the message must name the offending bound"
    );

    let impossible_day = call(
        &client,
        "get_entity_history",
        json!({"start_time": "2026-02-30T00:00:00Z"}),
    );
    assert!(
        impossible_day.text().contains("start_time"),
        "an impossible date is caught too"
    );
    assert_eq!(
        fake.count("/api/logbook"),
        0,
        "none of these may reach the server: {:?}",
        fake.requests()
    );
}

#[test]
fn get_error_log_tails_filters_and_clips_long_lines() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);
    let total_lines = common::error_log().lines().count();

    let default_page = call(&client, "get_error_log", json!({})).expect_structured("get_error_log");
    assert_eq!(default_page["total_lines"], total_lines as i64);
    assert_eq!(default_page["level_filter"], "any");
    assert_eq!(default_page["tail"], true);
    assert_eq!(default_page["truncated"], false);
    assert_eq!(default_page["matched"], total_lines as i64);
    assert!(default_page["lines"]
        .as_array()
        .unwrap()
        .last()
        .unwrap()
        .as_str()
        .unwrap()
        .contains("Recovered"));

    let errors = call(&client, "get_error_log", json!({"level": "error"}))
        .expect_structured("get_error_log errors");
    assert_eq!(errors["matched"], 3);
    assert!(errors["lines"]
        .as_array()
        .unwrap()
        .iter()
        .all(|line| line.as_str().unwrap().contains("ERROR")));
    assert_eq!(errors["level_filter"], "error");

    let tailed = call(
        &client,
        "get_error_log",
        json!({"level": "error", "max_lines": 2}),
    )
    .expect_structured("get_error_log tail");
    assert_eq!(tailed["truncated"], true);
    assert_eq!(tailed["returned"], 2);
    assert!(
        tailed["lines"][0].as_str().unwrap().contains("recorder"),
        "the tail keeps the newest lines"
    );

    let head = call(
        &client,
        "get_error_log",
        json!({"level": "error", "max_lines": 1, "tail": false}),
    )
    .expect_structured("get_error_log head");
    assert!(
        head["lines"][0].as_str().unwrap().contains("mqtt"),
        "without tail the oldest lines come first"
    );

    let searched = call(&client, "get_error_log", json!({"contains": "recorder"}))
        .expect_structured("get_error_log contains");
    assert_eq!(searched["matched"], 1);
    assert_eq!(searched["contains"], "recorder");
    assert_eq!(
        searched["lines"][0].as_str().unwrap().chars().count(),
        500,
        "a runaway line is clipped, not dropped"
    );

    let nothing = call(
        &client,
        "get_error_log",
        json!({"contains": "nothing matches this"}),
    )
    .expect_structured("get_error_log no match");
    assert_eq!(nothing["matched"], 0);
    assert_eq!(nothing["lines"], json!([]));
}

#[test]
fn list_events_reports_listener_counts() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);

    let all = call(&client, "list_events", json!({})).expect_structured("list_events");
    assert_eq!(all["total_event_types"], 5);
    assert_eq!(all["matched"], 5);
    let names: Vec<&str> = all["event_types"]
        .as_array()
        .unwrap()
        .iter()
        .map(|row| row["event"].as_str().unwrap())
        .collect();
    assert_eq!(
        names,
        vec![
            "automation_triggered",
            "call_service",
            "homeassistant_stop",
            "mqtt_message_received",
            "state_changed"
        ]
    );
    assert_eq!(all["event_types"][1]["listener_count"], 12);

    let searched = call(&client, "list_events", json!({"query": "state"}))
        .expect_structured("list_events search");
    assert_eq!(searched["matched"], 1);
    assert_eq!(searched["event_types"][0]["event"], "state_changed");
    assert_eq!(
        searched["total_event_types"], 5,
        "the total is the instance's, not the page's"
    );
}

#[test]
fn a_bad_token_is_reported_once_and_in_terms_the_user_can_act_on() {
    let fake = FakeHa::standard();
    let client = common::Client::with_env(
        &fake.url,
        "the-wrong-token",
        &[("HA_MCP_LOG_LEVEL", "debug")],
    );

    let message = call(
        &client,
        "get_entity",
        json!({"entity_id": "light.living_room"}),
    );
    let result = message.expect_tool_error("a call with a bad token");
    assert_eq!(result["_meta"]["errorKind"], "unauthorized");
    assert_eq!(result["_meta"]["httpStatus"], 401);
    let text = message.text().to_ascii_lowercase();
    assert!(
        text.contains("token"),
        "the advice should mention the token: {}",
        message.text()
    );
    assert!(
        !message.text().contains("the-wrong-token"),
        "the token must never be echoed back"
    );

    // Every other tool hits the same wall, and the message stays consistent.
    let another = call(&client, "list_entities", json!({}));
    assert_eq!(
        another.expect_tool_error("list_entities with a bad token")["_meta"]["errorKind"],
        "unauthorized"
    );
}

#[test]
fn an_unreachable_instance_is_reported_rather_than_guessed_at() {
    // Nothing listens on this port: the bind below hands out a free one and drops it.
    let port = {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        listener.local_addr().unwrap().port()
    };
    let client = common::Client::start(&format!("http://127.0.0.1:{port}"));

    let message = call(&client, "list_entities", json!({}));
    let result = message.expect_tool_error("a call against a dead instance");
    assert_eq!(result["_meta"]["errorKind"], "unreachable");
    assert!(
        message.text().contains("127.0.0.1"),
        "the message should name the address that failed"
    );

    // The server itself is fine: the protocol never depends on Home Assistant.
    let pinged = client.request("ping", Value::Null);
    assert_eq!(
        pinged.expect_result("ping against a dead instance")["resultType"],
        "complete"
    );
}

#[test]
fn a_slow_instance_times_out_instead_of_blocking_the_server() {
    let fake = FakeHa::start(
        TOKEN,
        vec![(
            "/api/states",
            common::Response::ok(json!(common::states())).delayed(Duration::from_secs(5)),
        )],
    );
    let client = common::Client::with_env(&fake.url, TOKEN, &[("HA_MCP_TIMEOUT_SECS", "1")]);

    let message = call(&client, "list_entities", json!({}));
    let result = message.expect_tool_error("a call that outstays the timeout");
    assert_eq!(result["_meta"]["errorKind"], "timeout");

    let fast = client.request("tools/list", json!({}));
    assert!(
        fast.get("error").is_none(),
        "a slow instance must not stall the protocol"
    );
}

#[test]
fn an_overlong_response_is_refused_with_its_size_named() {
    // 4 KiB is the smallest cap the server accepts.
    let filler = "x".repeat(200 * 1024);
    let fake = FakeHa::start(
        TOKEN,
        vec![("/api/events", common::Response::ok(json!([filler])))],
    );
    let client =
        common::Client::with_env(&fake.url, TOKEN, &[("HA_MCP_MAX_RESPONSE_BYTES", "4096")]);

    let message = call(&client, "list_events", json!({}));
    let result = message.expect_tool_error("a response over the cap");
    assert_eq!(result["_meta"]["errorKind"], "response-too-large");
    assert!(
        message.text().contains("4096"),
        "the cap should be named so it can be raised: {}",
        message.text()
    );
}

#[test]
fn tools_never_ask_home_assistant_to_change_anything() {
    let fake = FakeHa::standard();
    let client = common::Client::start(&fake.url);

    for name in [
        "get_instance_info",
        "get_config",
        "list_entities",
        "get_entity",
        "list_services",
        "get_entity_history",
        "get_error_log",
        "list_events",
        "list_domains",
        "list_integrations",
        "get_entities",
    ] {
        let message = call(&client, name, arguments_for(name));
        assert!(
            message.get("error").is_none(),
            "{name} failed: {}",
            message["error"]
        );
    }
    let methods = client.stderr_text();
    assert!(
        !methods.contains("POST"),
        "the log should show nothing but GETs:\n{methods}"
    );
    for target in fake.requests() {
        assert!(
            target.starts_with("/api/"),
            "the server must stay inside the API surface: {target}"
        );
    }
}
