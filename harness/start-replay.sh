#!/usr/bin/env bash
# Start the read-only Home Assistant replay the agents and graders talk to.
# :8126 is the endpoint every prompt names (host.containers.internal:8126);
# :8127 is a second instance for grading so grader requests do not land in a
# running case's access log. Both MUST bind 0.0.0.0: a container reaches the
# host through the podman gateway, not loopback (a whole case was lost to a
# 127.0.0.1 bind once). Idempotent: a port already listening is left alone.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
start() {
  local port=$1 log=$2
  if ss -ltn "sport = :$port" | grep -q LISTEN; then echo "replay :$port already up"; return; fi
  PROXY_HOST=0.0.0.0 PROXY_PORT=$port PROXY_LOG=$log FIXTURE=fixtures/ha-fixture.json \
    nohup python3 ha-replay.py > "tmp/replay-$port.out" 2>&1 &
  sleep 1; ss -ltn "sport = :$port" | grep -q LISTEN && echo "replay :$port started" || { echo "replay :$port FAILED"; exit 1; }
}
mkdir -p tmp
start 8126 /srv/bakeoff/replay-logs/ha-replay-access.log
start 8127 /srv/bakeoff/replay-logs/ha-replay-grade.log
