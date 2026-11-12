from __future__ import annotations

from types import SimpleNamespace

import pytest

from handcontrol.windows import startup


class FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeRegistry:
    HKEY_CURRENT_USER = 1
    KEY_QUERY_VALUE, KEY_SET_VALUE, REG_SZ = 2, 4, 1

    def __init__(self):
        self.exists = False
        self.values = {}
        self.calls = []
        self.failure = None

    def _open(self, root, path, reserved, access):
        assert root == self.HKEY_CURRENT_USER
        assert path == startup.RUN_KEY and reserved == 0
        self.calls.append(access)
        if self.failure:
            raise self.failure
        return FakeKey()

    def OpenKey(self, *args):
        key = self._open(*args)
        if not self.exists:
            raise FileNotFoundError
        return key

    def CreateKeyEx(self, *args):
        key = self._open(*args)
        self.exists = True
        return key

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError
        return self.values[name]

    def SetValueEx(self, key, name, reserved, value_type, value):
        assert reserved == 0
        self.values[name] = (value, value_type)

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError
        del self.values[name]


@pytest.mark.parametrize("frozen", [False, True])
def test_default_command_quotes_unicode_path(monkeypatch, frozen):
    path = r"C:\Users\İbrahim Şen\Holoscobe App\Holoscobe.exe" if frozen else r"C:\Users\İbrahim Şen\Python 3.11\python.exe"
    monkeypatch.setattr(startup, "sys", SimpleNamespace(executable=path, frozen=frozen))
    expected = f'"{path}"' if frozen else '"C:\\Users\\İbrahim Şen\\Python 3.11\\pythonw.exe" -m handcontrol.app'
    assert startup.default_command() == expected
    assert "--live" not in startup.default_command()


def test_startup_enable_read_disable_and_idempotence(monkeypatch):
    registry = FakeRegistry()
    monkeypatch.setattr(startup, "default_command", lambda: '"C:\\Holoscobe App\\Holoscobe.exe"')
    assert not startup.is_enabled(registry=registry)
    assert startup.set_enabled(False, registry=registry)
    assert not registry.exists
    assert startup.set_enabled(True, registry=registry)
    assert registry.values == {"Holoscobe": ('"C:\\Holoscobe App\\Holoscobe.exe"', registry.REG_SZ)}
    assert startup.is_enabled(registry=registry)
    assert startup.set_enabled(True, registry=registry)
    registry.values["OtherApp"] = ("other.exe", registry.REG_SZ)
    assert startup.set_enabled(False, registry=registry)
    assert not startup.is_enabled(registry=registry)
    assert startup.set_enabled(False, registry=registry)
    assert registry.values == {"OtherApp": ("other.exe", registry.REG_SZ)}
    assert set(registry.calls) == {registry.KEY_QUERY_VALUE, registry.KEY_SET_VALUE}


def test_explicit_command_is_preserved():
    registry = FakeRegistry()
    command = '"C:\\Araçlar\\Holoscobe.exe"'
    assert startup.set_enabled(True, command, registry=registry)
    assert registry.values["Holoscobe"] == (command, registry.REG_SZ)


@pytest.mark.parametrize("operation", ["read", "enable", "disable"])
def test_registry_access_failure_returns_false_and_logs(caplog, operation):
    registry = FakeRegistry()
    registry.failure = PermissionError("access denied")
    if operation == "read":
        assert not startup.is_enabled(registry=registry)
    else:
        assert not startup.set_enabled(operation == "enable", registry=registry)
    assert "startup registration" in caplog.text


@pytest.mark.parametrize("value,value_type", [("", 1), ("  ", 1), (42, 1), ("app.exe", 3)])
def test_invalid_registry_values_are_not_enabled(value, value_type):
    registry = FakeRegistry()
    registry.exists = True
    registry.values["Holoscobe"] = (value, value_type)
    assert not startup.is_enabled(registry=registry)


@pytest.mark.parametrize("command", ["", "  ", "bad\x00command", '"app.exe" --live'])
def test_invalid_or_live_command_never_writes(command):
    registry = FakeRegistry()
    assert not startup.set_enabled(True, command, registry=registry)
    assert not registry.exists and not registry.values


@pytest.mark.parametrize("method", ["QueryValueEx", "SetValueEx", "DeleteValue"])
def test_value_operation_failure_is_caught(monkeypatch, method):
    registry = FakeRegistry()
    registry.exists = True
    def broken(*args):
        raise OSError("value operation failed")
    monkeypatch.setattr(registry, method, broken)
    if method == "QueryValueEx":
        assert not startup.is_enabled(registry=registry)
    else:
        assert not startup.set_enabled(method == "SetValueEx", registry=registry)
