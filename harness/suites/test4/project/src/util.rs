//! Small helpers shared by the Home Assistant client and the MCP layer.

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine as _;
use serde_json::Value;

/// Percent-encodes a string so it is safe inside a URL path segment or query
/// value. Only RFC 3986 *unreserved* characters survive, which means a value
/// can never escape the path segment it is placed in (no `/`, `?`, `#`, `%`).
pub fn percent_encode(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    for byte in value.as_bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(*byte as char)
            }
            _ => out.push_str(&format!("%{byte:02X}")),
        }
    }
    out
}

/// Truncates to at most `max_chars` characters on a UTF-8 boundary.
///
/// Returns the (possibly shortened) slice and whether truncation happened.
pub fn truncate_chars(text: &str, max_chars: usize) -> (&str, bool) {
    if text.chars().count() <= max_chars {
        return (text, false);
    }
    let end = text
        .char_indices()
        .nth(max_chars)
        .map(|(i, _)| i)
        .unwrap_or(text.len());
    (&text[..end], true)
}

/// Collapses runs of whitespace and trims, for one-line error summaries.
pub fn one_line(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Shown when a caller supplies a cursor this server never issued.
pub const INVALID_CURSOR: &str =
    "argument \"cursor\" is not one of the cursors this server returned; \
                                  call the tool again without it to start over";

/// One page of a result set.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Page {
    /// Index of the first item to return.
    pub start: usize,
    /// Cursor for the following page, or `None` at the end of the set.
    pub next: Option<Cursor>,
}

/// Resolves a `cursor` argument against a set of `total` items.
///
/// The error message tells a caller what to do about a cursor it did not
/// produce itself (a stale or hand-written one).
pub fn page(total: usize, cursor: &str, limit: usize) -> Result<Page, String> {
    let start = if cursor.is_empty() {
        0
    } else {
        Cursor::decode(cursor)
            .ok_or_else(|| INVALID_CURSOR.to_string())?
            .0
    };
    // A stale cursor pointing past the end of a shrunk set must not panic.
    let start = start.min(total);
    let end = total.min(start.saturating_add(limit.max(1)));
    let next = if end < total { Some(Cursor(end)) } else { None };
    Ok(Page { start, next })
}

/// Levenshtein distance, used only to suggest corrections for typos.
pub fn edit_distance(wanted: &str, candidate: &str) -> usize {
    let left: Vec<char> = wanted.chars().collect();
    let right: Vec<char> = candidate.chars().collect();
    let mut previous: Vec<usize> = (0..=right.len()).collect();
    let mut current = vec![0usize; right.len() + 1];
    for (i, a) in left.iter().enumerate() {
        current[0] = i + 1;
        for (j, b) in right.iter().enumerate() {
            let substitution = previous[j] + usize::from(a != b);
            current[j + 1] = substitution.min(previous[j + 1] + 1).min(current[j] + 1);
        }
        std::mem::swap(&mut previous, &mut current);
    }
    previous[right.len()]
}

/// Human-readable JSON type name, for error messages.
pub fn json_type(value: &Value) -> &'static str {
    match value {
        Value::Null => "null",
        Value::Bool(_) => "a boolean",
        Value::Number(_) => "a number",
        Value::String(_) => "a string",
        Value::Array(_) => "an array",
        Value::Object(_) => "an object",
    }
}

/// Opaque pagination cursor.
///
/// Clients treat cursors as opaque strings; the offset encoding is an internal
/// detail and may change without notice.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Cursor(pub usize);

impl Cursor {
    pub fn encode(self) -> String {
        URL_SAFE_NO_PAD.encode(self.0.to_string())
    }

    pub fn decode(raw: &str) -> Option<Cursor> {
        let decoded = URL_SAFE_NO_PAD.decode(raw).ok()?;
        let text = String::from_utf8(decoded).ok()?;
        text.trim().parse::<usize>().ok().map(Cursor)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn page_walks_a_set_and_stops_without_a_cursor() {
        let first = page(5, "", 2).expect("first page");
        assert_eq!((first.start, first.next.is_some()), (0, true));
        let token = first.next.expect("more to come").encode();
        let second = page(5, &token, 2).expect("second page");
        assert_eq!((second.start, second.next.is_some()), (2, true));
        let third =
            page(5, &page(5, &token, 2).unwrap().next.unwrap().encode(), 2).expect("third page");
        assert_eq!((third.start, third.next), (4, None));
    }

    #[test]
    fn page_clamps_stale_cursors_and_rejects_forged_ones() {
        let shrunk = page(2, &Cursor(9).encode(), 10).expect("stale cursor is clamped");
        assert_eq!((shrunk.start, shrunk.next), (2, None));
        assert_eq!(page(10, "not-a-cursor", 2), Err(INVALID_CURSOR.to_string()));
        assert_eq!(
            page(0, "", 50).unwrap().start,
            0,
            "an empty set is pageable"
        );
        assert!(page(0, "", 50).unwrap().next.is_none());
    }

    #[test]
    fn edit_distance_ranks_closest_names_first() {
        assert_eq!(edit_distance("light", "light"), 0);
        assert_eq!(edit_distance("entity_id", "entity_ids"), 1);
        assert_eq!(edit_distance("", "abc"), 3);
        assert_eq!(edit_distance("abc", ""), 3);
        assert!(
            edit_distance("ligth", "light") < edit_distance("ligth", "sensor"),
            "a typo must rank closer than an unrelated name"
        );
        assert_ne!(edit_distance("toggle", "turn_on"), 0);
    }

    #[test]
    fn percent_encode_keeps_unreserved_and_escapes_the_rest() {
        assert_eq!(percent_encode("light.living_room-1"), "light.living_room-1");
        assert_eq!(percent_encode("a b"), "a%20b");
    }

    #[test]
    fn percent_encode_neutralises_path_and_query_injection() {
        assert_eq!(
            percent_encode("../../etc/passwd?x=1#y"),
            "..%2F..%2Fetc%2Fpasswd%3Fx%3D1%23y"
        );
        assert_eq!(percent_encode("%41"), "%2541");
    }

    #[test]
    fn truncate_chars_splits_on_char_boundaries() {
        let (kept, cut) = truncate_chars("héllo wörld", 3);
        assert_eq!(kept, "hél");
        assert!(cut);
        let (whole, cut) = truncate_chars("short", 30);
        assert_eq!(whole, "short");
        assert!(!cut);
    }

    #[test]
    fn cursors_round_trip() {
        for offset in [0usize, 1, 49, 12345] {
            let encoded = Cursor(offset).encode();
            assert_eq!(Cursor::decode(&encoded), Some(Cursor(offset)));
        }
    }

    #[test]
    fn cursors_reject_garbage() {
        for raw in ["", "!!!", "not-a-cursor", "###", "%"] {
            assert_eq!(Cursor::decode(raw), None, "accepted {raw:?}");
        }
    }

    #[test]
    fn one_line_collapses_whitespace() {
        assert_eq!(one_line(" a\n b\t c "), "a b c");
    }
}
