"""API tests never bootstrap the operator's database or background runtime readers."""
import os
import tempfile

_test_database = tempfile.TemporaryDirectory(prefix="control-center-tests-")
os.environ["CONTROL_CENTER_DB"] = os.path.join(_test_database.name, "bootstrap.db")
os.environ["CONTROL_CENTER_BACKGROUND_ENABLED"] = "0"
