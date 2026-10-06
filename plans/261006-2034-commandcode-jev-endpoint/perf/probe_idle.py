"""How long may a kept Command Code connection sit idle and still serve a fast turn? One kept connection; after each
idle gap, one real-size turn. Records whether the socket was dropped (re-open needed) and the turn time. No TypeSafe."""
import http.client, json, os, ssl, time
HOST, PATH = "api.commandcode.ai", "/provider/v1/systemone"
HDR = {"Authorization": "Bearer " + os.environ["CMD_API_KEY"], "Content-Type": "application/json", "User-Agent": "skill-concierge"}
WIDE, RERANK = open("wide.json", "rb").read(), open("rerank.json", "rb").read()
conn = http.client.HTTPSConnection(HOST, timeout=15, context=ssl.create_default_context()); conn.connect()
def call(body):
    global conn
    reopened = False
    for attempt in (1, 2):
        try:
            t = time.time(); conn.request("POST", PATH, body, HDR); out = json.loads(conn.getresponse().read())
            assert out["model"] == "typesafe/jev"; return time.time() - t, reopened
        except (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError, http.client.CannotSendRequest, ssl.SSLError):
            conn.close(); conn = http.client.HTTPSConnection(HOST, timeout=15, context=ssl.create_default_context()); conn.connect(); reopened = True
w, _ = call(WIDE); print(f"warm-up wide {w:.2f}s", flush=True)
for gap in (60, 120, 240):
    time.sleep(gap)
    w, ro1 = call(WIDE); r, ro2 = call(RERANK)
    print(f"after idle {gap:3d}s: wide {w:.2f} + rerank {r:.2f} = {w + r:.2f}s  socket dropped by server: {ro1 or ro2}", flush=True)
