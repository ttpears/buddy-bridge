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
