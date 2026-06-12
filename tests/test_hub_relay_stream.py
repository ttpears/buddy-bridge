from buddybridge import hub as hubmod


def _hub():
    return hubmod.Hub(hubmod.MockTransport())


def test_button_resolves_specific_id():
    h = _hub()
    pid = h.register_permission("box", "s1", "Bash", "ls")
    # a second, newer prompt becomes "current"; id routing must still hit pid
    h.register_permission("box", "s2", "Edit", "f.py")
    h.build_heartbeat()  # sets current = first pending (FIFO)
    decided = {}

    def waiter():
        decided["d"] = h.await_decision(pid, timeout=2)

    import threading
    t = threading.Thread(target=waiter); t.start()
    assert hubmod.resolve_button(h, {"id": pid, "decision": "deny"}) is True
    t.join(3)
    assert decided["d"] == "deny"


def test_button_without_id_uses_current():
    h = _hub()
    pid = h.register_permission("box", "s1", "Bash", "ls")
    h.build_heartbeat()
    assert hubmod.resolve_button(h, {"decision": "once"}) is True
    assert h.by_id[pid].decision == "once"


def test_transport_attach_primes_and_send_enqueues():
    t = hubmod.HttpRelayTransport(owner="me")
    h = hubmod.Hub(t)            # Hub.__init__ sets transport.hub = self
    c = t.attach()
    # priming frames: time, owner, an initial heartbeat
    kinds = [c.get(timeout=1) for _ in range(3)]
    assert any("time" in f for f in kinds)
    assert any(f.get("cmd") == "owner" and f.get("name") == "me" for f in kinds)
    # a state change pushes a fresh heartbeat to the client
    h.event("box", "s1", "running", msg="building")
    t.send(h.build_heartbeat())
    assert c.get(timeout=1)["running"] == 1


def test_transport_attach_displaces_old_client():
    t = hubmod.HttpRelayTransport()
    hubmod.Hub(t)
    c1 = t.attach()
    c2 = t.attach()                 # newer relay takes over
    assert c1.closed is True
    for _ in range(3):
        c2.get(timeout=1)           # drain priming frames (time, owner, heartbeat)
    t.send({"total": 0, "running": 0, "waiting": 0, "tokens": 0, "entries": []})
    # closed client never receives further frames; current one does
    assert c2.get(timeout=1)["total"] == 0


def test_transport_send_dedups_until_floor():
    t = hubmod.HttpRelayTransport()
    hubmod.Hub(t)
    c = t.attach()
    for _ in range(3):
        c.get(timeout=1)            # drain priming frames
    hb = {"total": 1, "running": 0, "waiting": 0, "tokens": 5, "entries": []}
    t.send(hb)
    assert c.get(timeout=1)["tokens"] == 5
    t.send(dict(hb))                # identical -> deduped, nothing enqueued
    assert c.empty()


import json
import threading
import urllib.request
import urllib.error

from http.server import ThreadingHTTPServer


def _serve(token=""):
    t = hubmod.HttpRelayTransport(owner="me")
    h = hubmod.Hub(t)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), hubmod.make_handler(h, token))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=h.run, daemon=True).start()
    return h, srv, srv.server_address[1]


def test_relay_stream_delivers_frames_and_button_resolves():
    h, srv, port = _serve()
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/relay/stream", timeout=3)
        first = json.loads(resp.readline())          # primed "time" frame
        assert "time" in first
        # raise a prompt; a heartbeat with the prompt should stream out
        pid = h.register_permission("box", "s1", "Bash", "ls -la")
        prompt = None
        for _ in range(20):
            obj = json.loads(resp.readline())
            if obj.get("prompt"):
                prompt = obj["prompt"]; break
        assert prompt and prompt["id"] == pid
        # approve via /button
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/button",
            data=json.dumps({"id": pid, "decision": "once"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        assert json.loads(urllib.request.urlopen(req, timeout=3).read())["ok"] is True
        resp.close()
    finally:
        srv.shutdown()


def test_token_gates_stream_and_reads():
    h, srv, port = _serve(token="secret")
    try:
        for path in ("/relay/stream", "/decision?id=x", "/detail", "/state", "/"):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3)
                assert False, f"{path} should require a token"
            except urllib.error.HTTPError as e:
                assert e.code == 401
        # query-string token is accepted for the stream
        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/relay/stream?token=secret", timeout=3)
        assert "time" in json.loads(resp.readline())
        resp.close()
    finally:
        srv.shutdown()


def test_decision_reachable_with_token_header():
    h, srv, port = _serve(token="secret")
    try:
        # mirrors hook.get(): X-Buddy-Token header on a GET /decision long-poll.
        # unknown id returns immediately with "timeout" (not 401).
        req = urllib.request.Request(f"http://127.0.0.1:{port}/decision?id=nope&wait=0",
                                     headers={"X-Buddy-Token": "secret"}, method="GET")
        body = json.loads(urllib.request.urlopen(req, timeout=3).read())
        assert body["decision"] == "timeout"
    finally:
        srv.shutdown()
