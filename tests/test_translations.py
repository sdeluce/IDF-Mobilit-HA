"""Translation files stay in sync with strings.json."""

import json
from pathlib import Path

import pytest

BASE = Path(__file__).parent.parent / "custom_components" / "idfm_departure"


def _keys(node, prefix=""):
    out = set()
    for k, v in node.items():
        p = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out |= _keys(v, p)
        else:
            out.add(p)
    return out


def _load(path):
    return json.loads((BASE / path).read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", ["translations/en.json", "translations/fr.json"])
def test_keys_match_strings(path):
    assert _keys(_load(path)) == _keys(_load("strings.json"))


def test_en_is_copy_of_strings():
    assert _load("translations/en.json") == _load("strings.json")


def test_fr_differs_from_en():
    assert _load("translations/fr.json") != _load("translations/en.json")


@pytest.mark.parametrize("path", ["strings.json", "translations/fr.json"])
def test_required_keys(path):
    keys = _keys(_load(path))
    required = {f"entity.sensor.{k}.name" for k in
                ("leave_at", "minutes_until_leave", "departure_at_stop", "line", "walk_time")}
    required |= {
        "entity.binary_sensor.time_to_leave.name",
        "services.refresh.name",
        "services.refresh.description",
        "services.refresh.fields.entry_id.name",
        "config.error.invalid_auth",
        "config.error.cannot_connect",
        "config.error.no_home",
        "config.error.no_results",
        "config.abort.already_configured",
        "config.abort.reauth_successful",
    }
    assert required <= keys
    assert any(k.startswith("options.step.init.") for k in keys)


def test_services_yaml_field_matches():
    yaml = BASE / "services.yaml"
    if not yaml.exists():
        pytest.skip("services.yaml owned by B, not present yet")
    assert "entry_id" in yaml.read_text(encoding="utf-8")
