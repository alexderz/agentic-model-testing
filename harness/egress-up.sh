#!/usr/bin/env bash
# Bring up the isolated egress rig for agent runs.
#
#   agent container  ->  bakeoff-internal (no route out at all)
#                        |
#                        +-- egress container, on BOTH networks:
#                              :8888  allowlisting HTTP/CONNECT proxy (public internet only)
#                              :18080 forwarder -> titan llama-swap  (inference)
#                              :18126 forwarder -> pluto HA replay   (fixture)
#
# The two forwarders exist because the agent must reach exactly those two
# services and nothing else on the LAN or the mesh. They are point-to-point,
# so no LAN discovery is possible through them.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TITAN="${TITAN_LAN:-192.0.2.62}"
LOGDIR="${EGRESS_LOGDIR:-$HERE/egress-logs}"
mkdir -p "$LOGDIR"

podman rm -f bakeoff-egress >/dev/null 2>&1 || true
podman network exists bakeoff-internal || \
  podman network create --internal bakeoff-internal >/dev/null
podman network exists bakeoff-out || podman network create bakeoff-out >/dev/null

podman run -d --name bakeoff-egress \
  --network bakeoff-internal \
  --userns=keep-id \
  --add-host=host.containers.internal:host-gateway \
  -v "$HERE/egress-proxy.py":/egress-proxy.py:ro,Z \
  -v "$LOGDIR":/egress-logs:Z \
  localhost/bakeoff-agent bash -c "
    export EGRESS_LOG=/egress-logs/egress.jsonl
    python3 /egress-proxy.py 8888 &
    # point-to-point forwarders; no name resolution, no discovery
    python3 -c \"
import socket,threading,sys
def fwd(lp,rh,rp):
    s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    s.bind(('0.0.0.0',lp)); s.listen(64)
    def one(c):
        try:
            u=socket.create_connection((rh,rp),timeout=20)
        except OSError:
            c.close(); return
        def p(a,b):
            try:
                while True:
                    d=a.recv(65536)
                    if not d: break
                    b.sendall(d)
            except OSError: pass
            finally:
                for x in (a,b):
                    try: x.close()
                    except OSError: pass
        threading.Thread(target=p,args=(c,u),daemon=True).start()
        threading.Thread(target=p,args=(u,c),daemon=True).start()
    while True:
        c,_=s.accept(); threading.Thread(target=one,args=(c,),daemon=True).start()
threading.Thread(target=fwd,args=(18080,'$TITAN',8080),daemon=True).start()
threading.Thread(target=fwd,args=(18126,'host.containers.internal',8126),daemon=True).start()
import time
while True: time.sleep(3600)
\" &
    wait" >/dev/null

podman network connect bakeoff-out bakeoff-egress
sleep 3
echo "egress up: $(podman ps --filter name=bakeoff-egress --format '{{.Status}}')"
echo "logs: $LOGDIR/egress.jsonl"
