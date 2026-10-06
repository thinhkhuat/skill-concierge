"""Kept-open connection vs a new connection per call (today's hook), real-size wide + rerank turns on Command Code,
interleaved, with idle gaps like real use. Per-call timeout 15 s so stalls are measured, not hidden. No TypeSafe."""
import http.client, json, os, ssl, sys, time, urllib.request
HOST, PATH = "api.commandcode.ai", "/provider/v1/systemone"
HDR = {"Authorization": "Bearer " + os.environ["CMD_API_KEY"], "Content-Type": "application/json",
       "User-Agent": "skill-concierge"}
WIDE, RERANK = open("wide.json", "rb").read(), open("rerank.json", "rb").read()
CTX = ssl.create_default_context()

def fresh(body):
    t = time.time()
    r = urllib.request.urlopen(urllib.request.Request(f"https://{HOST}{PATH}", body, HDR), timeout=15)
    out = json.loads(r.read()); assert out["model"] == "typesafe/jev"
    return time.time() - t

conn = [None]
def kept(body):
    t = time.time()
    for attempt in (1, 2):                      # a pooled client re-opens once if the server closed the idle socket
        try:
            if conn[0] is None:
                conn[0] = http.client.HTTPSConnection(HOST, timeout=15, context=CTX); conn[0].connect()
            conn[0].request("POST", PATH, body, HDR)
            r = conn[0].getresponse(); out = json.loads(r.read()); assert out["model"] == "typesafe/jev"
            return time.time() - t
        except (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError, http.client.CannotSendRequest):
            conn[0].close(); conn[0] = None
            if attempt == 2: raise

def turn(fn):
    try:
        w = fn(WIDE); r = fn(RERANK); return f"wide {w:.2f} + rerank {r:.2f} = {w + r:.2f}s"
    except Exception as e:
        return f"FAIL {type(e).__name__}: {str(e)[:80]}"

kept(RERANK)                                     # warm the kept connection once, as a relay would at start-up
gaps = [3, 8, 3, 15, 3, 8, 3, 30]
for i, gap in enumerate(gaps):
    order = (("fresh", fresh), ("kept", kept)) if i % 2 == 0 else (("kept", kept), ("fresh", fresh))
    for name, fn in order:
        print(f"round{i} {name:5}: {turn(fn)}", flush=True)
    print(f"  (idle {gap}s)", flush=True); time.sleep(gap)
