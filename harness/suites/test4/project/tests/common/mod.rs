//! Shared scaffolding for the integration tests: a fake Home Assistant over a
//! loopback socket, and a handle on the real `ha-mcp` binary driven over stdio.
//!
//! Nothing here talks to the network beyond `127.0.0.1`, so the suite runs in a
//! sandbox without outbound access.

#![allow(dead_code)]

pub mod validate;

use std::collections::BTreeMap;
use std::io::{BufRead, BufReader, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use serde_json::{json, Value};

/// Token the fake instance accepts and the server is configured with.
pub const TOKEN: &str = "integration-token";

/// How long to wait for the server to say something before calling it stalled.
const DEADLINE: Duration = Duration::from_secs(15);

// ---------------------------------------------------------------------------
// fake Home Assistant
// ---------------------------------------------------------------------------

/// A canned HTTP answer.
#[derive(Clone)]
pub struct Response {
    pub status: u16,
    pub content_type: &'static str,
    pub body: String,
    pub delay: Duration,
}

impl Response {
    pub fn json(status: u16, body: Value) -> Response {
        Response {
            status,
            content_type: "application/json",
            body: body.to_string(),
            delay: Duration::ZERO,
        }
    }

    pub fn ok(body: Value) -> Response {
        Response::json(200, body)
    }

    pub fn text(status: u16, body: &str) -> Response {
        Response {
            status,
            content_type: "text/plain",
            body: body.to_string(),
            delay: Duration::ZERO,
        }
    }

    /// Answers only after `delay`, to stand in for a slow instance.
    pub fn delayed(self, delay: Duration) -> Response {
        Response { delay, ..self }
    }
}

/// A loopback HTTP server that replays a fixed set of Home Assistant answers.
pub struct FakeHa {
    pub url: String,
    addr: SocketAddr,
    stop: Arc<AtomicBool>,
    seen: Arc<Mutex<Vec<String>>>,
    accept: Option<JoinHandle<()>>,
}

impl FakeHa {
    /// Serves `routes` (matched on the path, ignoring the query string) and
    /// answers anything else the way the recorded fixture does.
    pub fn start(token: &str, routes: Vec<(&str, Response)>) -> FakeHa {
        let listener = TcpListener::bind("127.0.0.1:0").expect("a free loopback port");
        let addr = listener.local_addr().expect("a local address");
        let stop = Arc::new(AtomicBool::new(false));
        let seen: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));

        let table: BTreeMap<String, Response> = routes
            .into_iter()
            .map(|(path, body)| (path.to_string(), body))
            .collect();
        let token = token.to_string();
        let thread_seen = Arc::clone(&seen);
        let thread_stop = Arc::clone(&stop);

        let accept = std::thread::spawn(move || {
            let _ = listener.set_nonblocking(true);
            while !thread_stop.load(Ordering::SeqCst) {
                match listener.accept() {
                    Ok((stream, _)) => {
                        let table = table.clone();
                        let token = token.clone();
                        let seen = Arc::clone(&thread_seen);
                        std::thread::spawn(move || {
                            let _ = serve_one(stream, &table, &token, &seen);
                        });
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        std::thread::sleep(Duration::from_millis(5));
                    }
                    Err(_) => break,
                }
            }
        });

        FakeHa {
            url: format!("http://{addr}"),
            addr,
            stop,
            seen,
            accept: Some(accept),
        }
    }

    /// Every endpoint the tools can reach, with realistic payloads.
    pub fn standard() -> FakeHa {
        FakeHa::start(TOKEN, standard_routes())
    }

    /// Request targets in the order they arrived, query string included.
    pub fn requests(&self) -> Vec<String> {
        self.seen.lock().expect("the request log").clone()
    }

    pub fn count(&self, path: &str) -> usize {
        self.requests()
            .iter()
            .filter(|target| target.split('?').next() == Some(path))
            .count()
    }
}

impl Drop for FakeHa {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
        // Unblock the accept loop, which is otherwise parked in `accept`.
        if let Ok(mut stream) = TcpStream::connect(self.addr) {
            let _ = stream.write_all(b"GET /api/ HTTP/1.1\r\n\r\n");
        }
        if let Some(accept) = self.accept.take() {
            let _ = accept.join();
        }
    }
}

/// Reads one request, answers it, and closes the connection.
fn serve_one(
    mut stream: TcpStream,
    routes: &BTreeMap<String, Response>,
    token: &str,
    seen: &Arc<Mutex<Vec<String>>>,
) -> std::io::Result<()> {
    stream.set_read_timeout(Some(Duration::from_secs(10)))?;
    let mut reader = BufReader::new(stream.try_clone()?);

    let mut target = String::new();
    let read = reader.read_line(&mut target)?;
    if read == 0 {
        return Ok(()); // the wake-up connect from `Drop`
    }
    let mut pieces = target.split_whitespace();
    let method = pieces.next().unwrap_or("").to_string();
    let path = pieces.next().unwrap_or("").to_string();
    seen.lock().expect("the request log").push(path.clone());

    let mut authorization = String::new();
    loop {
        let mut line = String::new();
        if reader.read_line(&mut line)? == 0 || line.trim().is_empty() {
            break;
        }
        if line.to_ascii_lowercase().starts_with("authorization:") {
            authorization = line
                .split_once(':')
                .map(|x| x.1)
                .unwrap_or("")
                .trim()
                .to_string();
        }
    }

    let response = if authorization != format!("Bearer {token}") {
        Response::json(
            401,
            json!({"message": "Invalid auth token provided", "error": {"code": "unauthorized", "message": "Invalid auth token provided"}}),
        )
    } else if method != "GET" {
        Response::json(
            405,
            json!({"message": "Method not allowed", "hint": "the tools are read-only"}),
        )
    } else {
        let without_query = path.split('?').next().unwrap_or("").to_string();
        routes
            .get(&without_query)
            .cloned()
            .unwrap_or_else(|| Response::json(404, recorded_404(&without_query)))
    };

    std::thread::sleep(response.delay);
    let body = response.body;
    write!(
        stream,
        "HTTP/1.1 {} {}\r\nContent-Type: {}; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        response.status,
        status_text(response.status),
        response.content_type,
        body.len(),
        body
    )?;
    stream.flush()?;
    Ok(())
}

fn recorded_404(path: &str) -> Value {
    json!({
        "error": format!("{path} is not in the recorded fixture"),
        "hint": "this eval replays a recording; only recorded paths exist",
    })
}

fn status_text(status: u16) -> &'static str {
    match status {
        200 => "OK",
        400 => "Bad Request",
        401 => "Unauthorized",
        403 => "Forbidden",
        404 => "Not Found",
        405 => "Method Not Allowed",
        429 => "Too Many Requests",
        500 => "Internal Server Error",
        503 => "Service Unavailable",
        _ => "Unknown",
    }
}

// ---------------------------------------------------------------------------
// driving the real binary
// ---------------------------------------------------------------------------

/// A running `ha-mcp` process, plus background readers for both of its pipes so
/// a test can wait for a message or assert that nothing comes.
pub struct Client {
    child: Child,
    stdin: Mutex<Option<ChildStdin>>,
    inbox: Arc<Inbox>,
    stderr: Arc<Mutex<Vec<String>>>,
    readers: Option<(JoinHandle<()>, JoinHandle<()>)>,
    next_id: std::sync::atomic::AtomicI64,
}

/// Messages in the order stdout delivered them, plus answers that arrived while
/// the test was waiting for a different id. Workers run concurrently, so a
/// server is free to answer out of order and the tests must cope.
struct Inbox {
    messages: Mutex<std::collections::VecDeque<Value>>,
    parked: Mutex<std::collections::BTreeMap<String, Value>>,
    changed: Condvar,
}

impl Inbox {
    fn new() -> Inbox {
        Inbox {
            messages: Mutex::new(std::collections::VecDeque::new()),
            parked: Mutex::new(std::collections::BTreeMap::new()),
            changed: Condvar::new(),
        }
    }
}

impl Client {
    /// Starts the server against `ha_url` with the standard token.
    pub fn start(ha_url: &str) -> Client {
        Client::with_env(ha_url, TOKEN, &[("HA_MCP_LOG_LEVEL", "debug")])
    }

    /// Starts the server with explicit environment overrides. A `None` value
    /// removes the variable, which matters for the configuration tests.
    pub fn with_env(ha_url: &str, token: &str, extra: &[(&str, &str)]) -> Client {
        let mut command = Command::new(env!("CARGO_BIN_EXE_ha-mcp"));
        command
            .env("HA_URL", ha_url)
            .env("HA_TOKEN", token)
            .env("HA_MCP_LOG_LEVEL", "debug")
            .env_remove("HA_MCP_TOOL_PAGE_SIZE")
            .env_remove("HA_MCP_STRICT_META")
            .env_remove("HA_MCP_TIMEOUT_SECS")
            .env_remove("HA_MCP_MAX_RESPONSE_BYTES")
            .env_remove("HA_MCP_TLS_NO_VERIFY")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        for (key, value) in extra {
            command.env(key, value);
        }

        let mut child = command.spawn().expect("the server binary must start");
        let stdin = child.stdin.take().expect("stdin");
        let stdout = child.stdout.take().expect("stdout");
        let stderr_pipe = child.stderr.take().expect("stderr");

        let inbox = Arc::new(Inbox::new());
        let reader_inbox = Arc::clone(&inbox);
        let reader = std::thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            let mut line = String::new();
            while reader.read_line(&mut line).unwrap_or(0) > 0 {
                let parsed = match serde_json::from_str::<Value>(line.trim_end()) {
                    Ok(value) => value,
                    Err(error) => {
                        // Recording the raw line keeps the failure message useful.
                        json!({"_unparsable": line.trim_end().to_string(), "_reason": error.to_string()})
                    }
                };
                let mut queue = reader_inbox.messages.lock().expect("the inbox");
                queue.push_back(parsed);
                reader_inbox.changed.notify_all();
                line.clear();
            }
        });

        let stderr_log: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
        let reader_log = Arc::clone(&stderr_log);
        let stderr_reader = std::thread::spawn(move || {
            let mut reader = BufReader::new(stderr_pipe);
            let mut line = String::new();
            while reader.read_line(&mut line).unwrap_or(0) > 0 {
                reader_log
                    .lock()
                    .expect("the log")
                    .push(line.trim_end().to_string());
                line.clear();
            }
        });

        Client {
            child,
            stdin: Mutex::new(Some(stdin)),
            inbox,
            stderr: stderr_log,
            readers: Some((reader, stderr_reader)),
            next_id: std::sync::atomic::AtomicI64::new(1),
        }
    }

    /// Starts the server with no Home Assistant configuration at all.
    pub fn without_configuration() -> Client {
        let mut command = Command::new(env!("CARGO_BIN_EXE_ha-mcp"));
        for key in [
            "HA_URL",
            "HA_BASE_URL",
            "HA_TOKEN",
            "HA_LONG_LIVED_ACCESS_TOKEN",
        ] {
            command.env_remove(key);
        }
        let child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .expect("the server binary must start");
        Client {
            child,
            stdin: Mutex::new(None),
            inbox: Arc::new(Inbox::new()),
            stderr: Arc::new(Mutex::new(Vec::new())),
            readers: None,
            next_id: std::sync::atomic::AtomicI64::new(1),
        }
    }

    /// Sends one line and returns it unchanged.
    pub fn send(&self, line: &str) {
        let mut guard = self.stdin.lock().expect("stdin");
        let stdin = guard.as_mut().expect("stdin is still open");
        stdin.write_all(line.as_bytes()).expect("writing to stdin");
        stdin.write_all(b"\n").expect("writing to stdin");
        stdin.flush().expect("flushing stdin");
    }

    /// Sends a request with a fresh id and returns the matching message.
    pub fn request(&self, method: &str, params: Value) -> Value {
        let id = self.next_id.fetch_add(1, Ordering::SeqCst);
        self.request_as(id, method, params)
    }

    pub fn request_as(&self, id: i64, method: &str, params: Value) -> Value {
        let line =
            json!({"jsonrpc": "2.0", "id": id, "method": method, "params": params}).to_string();
        self.send(&line);
        self.recv_for(id, &format!("the answer to {method} (id {id})"))
    }

    pub fn notify(&self, method: &str, params: Value) {
        self.send(&json!({"jsonrpc": "2.0", "method": method, "params": params}).to_string());
    }

    /// Returns the next message, whatever it is.
    pub fn recv(&self, what: &str) -> Value {
        let started = Instant::now();
        let mut queue = self.inbox.messages.lock().expect("the inbox");
        loop {
            if let Some(message) = queue.pop_front() {
                return message;
            }
            let (held, wait) = self
                .inbox
                .changed
                .wait_timeout(queue, Duration::from_millis(200))
                .expect("the inbox is not poisoned");
            queue = held;
            if wait.timed_out() && started.elapsed() > DEADLINE {
                panic!(
                    "timed out waiting for {what}.\nserver log:\n{}",
                    self.stderr_text()
                );
            }
        }
    }

    /// Waits for the answer to one particular id, setting aside anything that
    /// arrives for another request meanwhile.
    pub fn recv_for(&self, id: i64, what: &str) -> Value {
        let wanted = json!(id);
        let started = Instant::now();
        loop {
            let mut queue = self.inbox.messages.lock().expect("the inbox");
            if let Some(position) = queue
                .iter()
                .position(|message| message.get("id") == Some(&wanted))
            {
                return queue.remove(position).expect("the answer was just located");
            }
            let mut parked = self.inbox.parked.lock().expect("the parked answers");
            while let Some(other) = queue.pop_front() {
                let key = other
                    .get("id")
                    .map(Value::to_string)
                    .unwrap_or_else(|| "?".to_string());
                parked.insert(key, other);
            }
            drop(parked);
            let (held, _wait) = self
                .inbox
                .changed
                .wait_timeout(queue, Duration::from_millis(200))
                .expect("the inbox is not poisoned");
            drop(held);
            if started.elapsed() > DEADLINE {
                panic!(
                    "timed out waiting for {what}.
server log:
{}",
                    self.stderr_text()
                );
            }
        }
    }

    /// Asserts that nothing arrives within `window`.
    pub fn expect_silence(&self, window: Duration) {
        let mut queue = self.inbox.messages.lock().expect("the inbox");
        let (held, _wait) = self
            .inbox
            .changed
            .wait_timeout(queue, window)
            .expect("the inbox is not poisoned");
        queue = held;
        let parked = self.inbox.parked.lock().expect("the parked answers");
        if let Some(message) = queue
            .pop_front()
            .or_else(|| parked.values().next().cloned())
        {
            panic!("expected silence but the server answered: {message}");
        }
    }

    pub fn has_pending(&self) -> bool {
        !self.inbox.messages.lock().expect("the inbox").is_empty()
            || !self
                .inbox
                .parked
                .lock()
                .expect("the parked answers")
                .is_empty()
    }

    pub fn stderr_text(&self) -> String {
        self.stderr.lock().expect("the log").join("\n")
    }

    pub fn log_mentions(&self, needle: &str) -> bool {
        self.stderr
            .lock()
            .expect("the log")
            .iter()
            .any(|line| line.contains(needle))
    }

    /// Closes stdin, which is how a real MCP client shuts the server down.
    pub fn close(mut self) -> i32 {
        self.close_stdin();
        let status = self.child.wait().expect("the server should exit");
        self.finish(status.code().unwrap_or(-1))
    }

    /// Asserts the process already exited, e.g. after a configuration failure.
    pub fn expect_exit_code(mut self, expected: i32) {
        self.close_stdin();
        let status = self.child.wait().expect("the server should exit");
        let code = status.code().unwrap_or(-1);
        assert_eq!(
            code,
            expected,
            "unexpected exit code; log:\n{}",
            self.stderr_text()
        );
        self.finish(code);
    }

    /// Hangs up stdin, which is how a real MCP client shuts the server down.
    fn close_stdin(&mut self) {
        drop(self.stdin.get_mut().expect("stdin").take());
    }

    fn finish(&mut self, code: i32) -> i32 {
        if let Some((stdout, stderr)) = self.readers.take() {
            let _ = stdout.join();
            let _ = stderr.join();
        }
        code
    }
}

impl Drop for Client {
    fn drop(&mut self) {
        // Never leave a server running behind a failed assertion.
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

/// Sends a request without a `params` member, which some clients omit.
pub fn request_without_params(id: i64, method: &str) -> String {
    format!(r#"{{"jsonrpc":"2.0","id":{id},"method":"{method}"}}"#)
}

/// Every declared tool name, in the order `tools/list` gives them.
pub fn tool_names(list: &Value) -> Vec<String> {
    list["tools"]
        .as_array()
        .expect("`tools/list` must return an array of tools")
        .iter()
        .map(|tool| {
            tool["name"]
                .as_str()
                .expect("every tool has a name")
                .to_string()
        })
        .collect()
}

/// Follows `nextCursor` until the last page, collecting every tool.
pub fn all_tools(client: &Client) -> Vec<Value> {
    let mut tools: Vec<Value> = Vec::new();
    let mut cursor = String::new();
    loop {
        let params = if cursor.is_empty() {
            json!({})
        } else {
            json!({"cursor": cursor})
        };
        let page = client
            .request("tools/list", params)
            .expect_result("tools/list");
        tools.extend(page["tools"].as_array().expect("a tools array").clone());
        match page.get("nextCursor").and_then(Value::as_str) {
            Some(next) => cursor = next.to_string(),
            None => return tools,
        }
    }
}

// ---------------------------------------------------------------------------
// assertions
// ---------------------------------------------------------------------------

/// Convenience wrappers so the tests read as intent rather than as indexing.
/// Convenience wrappers so the tests read as intent rather than as indexing.
/// Values are returned by clone: these tests would rather be readable than lean.
pub trait Message {
    fn expect_result(&self, what: &str) -> Value;
    fn expect_error(&self, what: &str, code: i64) -> Value;
    fn expect_tool_error(&self, what: &str) -> Value;
    fn expect_structured(&self, what: &str) -> Value;
    fn text(&self) -> String;
}

impl Message for Value {
    fn expect_result(&self, what: &str) -> Value {
        assert!(
            self.get("error").is_none(),
            "{what} failed: {}",
            self["error"]
        );
        let result = self.get("result").unwrap_or(&Value::Null);
        assert!(
            result.is_object(),
            "{what} must answer with an object result, got {self}"
        );
        result.clone()
    }

    fn expect_error(&self, what: &str, code: i64) -> Value {
        let error = self.get("error").unwrap_or(&Value::Null);
        assert!(
            error.is_object(),
            "{what} must answer with a JSON-RPC error, got {self}"
        );
        assert_eq!(
            error["code"],
            code,
            "{what}: wrong error code, message {:?}",
            error["message"].as_str()
        );
        assert!(
            error["message"]
                .as_str()
                .is_some_and(|text| !text.is_empty()),
            "{what} must explain itself"
        );
        error.clone()
    }

    /// A tool-level failure: a normal result, flagged, with text and no
    /// structured content.
    fn expect_tool_error(&self, what: &str) -> Value {
        let result = self.expect_result(what);
        assert_eq!(
            result["isError"], true,
            "{what} should be flagged as a tool error: {result}"
        );
        assert!(
            result.get("structuredContent").is_none(),
            "{what} must not ship structured content on failure"
        );
        assert!(
            result["content"][0]["text"]
                .as_str()
                .is_some_and(|text| !text.is_empty()),
            "{what} must explain the failure"
        );
        result
    }

    /// A successful tool call: text plus structured content that agree.
    fn expect_structured(&self, what: &str) -> Value {
        let result = self.expect_result(what);
        assert!(
            result
                .get("isError")
                .is_none_or(|flag| flag.as_bool() == Some(false)),
            "{what} reported a tool error: {}",
            result["content"]
        );
        let structured = result["structuredContent"].clone();
        assert!(
            structured.is_object(),
            "{what} must carry structuredContent"
        );
        let text = result["content"][0]["text"]
            .as_str()
            .expect("{what} must carry a text block");
        assert_eq!(result["content"][0]["mimeType"], "application/json");
        let parsed: Value =
            serde_json::from_str(text).expect("the text block must be the structured content");
        assert_eq!(
            parsed, structured,
            "{what}: the text block must mirror structuredContent"
        );
        structured
    }

    /// The first text block, whether called on a result or on a whole envelope.
    fn text(&self) -> String {
        let content = self
            .get("content")
            .or_else(|| self["result"].get("content"))
            .unwrap_or(&Value::Null);
        content[0]["text"].as_str().unwrap_or("").to_string()
    }
}

/// The standard payload set, mirroring the shapes Home Assistant really returns.
pub fn standard_routes() -> Vec<(&'static str, Response)> {
    let mut routes: Vec<(&'static str, Response)> = vec![
        ("/api/", Response::ok(json!({"message": "API running."}))),
        ("/api/config", Response::ok(config())),
        ("/api/states", Response::ok(json!(states()))),
        ("/api/services", Response::ok(services())),
        ("/api/events", Response::ok(json!(events()))),
        ("/api/logbook", Response::ok(json!(logbook()))),
        ("/api/error_log", Response::text(200, &error_log())),
    ];
    // Every entity in `states()` answers on its own endpoint as well.
    for path in ENTITY_PATHS {
        let entity_id = path.trim_start_matches("/api/states/");
        routes.push((path, Response::ok(entity(entity_id))));
    }
    routes
}

/// The six entities the fixture knows, as their own endpoints.
const ENTITY_PATHS: [&str; 6] = [
    "/api/states/light.living_room",
    "/api/states/light.bedroom",
    "/api/states/sensor.outside_temperature",
    "/api/states/sensor.battery_unknown",
    "/api/states/switch.coffee_machine",
    "/api/states/climate.thermostat",
];

/// The config document, trimmed to what the handlers project.
pub fn config() -> Value {
    json!({
        "latitude": 52.3702,
        "longitude": 4.8952,
        "elevation": 2,
        "location_name": "Home",
        "version": "2026.9.1",
        "installation_type": "Home Assistant Container",
        "state": "running",
        "external_url": "http://home.example:8123",
        "internal_url": "http://home.example:8123",
        "time_zone": "Europe/Amsterdam",
        "country": "NL",
        "currency": "EUR",
        "developer_mode": true,
        "safe_mode": false,
        "recovery_mode": false,
        "unit_system": {"length": "km", "temperature": "°C", "mass": "g", "time": "h"},
        "components": ["sensor", "light", "climate", "switch", "automation", "history", "logbook", "mqtt.light"],
        "config_dir": "/config",
        "uuid": "1f2c6a1e0b5b4f0e9e0a0d0c0b0a0908",
        "language": "en"
    })
}

/// One state document, used for both the list and the single-entity endpoint.
pub fn entity(entity_id: &str) -> Value {
    match entity_id {
        "light.living_room" => json!({
            "entity_id": "light.living_room",
            "state": "on",
            "attributes": {
                "friendly_name": "Living room",
                "brightness": 180,
                "color_temp_kelvin": 3700,
                "supported_color_modes": ["color_temp", "brightness"],
                "supported_features": 0,
                "icon": "mdi:lamp"
            },
            "last_changed": "2026-09-22T18:04:11.250612+00:00",
            "last_reported": "2026-09-22T18:04:11.250612+00:00",
            "last_updated": "2026-09-22T18:04:11.250612+00:00",
            "context": {"id": "01HZY0A", "parent_id": null, "user_id": null}
        }),
        "light.bedroom" => json!({
            "entity_id": "light.bedroom",
            "state": "off",
            "attributes": {"friendly_name": "Bedroom", "supported_color_modes": ["onoff"]},
            "last_changed": "2026-09-21T22:15:00.000000+00:00",
            "last_reported": "2026-09-21T22:15:00.000000+00:00",
            "last_updated": "2026-09-21T22:15:00.000000+00:00",
            "context": {"id": "01HZY0B", "parent_id": null, "user_id": null}
        }),
        "sensor.outside_temperature" => json!({
            "entity_id": "sensor.outside_temperature",
            "state": "12.4",
            "attributes": {
                "friendly_name": "Outside temperature",
                "device_class": "temperature",
                "state_class": "measurement",
                "unit_of_measurement": "°C"
            },
            "last_changed": "2026-09-22T06:00:00.000000+00:00",
            "last_reported": "2026-09-22T06:00:00.000000+00:00",
            "last_updated": "2026-09-22T06:30:00.000000+00:00",
            "context": {"id": "01HZY0C", "parent_id": null, "user_id": null}
        }),
        "sensor.battery_unknown" => json!({
            "entity_id": "sensor.battery_unknown",
            "state": "unavailable",
            "attributes": {
                "friendly_name": "Sensor battery",
                "device_class": "battery",
                "unit_of_measurement": "%",
                "hidden_by": "user",
                "entity_category": "diagnostic"
            },
            "last_changed": "2026-09-20T04:00:00.000000+00:00",
            "last_reported": "2026-09-20T04:00:00.000000+00:00",
            "last_updated": "2026-09-20T04:00:00.000000+00:00",
            "context": {"id": "01HZY0D", "parent_id": null, "user_id": null}
        }),
        "switch.coffee_machine" => json!({
            "entity_id": "switch.coffee_machine",
            "state": "off",
            "attributes": {"friendly_name": "Coffee machine", "device_class": "switch"},
            "last_changed": "2026-09-22T05:30:00.000000+00:00",
            "last_reported": "2026-09-22T05:30:00.000000+00:00",
            "last_updated": "2026-09-22T05:30:00.000000+00:00",
            "context": {"id": "01HZY0E", "parent_id": null, "user_id": null}
        }),
        "climate.thermostat" => json!({
            "entity_id": "climate.thermostat",
            "state": "heat",
            "attributes": {
                "friendly_name": "Thermostat",
                "hvac_modes": ["off", "heat", "eco"],
                "temperature": 21,
                "current_temperature": 19.8
            },
            "last_changed": "2026-09-22T06:00:00.000000+00:00",
            "last_reported": "2026-09-22T06:00:00.000000+00:00",
            "last_updated": "2026-09-22T06:00:00.000000+00:00",
            "context": {"id": "01HZY0F", "parent_id": null, "user_id": null}
        }),
        _ => json!({
            "entity_id": entity_id,
            "state": "unknown",
            "attributes": {"friendly_name": entity_id},
            "last_changed": "2026-09-22T00:00:00.000000+00:00",
            "last_reported": "2026-09-22T00:00:00.000000+00:00",
            "last_updated": "2026-09-22T00:00:00.000000+00:00",
            "context": {"id": "01HZY0G", "parent_id": null, "user_id": null}
        }),
    }
}

/// The `/api/states` payload, deliberately not sorted by entity id.
pub fn states() -> Vec<Value> {
    [
        "sensor.outside_temperature",
        "light.living_room",
        "switch.coffee_machine",
        "light.bedroom",
        "climate.thermostat",
        "sensor.battery_unknown",
    ]
    .iter()
    .map(|id| entity(id))
    .collect()
}

/// `/api/services`: the wire shape is a list of `{domain, services}` entries.
pub fn services() -> Value {
    json!([
        {
            "domain": "light",
            "services": {
                "turn_on": {
                    "name": "Turn on",
                    "description": "Turns on all light entities.",
                    "target": {"entity_id": {"selector": {"entity": {"domain": ["light"], "multiple": true}}}},
                    "fields": {
                        "brightness": {
                            "name": "Brightness",
                            "description": "The brightness, 0 to 255.",
                            "required": false,
                            "selector": {"number": {"min": 0, "max": 255}}
                        },
                        "transition": {
                            "name": "Transition",
                            "description": "Duration in seconds.",
                            "required": false,
                            "example": 2
                        },
                        "rgb_color": {
                            "name": "RGB color",
                            "required": false,
                            "example": [255, 160, 122]
                        }
                    }
                },
                "turn_off": {
                    "name": "Turn off",
                    "description": "Turns off all light entities.",
                    "target": {"entity_id": {}},
                    "fields": {}
                }
            }
        },
        {
            "domain": "homeassistant",
            "services": {
                "restart": {
                    "name": "Restart",
                    "description": "Restarts Home Assistant.",
                    "fields": {}
                },
                "update_entity": {
                    "name": "Update entity",
                    "description": "Updates the entity to its latest state.",
                    "fields": {
                        "entity_id": {
                            "name": "Entity",
                            "description": "Identifier of the entity.",
                            "required": true,
                            "selector": {"entity": {}}
                        }
                    }
                }
            }
        },
        {
            "domain": "weather",
            "services": {
                "get_forecasts": {
                    "name": "Get forecast",
                    "description": "Get forecast for weather entity.",
                    "target": {"entity_id": {"selector": {"entity": {"domain": ["weather"]}}}},
                    "fields": {
                        "type": {
                            "name": "Type",
                            "description": "Forecast type.",
                            "required": false,
                            "selector": {"select": {"options": ["today", "twice_daily"]}}
                        },
                        "is_daily": {
                            "name": "Is daily",
                            "description": "Result is a daily forecast.",
                            "required": true,
                            "selector": {"boolean": {}}
                        }
                    }
                }
            }
        }
    ])
}

/// `/api/events`.
pub fn events() -> Vec<Value> {
    vec![
        json!({"event": "call_service", "listener_count": 12}),
        json!({"event": "state_changed", "listener_count": 48}),
        json!({"event": "automation_triggered", "listener_count": 3}),
        json!({"event": "homeassistant_stop", "listener_count": 1}),
        json!({"event": "mqtt_message_received", "listener_count": 7}),
    ]
}

/// `/api/logbook`: deliberately unordered, with entries outside every window a
/// test might ask for.
pub fn logbook() -> Vec<Value> {
    vec![
        json!({
            "when": "2026-09-22T18:04:11.250612+00:00",
            "name": "Living room",
            "entity_id": "light.living_room",
            "state": "on",
            "message": "turned on",
            "domain": "light",
            "service": "light.turn_on",
            "source": "user"
        }),
        json!({
            "when": "2026-09-22T07:02:00.000000+00:00",
            "name": "Living room",
            "entity_id": "light.living_room",
            "state": "off",
            "message": "turned off",
            "domain": "light",
            "service": "light.turn_off",
            "source": "automation"
        }),
        json!({
            "when": "2026-09-22T06:31:00.000000+00:00",
            "name": "Bedroom",
            "entity_id": "light.bedroom",
            "state": "off",
            "message": "turned off",
            "domain": "light",
            "source": "device"
        }),
        json!({
            "when": "2026-09-22T06:00:00.000000+00:00",
            "name": "Outside temperature",
            "entity_id": "sensor.outside_temperature",
            "state": "12.4",
            "domain": "sensor",
            "source": "device"
        }),
        json!({
            "when": "2026-09-21T21:15:00.000000+00:00",
            "name": "Coffee machine",
            "entity_id": "switch.coffee_machine",
            "state": "on",
            "message": "turned on",
            "domain": "switch",
            "service": "switch.turn_on",
            "source": "user"
        }),
    ]
}

/// `/api/error_log`: mixed levels, a traceback continuation, a noisy entity.
pub fn error_log() -> String {
    let mut lines: Vec<String> = Vec::new();
    lines.push(
        "2026-09-20 07:00:00.000000 INFO (MainThread) [homeassistant.core] Starting Home Assistant"
            .into(),
    );
    for minute in 0..12 {
        lines.push(format!(
            "2026-09-20 07:{minute:02}:00.000000 DEBUG (MainThread) [homeassistant.components.mqtt] heartbeat {minute}"
        ));
    }
    lines.push("2026-09-22 06:10:00.000000 WARNING (SyncWorker_1) [homeassistant.components.sensor] Timeout fetching sensor.outside_temperature data".into());
    lines.push("2026-09-22 06:11:00.000000 ERROR (MainThread) [homeassistant.components.mqtt] Failed to connect to broker".into());
    lines.push("Traceback (most recent call last):".into());
    lines.push("  File \"/usr/src/homeassistant/homeassistant/components/mqtt/__init__.py\", line 42, in setup".into());
    lines.push("ConnectionRefusedError: [Errno 111] Connection refused".into());
    // A line far past the per-line cap, to prove the tail is clipped not dropped.
    lines.push(format!(
        "2026-09-22 06:12:00.000000 ERROR (MainThread) [homeassistant.components.recorder] {}{}",
        "database is locked while writing ",
        "x".repeat(600)
    ));
    lines.push("2026-09-22 07:20:00.000000 ERROR (MainThread) [homeassistant.components.light] Unable to reach light.living_room".into());
    lines.push(
        "2026-09-22 07:21:00.000000 INFO (MainThread) [homeassistant.components.light] Recovered"
            .into(),
    );
    lines.join("\n")
}
