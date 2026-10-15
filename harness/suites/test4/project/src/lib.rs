//! A read-only Model Context Protocol server for the Home Assistant REST API.
//!
//! The crate is split in two halves: [`ha`] talks HTTP to Home Assistant, and
//! [`mcp`] implements the protocol the client speaks. [`run`] wires them to
//! standard input and output.

pub mod config;
pub mod error;
pub mod ha;
pub mod log;
pub mod mcp;
pub mod timestamp;
pub mod transport;
pub mod util;

pub use config::Config;
pub use error::HaError;

/// Why the server could not start at all.
#[derive(Debug)]
pub enum StartupError {
    /// Configuration is missing or unusable.
    Config(config::ConfigError),
}

impl std::fmt::Display for StartupError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            StartupError::Config(error) => write!(f, "{error}"),
        }
    }
}

/// Starts the server on standard input and standard output.
pub fn run() -> Result<(), StartupError> {
    let config = Config::from_env().map_err(StartupError::Config)?;
    log::set_level(config.log_level);
    crate::info!("home-assistant-mcp {} ready", config::SERVER_NAME);
    let client = ha::HaClient::new(&config);
    transport::serve(config, client)
}

#[cfg(test)]
mod tests {
    #[test]
    fn both_halves_are_reachable_from_the_crate_root() {
        assert!(crate::mcp::tools::find("get_entity").is_some());
        assert!(crate::Config::from_lookup(|_| None).is_err());
    }
}
