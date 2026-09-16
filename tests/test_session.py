import json

from hazzel import session


def test_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "session_path", lambda root=None: tmp_path / "s.json")
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]
    assert session.save(messages, "sum", [{"tool": "read_file", "detail": "x", "success": True}], "hello", "hi there")
    loaded = session.load()
    assert loaded is not None
    assert [m["role"] for m in loaded["messages"]] == ["user", "assistant"]
    assert loaded["summary"] == "sum"
    assert loaded["trace"][0]["tool"] == "read_file"
    assert loaded["user_input"] == "hello"
    assert loaded["response"] == "hi there"


def test_system_message_not_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "session_path", lambda root=None: tmp_path / "s.json")
    session.save([{"role": "system", "content": "sys"}, {"role": "user", "content": "a"}])
    assert all(m["role"] != "system" for m in session.load()["messages"])


def test_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "session_path", lambda root=None: tmp_path / "nope.json")
    assert session.load() is None


def test_corrupt_file_returns_none(tmp_path, monkeypatch):
    path = tmp_path / "s.json"
    path.write_text("{not json")
    monkeypatch.setattr(session, "session_path", lambda root=None: path)
    assert session.load() is None


def test_empty_messages_returns_none(tmp_path, monkeypatch):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"messages": []}))
    monkeypatch.setattr(session, "session_path", lambda root=None: path)
    assert session.load() is None


def test_rejects_bad_roles(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "session_path", lambda root=None: tmp_path / "s.json")
    session.save([{"role": "system", "content": "s"}, {"role": "bogus", "content": "x"}, {"role": "user", "content": "ok"}])
    loaded = session.load()
    assert [m["role"] for m in loaded["messages"]] == ["user"]


def test_caps_messages(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "session_path", lambda root=None: tmp_path / "s.json")
    monkeypatch.setattr(session, "MAX_MESSAGES", 3)
    messages = [{"role": "system", "content": "s"}] + [{"role": "user", "content": f"m{i}"} for i in range(10)]
    session.save(messages)
    assert len(session.load()["messages"]) == 3


def test_clear_removes_file(tmp_path, monkeypatch):
    path = tmp_path / "s.json"
    monkeypatch.setattr(session, "session_path", lambda root=None: path)
    session.save([{"role": "system", "content": "s"}, {"role": "user", "content": "a"}])
    assert path.exists()
    session.clear()
    assert not path.exists()
    session.clear()


def test_backup_and_load_backup(tmp_path, monkeypatch):
    main = tmp_path / "s.json"
    prev = tmp_path / "s.prev.json"
    monkeypatch.setattr(session, "session_path", lambda root=None: main)
    monkeypatch.setattr(session, "backup_path", lambda root=None: prev)
    assert session.backup() is False
    assert session.load_backup() is None
    session.save([{"role": "system", "content": "s"}, {"role": "user", "content": "keep me"}])
    assert session.backup() is True
    session.clear()
    assert session.load() is None
    restored = session.load_backup()
    assert [m["content"] for m in restored["messages"]] == ["keep me"]


def test_clear_backup_consumes_archive(tmp_path, monkeypatch):
    main = tmp_path / "s.json"
    prev = tmp_path / "s.prev.json"
    monkeypatch.setattr(session, "session_path", lambda root=None: main)
    monkeypatch.setattr(session, "backup_path", lambda root=None: prev)
    session.save([{"role": "system", "content": "s"}, {"role": "user", "content": "keep me"}])
    assert session.backup() is True
    session.clear_backup()
    assert session.load_backup() is None
    assert session.load() is not None
    session.clear_backup()


def test_backup_path_sits_beside_session(tmp_path):
    main = session.session_path(tmp_path / "proj")
    prev = session.backup_path(tmp_path / "proj")
    assert prev.parent == main.parent
    assert prev != main


def test_per_project_paths_differ(tmp_path):
    a = session.session_path(tmp_path / "proj-a")
    b = session.session_path(tmp_path / "proj-b")
    assert a != b
    assert a.parent == b.parent
