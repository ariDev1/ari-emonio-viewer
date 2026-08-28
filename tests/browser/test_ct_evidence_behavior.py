from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess


def _run_ct_module(program_body: str) -> object:
    api_source = Path("frontend/js/api.js").read_text(encoding="utf-8")
    api_url = "data:text/javascript;base64," + base64.b64encode(api_source.encode()).decode()
    ct_source = Path("frontend/js/ct-evidence.js").read_text(encoding="utf-8")
    ct_source = ct_source.replace('from "./api.js"', f'from "{api_url}"')
    ct_url = "data:text/javascript;base64," + base64.b64encode(ct_source.encode()).decode()
    program = f"""
class ClassList {{
  toggle() {{}}
}}
function node(value = "") {{
  return {{
    textContent: value,
    value,
    disabled: false,
    classList: new ClassList(),
    addEventListener() {{}},
  }};
}}
const nodes = new Map();
for (const id of [
  "ct-evidence-state", "ct-source", "ct-observed", "ct-physical-status",
  "ct-evidence-message", "ct-password", "ct-read"
]) nodes.set(id, node());
const valueNodes = new Map();
for (const key of ["ct_type", "ct_voltage", "ct_range", "ct_invert", "ct_didt"]) valueNodes.set(key, node("—"));
globalThis.document = {{
  getElementById(id) {{ return nodes.get(id); }},
  querySelector(selector) {{
    const match = selector.match(/data-ct-key=\\"([^\\"]+)\\"/);
    return match ? valueNodes.get(match[1]) : null;
  }},
}};
const mod = await import('{ct_url}');
{program_body}
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", program],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_failed_refresh_preserves_last_observed_values_for_same_device() -> None:
    result = _run_ct_module(
        """
mod.renderCtEvidence({
  device_id: "device-a",
  status: "OBSERVED",
  evidence: {
    source: "EMONIO_TELNET_CONF",
    observed_utc: "2026-08-27T20:00:00Z",
    physical_orientation_status: "NOT_VERIFIED",
    values: {ct_type: 0, ct_voltage: 0, ct_range: 3, ct_invert: 7, ct_didt: 0},
  },
});
globalThis.fetch = async () => ({ok: false, status: 502, statusText: "Bad Gateway", text: async () => "CT configuration read failed"});
await mod.refreshCtEvidence("device-a");
console.log(JSON.stringify({
  state: nodes.get("ct-evidence-state").textContent,
  source: nodes.get("ct-source").textContent,
  invert: valueNodes.get("ct_invert").textContent,
  message: nodes.get("ct-evidence-message").textContent,
}));
"""
    )
    assert result == {
        "state": "CT CONFIG: READ ERROR",
        "source": "EMONIO_TELNET_CONF",
        "invert": "7",
        "message": "Evidence refresh failed: 502 CT configuration read failed",
    }


def test_failed_refresh_for_new_device_does_not_show_previous_device_evidence() -> None:
    result = _run_ct_module(
        """
mod.renderCtEvidence({
  device_id: "device-a",
  status: "OBSERVED",
  evidence: {
    source: "EMONIO_TELNET_CONF",
    observed_utc: "2026-08-27T20:00:00Z",
    physical_orientation_status: "NOT_VERIFIED",
    values: {ct_type: 0, ct_voltage: 0, ct_range: 3, ct_invert: 7, ct_didt: 0},
  },
});
globalThis.fetch = async () => ({ok: false, status: 502, statusText: "Bad Gateway", text: async () => "CT configuration read failed"});
await mod.refreshCtEvidence("device-b");
console.log(JSON.stringify({
  state: nodes.get("ct-evidence-state").textContent,
  source: nodes.get("ct-source").textContent,
  invert: valueNodes.get("ct_invert").textContent,
}));
"""
    )
    assert result == {
        "state": "CT CONFIG: READ ERROR",
        "source": "—",
        "invert": "—",
    }
