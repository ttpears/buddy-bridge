import importlib

from importlib.resources import files


def test_package_imports_and_has_version():
    pkg = importlib.import_module("buddybridge")
    assert hasattr(pkg, "__version__")
    assert isinstance(pkg.__version__, str)


def test_hub_module_exposes_main():
    hub = importlib.import_module("buddybridge.hub")
    assert callable(hub.main)
    assert callable(getattr(hub, "make_handler"))
