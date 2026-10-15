//! Binary entry point: configure logging, then serve stdio until EOF.

use ha_mcp::StartupError;

fn main() {
    let failure = match ha_mcp::run() {
        Ok(()) => return,
        Err(error) => error,
    };
    match failure {
        StartupError::Config(error) => {
            eprintln!("home-assistant-mcp: cannot start: {error}");
            eprintln!("home-assistant-mcp: set HA_URL and HA_TOKEN, then try again.");
            std::process::exit(2);
        }
    }
}
