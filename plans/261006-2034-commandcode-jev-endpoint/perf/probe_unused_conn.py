"""How long does Command Code keep a connection that was opened (TCP + TLS) but never used? Opens 6 connections at
once, then sends one tiny request on each after 5/15/30/60/90/120 s and reports whether it was still open."""
import http.client, json, os, ssl, time
HOST, PATH = "api.commandcode.ai", "/provider/v1/systemone"
HDR = {"Authorization": "Bearer " + os.environ["CMD_API_KEY"], "Content-Type": "application/json", "User-Agent": "jevd-probe"}
BODY = json.dumps({"model": "typesafe/jev", "state": "Payments failed for three days.",
                   "questions": {"urgent": {"type": "noul", "instructions": "Does this need urgent attention?"}}}).encode()
ctx = ssl.create_default_context()
conns = []
for _ in range(6):
    c = http.client.HTTPSConnection(HOST, timeout=10, context=ctx); c.connect(); conns.append(c)
t0 = time.time()
for wait, c in zip((5, 15, 30, 60, 90, 120), conns):
    time.sleep(max(0, t0 + wait - time.time()))
    s = time.time()
    try:
        c.request("POST", PATH, BODY, HDR); r = c.getresponse(); r.read()
        print(f"unused for {wait:3d}s: still open, answered {r.status} in {time.time() - s:.2f}s", flush=True)
    except Exception as e:
        print(f"unused for {wait:3d}s: CLOSED by server ({type(e).__name__}) after {time.time() - s:.2f}s", flush=True)
