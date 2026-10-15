"""Test 8, agent side: http://127.0.0.1:8000/ inside the agent's container, carried to the preview server in the
browser's container through /sock/preview.sock (the browser container has no network). The agent can curl the
preview, and the port is taken, so a server the agent starts itself cannot shadow the preview.
  python3 -I preview-bridge.py /sock/preview.sock [port]
"""
import socket
import sys
import threading

SOCK = sys.argv[1]
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8000


def pipe(a, b):
    try:
        while True:
            d = a.recv(65536)
            if not d:
                break
            b.sendall(d)
    except OSError:
        pass
    finally:
        try:
            b.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def serve(c):
    u = socket.socket(socket.AF_UNIX)
    try:
        u.connect(SOCK)
    except OSError:
        c.close()
        u.close()
        return
    t = threading.Thread(target=pipe, args=(u, c), daemon=True)
    t.start()
    pipe(c, u)
    t.join()
    c.close()
    u.close()


ls = socket.socket()
ls.bind(("127.0.0.1", PORT))
ls.listen(64)
while True:
    conn, _ = ls.accept()
    threading.Thread(target=serve, args=(conn,), daemon=True).start()
