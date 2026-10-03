"""The core's UsageEvent must stay identical to the accounting service's."""
import importlib.util
import pathlib

import pytest

from app.accounting import events as core

SERVICE_EVENTS = pathlib.Path(__file__).resolve().parents[2] / "accounting-service" / "app" / "models" / "events.py"

pytestmark = pytest.mark.skipif(not SERVICE_EVENTS.exists(), reason="accounting-service not mounted (e.g. in Docker)")


def _service():
    spec = importlib.util.spec_from_file_location("service_events", SERVICE_EVENTS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_models_do_not_drift():
    svc = _service()
    for name in ("UsageEvent", "Rates"):
        assert getattr(core, name).model_json_schema() == getattr(svc, name).model_json_schema(), name
    for name in ("CallKind", "Outcome", "Source"):
        assert [m.value for m in getattr(core, name)] == [m.value for m in getattr(svc, name)], name
