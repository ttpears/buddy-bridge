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
