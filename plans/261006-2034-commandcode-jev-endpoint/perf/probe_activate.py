"""Does an unbilled request (GET on the API path, no model run) keep a fresh Command Code connection open like a real
request does? Opens 3 connections, sends one GET on each, then a tiny real request after 30/90/180 s."""
import http.client, json, os, ssl, time
HOST, PATH = "api.commandcode.ai", "/provider/v1/systemone"
HDR = {"Authorization": "Bearer " + os.environ["CMD_API_KEY"], "Content-Type": "application/json", "User-Agent": "jevd-probe"}
BODY = json.dumps({"model": "typesafe/jev", "state": "Payments failed for three days.",
                   "questions": {"urgent": {"type": "noul", "instructions": "Does this need urgent attention?"}}}).encode()
ctx = ssl.create_default_context()
conns = []
for i in range(3):
    c = http.client.HTTPSConnection(HOST, timeout=10, context=ctx); c.connect()
    c.request("GET", PATH, headers={"User-Agent": "jevd-probe"}); r = c.getresponse(); body = r.read()
    print(f"conn{i}: GET {PATH} -> {r.status}, Connection: {r.getheader('Connection')}, body {body[:80]!r}", flush=True)
    conns.append(c)
t0 = time.time()
for wait, c in zip((30, 90, 180), conns):
    time.sleep(max(0, t0 + wait - time.time()))
    s = time.time()
    try:
        c.request("POST", PATH, BODY, HDR); r = c.getresponse(); r.read()
        print(f"after GET + {wait:3d}s idle: still open, answered {r.status} in {time.time() - s:.2f}s", flush=True)
    except Exception as e:
        print(f"after GET + {wait:3d}s idle: CLOSED ({type(e).__name__})", flush=True)
