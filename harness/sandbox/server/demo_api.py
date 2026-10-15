#!/usr/bin/env python3
"""Default server: a tiny JSON API over Postgres (the db), so the sandbox can be exercised end to
end. Real evals replace it with SERVER_IMAGE / SERVER_CMD (sandbox/up.sh).
  GET /health  GET /items  POST /items {"name": ...}  GET /items/<id>
"""
import http.server, json, os, re, socketserver, time
import psycopg

DSN = os.environ["DATABASE_URL"]


def db():
    for _ in range(60):
        try: return psycopg.connect(DSN, autocommit=True)
        except psycopg.OperationalError: time.sleep(1)
    raise SystemExit("database not reachable")


CONN = db()
CONN.execute("create table if not exists items (id serial primary key, name text not null)")


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def reply(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path == "/health": return self.reply(200, {"ok": True, "db": CONN.execute("select 1").fetchone()[0] == 1})
        if self.path == "/items": return self.reply(200, [{"id": i, "name": n} for i, n in CONN.execute("select id, name from items order by id")])
        m = re.fullmatch(r"/items/(\d+)", self.path)
        if m:
            r = CONN.execute("select id, name from items where id = %s", (int(m[1]),)).fetchone()
            return self.reply(200, {"id": r[0], "name": r[1]}) if r else self.reply(404, {"error": "not found"})
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/items": return self.reply(404, {"error": "not found"})
        try: name = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))["name"]
        except (ValueError, KeyError, TypeError): return self.reply(400, {"error": "body must be {\"name\": ...}"})
        i = CONN.execute("insert into items (name) values (%s) returning id", (name,)).fetchone()[0]
        self.reply(201, {"id": i, "name": name})


class S(socketserver.ThreadingMixIn, http.server.HTTPServer): daemon_threads = True


if __name__ == "__main__":
    S(("0.0.0.0", int(os.environ.get("PORT", "8000"))), H).serve_forever()
