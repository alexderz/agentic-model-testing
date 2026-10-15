//! The stdio transport: lines in, lines out, no framing beyond the newline.
//!
//! Three roles cooperate:
//!
//! * the reader (the calling thread) turns stdin lines into requests,
//! * a small pool of workers runs the tools, so one slow Home Assistant call
//!   cannot stop the server from answering `ping`,
//! * one writer thread owns stdout, so two responses can never interleave.
//!
//! stdout carries nothing but JSON-RPC messages; all diagnostics go to stderr.

use std::collections::{HashSet, VecDeque};
use std::io::{self, BufRead, BufReader, Write};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::{Arc, Condvar, Mutex, PoisonError};

use crate::config::Config;
use crate::ha::HaClient;
use crate::mcp::jsonrpc::{error_line, parse_line, Id, Incoming, ProtoError};
use crate::mcp::session::Session;
use crate::mcp::tools;
use crate::StartupError;

/// Longest single request line accepted, as a guard against runaway clients.
const MAX_REQUEST_BYTES: usize = 8 * 1024 * 1024;

/// Concurrent tool executions. Home Assistant answers requests serially anyway;
/// extra workers only help when one call is slow.
const WORKERS: usize = 4;

/// Requests accepted while workers are busy. Past this the reader blocks, which
/// is the honest way to apply back pressure.
const QUEUE_CAPACITY: usize = 32;

/// How many cancelled request ids are remembered.
const CANCEL_HISTORY: usize = 512;

/// Runs the server until stdin reaches end of file.
pub fn serve(config: Config, client: HaClient) -> Result<(), StartupError> {
    // A panic must not end the process silently: it is logged, and for a request
    // it is answered as an internal error by `Session::handle`.
    std::panic::set_hook(Box::new(|info| {
        crate::error!("panic: {info}");
    }));

    crate::info!(
        "serving {} tools for {} over stdio ({WORKERS} workers, page size {})",
        tools::registry().len(),
        config.base_url,
        config.tool_page_size
    );

    let session = Arc::new(Session::new(config, client));
    let cancelled = Arc::new(Cancellations::default());
    let queue = Queue::new(QUEUE_CAPACITY);
    let (tx, rx) = channel::<String>();

    let writer = std::thread::spawn(move || write_loop(rx));
    let mut workers = Vec::new();
    for index in 0..WORKERS {
        let session = Arc::clone(&session);
        let queue = Arc::clone(&queue);
        let cancelled = Arc::clone(&cancelled);
        let tx = tx.clone();
        workers.push(std::thread::spawn(move || {
            while let Some(incoming) = queue.pop() {
                work(&session, &cancelled, &tx, incoming, index);
            }
        }));
    }
    // The reader needs a sender for protocol-level errors, but it must let go of
    // it before the stdout thread can see the channel close.
    let reader_tx = tx.clone();
    drop(tx);

    let reader = read_stdin(&cancelled, &queue, &reader_tx);
    drop(reader_tx);

    // EOF or a dead stdout: wake the workers so they drain and exit.
    queue.close();
    for worker in workers {
        if worker.join().is_err() {
            crate::error!("a worker thread panicked; it has been left behind");
        }
    }
    let written = writer
        .join()
        .unwrap_or_else(|_| Err(io::Error::other("the stdout thread panicked")));
    match written {
        Ok(count) => crate::info!("wrote {count} messages; stdin closed"),
        Err(error) => crate::warn!("stdout failed: {error}"),
    }
    reader
}

/// Handles one parsed message: runs it, unless the client cancelled it first.
fn work(
    session: &Session,
    cancelled: &Cancellations,
    tx: &Sender<String>,
    incoming: Incoming,
    index: usize,
) {
    let id = incoming.id.clone();
    crate::debug!("worker {index} starts {} ({id:?})", incoming.method);
    let reply = session.handle(&incoming);

    if let Some(id) = &id {
        if cancelled.is_cancelled(id) {
            crate::info!(
                "discarding the answer to {} ({id:?}): the client cancelled it",
                incoming.method
            );
            return;
        }
    }
    if let Some(line) = reply.line(id.as_ref()) {
        if tx.send(line).is_err() {
            crate::error!(
                "stdout is closed; the answer to {} ({id:?}) was dropped",
                incoming.method
            );
        }
    }
}

/// Reads stdin line by line until EOF, handing each line to [`handle_line`].
fn read_stdin(
    cancelled: &Cancellations,
    queue: &Arc<Queue<Incoming>>,
    tx: &Sender<String>,
) -> Result<(), StartupError> {
    let stdin = io::stdin();
    let mut reader = BufReader::new(stdin.lock());
    let mut bytes: Vec<u8> = Vec::with_capacity(8 * 1024);

    loop {
        bytes.clear();
        match reader.read_until(b'\n', &mut bytes) {
            Ok(0) => return Ok(()), // end of input
            Ok(_) => {}
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => {
                crate::error!("cannot read stdin: {error}");
                return Ok(());
            }
        }
        // Invalid UTF-8 becomes a parse error rather than killing the loop.
        let text = String::from_utf8_lossy(&bytes);
        if !handle_line(&text, cancelled, queue, tx) {
            return Ok(());
        }
    }
}

/// Processes a single message. Returns `false` when the server should stop.
///
/// Split out from [`read_stdin`] so the routing rules can be tested without a
/// client on the other end of a pipe.
fn handle_line(
    text: &str,
    cancelled: &Cancellations,
    queue: &Queue<Incoming>,
    tx: &Sender<String>,
) -> bool {
    let trimmed = text.trim_end_matches(['\n', '\r', ' ', '\t']);
    if trimmed.is_empty() {
        return true; // blank lines between messages are harmless
    }
    if trimmed.len() > MAX_REQUEST_BYTES {
        crate::warn!("refusing a {} byte message", trimmed.len());
        let error = ProtoError::invalid_request(format!(
            "a single message must fit in {MAX_REQUEST_BYTES} bytes; this one is {}",
            trimmed.len()
        ));
        return tx.send(error_line(None, &error)).is_ok();
    }

    match parse_line(trimmed) {
        Ok(incoming) if incoming.is_notification() => {
            note_notification(&incoming, cancelled);
            true
        }
        Ok(incoming) => queue.push(incoming),
        Err((id, error)) => {
            crate::debug!("rejected a message: {}", error.message);
            tx.send(error_line(id.as_ref(), &error)).is_ok()
        }
    }
}

/// Notifications carry no reply; only cancellation has consequences.
fn note_notification(incoming: &Incoming, cancelled: &Cancellations) {
    if incoming.method != "notifications/cancelled" {
        crate::debug!(
            "notification {} from {}",
            incoming.method,
            incoming.meta.client_name()
        );
        return;
    }
    match incoming.params.get("requestId").and_then(Id::parse) {
        Some(id) => {
            crate::info!("client cancelled request {id:?}; its answer will be dropped");
            cancelled.cancel(id);
        }
        None => crate::warn!(
            "received notifications/cancelled without a usable requestId; \
             expected params.requestId to be a string or an integer"
        ),
    }
}

/// The single writer of stdout.
fn write_loop(rx: Receiver<String>) -> io::Result<usize> {
    let stdout = io::stdout();
    let mut handle = stdout.lock();
    let mut written = 0usize;
    while let Ok(line) = rx.recv() {
        handle.write_all(line.as_bytes())?;
        handle.write_all(b"\n")?;
        handle.flush()?;
        written += 1;
    }
    let _ = handle.flush();
    Ok(written)
}

/// Ids the client has cancelled, kept for long enough to discard their answers.
#[derive(Default)]
pub struct Cancellations {
    ids: Mutex<Cancelled>,
}

#[derive(Default)]
struct Cancelled {
    set: HashSet<String>,
    order: VecDeque<String>,
}

impl Cancellations {
    pub fn cancel(&self, id: Id) {
        let key = key(&id);
        let mut state = self.ids.lock().unwrap_or_else(PoisonError::into_inner);
        if state.set.insert(key.clone()) {
            state.order.push_back(key);
        }
        while state.order.len() > CANCEL_HISTORY {
            if let Some(old) = state.order.pop_front() {
                state.set.remove(&old);
            }
        }
    }

    pub fn is_cancelled(&self, id: &Id) -> bool {
        let state = self.ids.lock().unwrap_or_else(PoisonError::into_inner);
        state.set.contains(&key(id))
    }

    pub fn len(&self) -> usize {
        self.ids
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .set
            .len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

/// Textual identity of a request id: JSON-RPC keeps `1` and `"1"` apart, so the
/// key carries the kind as well as the value.
fn key(id: &Id) -> String {
    match id {
        Id::Number(number) => format!("n{number}"),
        Id::Text(text) => format!("s{text}"),
    }
}

/// A bounded, multi-producer, multi-consumer FIFO queue.
///
/// The standard library has channels but no bounded variant, and an unbounded
/// queue would let a fast client grow memory without limit.
pub struct Queue<T> {
    state: Mutex<QueueState<T>>,
    not_empty: Condvar,
    not_full: Condvar,
    capacity: usize,
}

struct QueueState<T> {
    items: VecDeque<T>,
    closed: bool,
}

impl<T> Queue<T> {
    pub fn new(capacity: usize) -> Arc<Queue<T>> {
        Arc::new(Queue {
            state: Mutex::new(QueueState {
                items: VecDeque::with_capacity(capacity),
                closed: false,
            }),
            not_empty: Condvar::new(),
            not_full: Condvar::new(),
            capacity: capacity.max(1),
        })
    }

    /// Hands an item to a worker, waiting for room. `false` means the queue is
    /// closed and the producer should stop.
    pub fn push(&self, item: T) -> bool {
        let mut state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
        while !state.closed && state.items.len() >= self.capacity {
            state = self
                .not_full
                .wait(state)
                .unwrap_or_else(PoisonError::into_inner);
        }
        if state.closed {
            return false;
        }
        state.items.push_back(item);
        drop(state);
        self.not_empty.notify_one();
        true
    }

    /// Takes the next item, waiting for one. `None` means closed and drained.
    pub fn pop(&self) -> Option<T> {
        let mut state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
        loop {
            if let Some(item) = state.items.pop_front() {
                drop(state);
                self.not_full.notify_one();
                return Some(item);
            }
            if state.closed {
                return None;
            }
            state = self
                .not_empty
                .wait(state)
                .unwrap_or_else(PoisonError::into_inner);
        }
    }

    /// Refuses further pushes and wakes every waiting consumer.
    pub fn close(&self) {
        let mut state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
        state.closed = true;
        drop(state);
        self.not_empty.notify_all();
        self.not_full.notify_all();
    }

    pub fn len(&self) -> usize {
        self.state
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .items
            .len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::log::Level;
    use crate::mcp::jsonrpc::code;
    use serde_json::Value;

    /// Reaches the queue's contents without spawning workers, because `pop`
    /// would block once the queue runs dry.
    fn drain(queue: &Queue<Incoming>) -> Vec<Incoming> {
        let mut out = Vec::new();
        while let Some(incoming) = try_pop(queue) {
            out.push(incoming);
        }
        out
    }

    fn try_pop(queue: &Queue<Incoming>) -> Option<Incoming> {
        let mut state = queue.state.lock().unwrap_or_else(PoisonError::into_inner);
        state.items.pop_front()
    }

    /// Everything a test needs to drive one message through the transport.
    type Harness = (
        Session,
        Arc<Cancellations>,
        Arc<Queue<Incoming>>,
        Sender<String>,
        Receiver<String>,
    );

    fn harness() -> Harness {
        let config = Config::from_lookup(|key| match key {
            "HA_URL" => Some("http://localhost:8123".into()),
            "HA_TOKEN" => Some("token".into()),
            "HA_MCP_LOG_LEVEL" => Some("off".into()),
            _ => None,
        })
        .expect("test config");
        let client = HaClient::new(&config);
        let session = Session::new(config, client);
        let cancelled = Arc::new(Cancellations::default());
        let queue = Queue::new(4);
        let (tx, rx) = channel();
        (session, cancelled, queue, tx, rx)
    }

    #[test]
    fn requests_are_queued_for_a_worker_and_notifications_are_not() {
        let (_session, cancelled, queue, tx, rx) = harness();
        assert!(handle_line(
            r#"{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}"#,
            &cancelled,
            &queue,
            &tx
        ));

        let queued = drain(&queue);
        assert_eq!(queued.len(), 1);
        assert_eq!(queued[0].method, "tools/list");
        assert_eq!(queued[0].id, Some(Id::Number(1)));
        assert!(
            rx.try_recv().is_err(),
            "nothing is answered before a worker runs"
        );

        assert!(handle_line(
            r#"{"jsonrpc":"2.0","method":"notifications/initialized"}"#,
            &cancelled,
            &queue,
            &tx
        ));
        assert!(drain(&queue).is_empty(), "a notification is never queued");
        assert!(rx.try_recv().is_err(), "a notification is never answered");
    }

    #[test]
    fn blank_lines_and_carriage_returns_survive_the_reader() {
        let (_session, cancelled, queue, tx, rx) = harness();
        for blank in ["", "   ", "\n", "\r\n", "\t"] {
            assert!(handle_line(blank, &cancelled, &queue, &tx));
        }
        assert!(drain(&queue).is_empty());
        assert!(rx.try_recv().is_err());

        assert!(handle_line(
            &format!("{}\r\n", r#"{"jsonrpc":"2.0","id":2,"method":"ping"}"#),
            &cancelled,
            &queue,
            &tx
        ));
        assert_eq!(drain(&queue).len(), 1, "a CRLF request is still a request");
    }

    #[test]
    fn malformed_messages_are_answered_without_stopping_the_loop() {
        let (_session, cancelled, queue, tx, rx) = harness();
        assert!(handle_line("not json", &cancelled, &queue, &tx));
        assert!(handle_line(
            r#"{"jsonrpc":"2.0","id":3}"#,
            &cancelled,
            &queue,
            &tx
        ));
        assert!(handle_line(r#"[1,2,3]"#, &cancelled, &queue, &tx));
        assert!(drain(&queue).is_empty());

        let codes: Vec<i32> = (0..3)
            .map(|_| read_line(&rx)["error"]["code"].as_i64().unwrap() as i32)
            .collect();
        assert_eq!(
            codes,
            vec![
                code::PARSE_ERROR,
                code::INVALID_REQUEST,
                code::INVALID_REQUEST
            ]
        );
        assert!(
            handle_line(
                r#"{"jsonrpc":"2.0","id":9,"method":"ping"}"#,
                &cancelled,
                &queue,
                &tx
            ),
            "the reader keeps going after bad input"
        );
    }

    #[test]
    fn an_overlong_message_is_refused_by_name() {
        let (_session, cancelled, queue, tx, rx) = harness();
        let blob = "x".repeat(MAX_REQUEST_BYTES);
        let huge =
            format!(r#"{{"jsonrpc":"2.0","id":1,"method":"ping","params":{{"blob":"{blob}"}}}}"#);
        assert!(huge.len() > MAX_REQUEST_BYTES);
        assert!(handle_line(&huge, &cancelled, &queue, &tx));
        let response: Value = serde_json::from_str(&rx.try_recv().expect("an error line")).unwrap();
        assert_eq!(response["error"]["code"], code::INVALID_REQUEST);
        assert!(response["error"]["message"]
            .as_str()
            .unwrap()
            .contains("bytes"));
        assert!(drain(&queue).is_empty());
    }

    #[test]
    fn cancellation_suppresses_the_answer_to_that_request_only() {
        let (session, cancelled, queue, tx, rx) = harness();
        handle_line(
            r#"{"jsonrpc":"2.0","id":11,"method":"tools/list"}"#,
            &cancelled,
            &queue,
            &tx,
        );
        handle_line(
            r#"{"jsonrpc":"2.0","id":12,"method":"ping"}"#,
            &cancelled,
            &queue,
            &tx,
        );
        let queued = drain(&queue);

        handle_line(
            r#"{"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":11}}"#,
            &cancelled,
            &queue,
            &tx,
        );
        assert!(cancelled.is_cancelled(&Id::Number(11)));
        assert!(
            !cancelled.is_cancelled(&Id::Text("11".into())),
            "11 and \"11\" are different ids"
        );
        assert!(!cancelled.is_cancelled(&Id::Number(12)));

        work(&session, &cancelled, &tx, queued[0].clone(), 0);
        assert!(
            rx.try_recv().is_err(),
            "the cancelled request must not be answered"
        );

        work(&session, &cancelled, &tx, queued[1].clone(), 0);
        let answered: Value = serde_json::from_str(&rx.try_recv().expect("an answer")).unwrap();
        assert_eq!(answered["id"], 12);
        assert_eq!(answered["result"]["resultType"], "complete");
    }

    #[test]
    fn a_cancellation_without_a_request_id_is_logged_and_ignored() {
        let (_session, cancelled, queue, tx, _rx) = harness();
        assert!(handle_line(
            r#"{"jsonrpc":"2.0","method":"notifications/cancelled","params":{}}"#,
            &cancelled,
            &queue,
            &tx
        ));
        assert!(cancelled.is_empty());
        assert!(drain(&queue).is_empty());
    }

    #[test]
    fn the_cancelled_list_stays_bounded() {
        let cancelled = Cancellations::default();
        for number in 0..(CANCEL_HISTORY + 100) {
            cancelled.cancel(Id::Number(number as i64));
        }
        assert_eq!(cancelled.len(), CANCEL_HISTORY);
        assert!(
            !cancelled.is_cancelled(&Id::Number(0)),
            "the oldest id is forgotten first"
        );
        assert!(cancelled.is_cancelled(&Id::Number((CANCEL_HISTORY + 99) as i64)));
    }

    #[test]
    fn a_request_named_with_an_unknown_id_kind_is_still_answered() {
        let (session, cancelled, queue, tx, rx) = harness();
        handle_line(
            r#"{"jsonrpc":"2.0","id":"abc","method":"ping"}"#,
            &cancelled,
            &queue,
            &tx,
        );
        let queued = drain(&queue);
        work(&session, &cancelled, &tx, queued[0].clone(), 1);
        let answered: Value = serde_json::from_str(&rx.try_recv().expect("an answer")).unwrap();
        assert_eq!(answered["id"], "abc");
    }

    #[test]
    fn the_queue_is_fifo_and_stops_accepting_work_when_closed() {
        let queue = Queue::new(3);
        assert!(queue.is_empty());
        for value in [1u32, 2, 3] {
            assert!(queue.push(value));
        }
        assert_eq!(queue.len(), 3);
        assert_eq!(queue.pop(), Some(1));
        assert_eq!(queue.pop(), Some(2));

        queue.close();
        assert_eq!(
            queue.pop(),
            Some(3),
            "items already queued are still delivered"
        );
        assert_eq!(queue.pop(), None, "a drained closed queue stays empty");
        assert!(!queue.push(4), "a closed queue refuses work");
    }

    #[test]
    fn a_full_queue_blocks_the_producer_until_a_consumer_reads() {
        let queue = Queue::new(1);
        assert!(queue.push(1));
        let shared = Arc::clone(&queue);
        let handle = std::thread::spawn(move || {
            // Blocks here until the main thread pops something.
            shared.push(2)
        });
        std::thread::sleep(std::time::Duration::from_millis(50));
        assert!(
            !handle.is_finished(),
            "push must block while the queue is full"
        );
        assert_eq!(queue.pop(), Some(1));
        assert!(
            handle.join().expect("producer"),
            "the blocked producer gets through"
        );
    }

    #[test]
    fn closing_wakes_a_waiting_consumer() {
        let queue: Arc<Queue<u32>> = Queue::new(2);
        let shared = Arc::clone(&queue);
        let handle = std::thread::spawn(move || shared.pop());
        std::thread::sleep(std::time::Duration::from_millis(50));
        assert!(!handle.is_finished());
        queue.close();
        assert_eq!(handle.join().expect("consumer"), None);
    }

    #[test]
    fn several_workers_share_one_queue_without_losing_messages() {
        let queue: Arc<Queue<u32>> = Queue::new(8);
        let mut handles = Vec::new();
        for _ in 0..4 {
            let queue = Arc::clone(&queue);
            handles.push(std::thread::spawn(move || {
                let mut seen = Vec::new();
                while let Some(value) = queue.pop() {
                    seen.push(value);
                }
                seen
            }));
        }
        for value in 0..40u32 {
            assert!(queue.push(value));
        }
        queue.close();
        let mut all: Vec<u32> = handles
            .into_iter()
            .flat_map(|handle| handle.join().expect("worker"))
            .collect();
        all.sort_unstable();
        assert_eq!(
            all,
            (0..40).collect::<Vec<u32>>(),
            "every message is delivered exactly once"
        );
    }

    #[test]
    fn a_closed_queue_releases_a_blocked_producer() {
        let queue: Arc<Queue<u32>> = Queue::new(1);
        assert!(queue.push(1));
        let shared = Arc::clone(&queue);
        let handle = std::thread::spawn(move || shared.push(2));
        std::thread::sleep(std::time::Duration::from_millis(50));
        queue.close();
        assert!(
            !handle.join().expect("producer"),
            "a blocked producer learns the queue closed"
        );
    }

    fn read_line(rx: &Receiver<String>) -> Value {
        let line = rx
            .try_recv()
            .expect("a message should be queued for stdout");
        assert_eq!(line.lines().count(), 1, "stdout framing must be one line");
        serde_json::from_str(&line).expect("stdout must carry valid JSON")
    }

    #[test]
    fn log_level_off_does_not_break_message_routing() {
        crate::log::set_level(Level::Off);
        let (session, cancelled, queue, tx, rx) = harness();
        assert!(handle_line(
            r#"{"jsonrpc":"2.0","id":1,"method":"ping"}"#,
            &cancelled,
            &queue,
            &tx
        ));
        let queued = drain(&queue);
        work(&session, &cancelled, &tx, queued[0].clone(), 0);
        assert!(rx.try_recv().is_ok());
        crate::log::set_level(Level::Debug);
    }
}
