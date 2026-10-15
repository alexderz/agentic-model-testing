//! Minimal stderr-only logging.
//!
//! The stdio transport reserves `stdout` for MCP messages, so every diagnostic
//! this server produces goes to `stderr` (which the spec explicitly allows).
//! Nothing here ever touches `stdout`.

use std::fmt::Arguments;
use std::sync::atomic::{AtomicU8, Ordering};

/// Verbosity levels, ordered from quietest to loudest.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
#[repr(u8)]
pub enum Level {
    Off = 0,
    Error = 1,
    Warn = 2,
    Info = 3,
    Debug = 4,
}

impl Level {
    /// Parses a level name from configuration, case-insensitively.
    ///
    /// `None` means the value is not a level name at all; the caller turns that
    /// into a configuration error rather than silently picking a default.
    pub fn parse(value: &str) -> Option<Level> {
        match value.trim().to_ascii_lowercase().as_str() {
            "off" | "none" | "quiet" | "silent" => Some(Level::Off),
            "error" => Some(Level::Error),
            "warn" | "warning" => Some(Level::Warn),
            "info" => Some(Level::Info),
            "debug" | "trace" => Some(Level::Debug),
            _ => None,
        }
    }

    pub const NAMES: &'static [&'static str] = &["off", "error", "warning", "info", "debug"];

    fn enabled(self) -> bool {
        (self as u8) <= ACTIVE.load(Ordering::Relaxed)
    }
}

static ACTIVE: AtomicU8 = AtomicU8::new(Level::Info as u8);

/// Sets the process-wide log level. Called once during startup.
pub fn set_level(level: Level) {
    ACTIVE.store(level as u8, Ordering::Relaxed);
}

pub(crate) fn emit(level: Level, args: Arguments<'_>) {
    if level.enabled() {
        eprintln!("[ha-mcp] {}", args);
    }
}

#[macro_export]
macro_rules! error {
    ($($arg:tt)*) => { $crate::log::emit($crate::log::Level::Error, format_args!($($arg)*)) };
}

#[macro_export]
macro_rules! warn {
    ($($arg:tt)*) => { $crate::log::emit($crate::log::Level::Warn, format_args!($($arg)*)) };
}

#[macro_export]
macro_rules! info {
    ($($arg:tt)*) => { $crate::log::emit($crate::log::Level::Info, format_args!($($arg)*)) };
}

#[macro_export]
macro_rules! debug {
    ($($arg:tt)*) => { $crate::log::emit($crate::log::Level::Debug, format_args!($($arg)*)) };
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_known_level_names() {
        assert_eq!(Level::parse("debug"), Some(Level::Debug));
        assert_eq!(Level::parse(" WARNING "), Some(Level::Warn));
        assert_eq!(Level::parse("Off"), Some(Level::Off));
    }

    #[test]
    fn rejects_unknown_level_names() {
        assert_eq!(Level::parse("shout"), None);
        assert_eq!(Level::parse(""), None);
    }

    #[test]
    fn levels_are_ordered_quietest_first() {
        assert!(Level::Off < Level::Error);
        assert!(Level::Error < Level::Warn);
        assert!(Level::Warn < Level::Info);
        assert!(Level::Info < Level::Debug);
    }

    #[test]
    fn off_silences_every_level_and_warn_silences_debug() {
        set_level(Level::Off);
        assert!(!Level::Error.enabled());
        set_level(Level::Warn);
        assert!(Level::Error.enabled());
        assert!(!Level::Debug.enabled());
        set_level(Level::Debug);
        assert!(Level::Debug.enabled());
        set_level(Level::Info);
    }
}
