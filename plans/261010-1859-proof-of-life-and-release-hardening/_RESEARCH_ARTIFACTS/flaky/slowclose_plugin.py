"""pytest plugin (use: slowclose.sh). Delays the fake provider's socket close by 50 ms after its handler
returns, i.e. makes the scheduling gap the flaky test races against wide and constant. If the cause is that
gap, the test must fail every time with it."""
import time
from socketserver import TCPServer

_orig = TCPServer.shutdown_request


def _slow(self, request):
    time.sleep(0.05)
    return _orig(self, request)


TCPServer.shutdown_request = _slow
