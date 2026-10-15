#!/bin/bash
# Kept for old callers: the sandbox is declared in compose.yaml and run by evalbox.py.
exec "$(dirname "$0")/evalbox.py" up "$@"
