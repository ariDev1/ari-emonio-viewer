from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess


def _run_modbus_module(program_body: str) -> object:
    api_source = Path("frontend/js/api.js").read_text(encoding="utf-8")
    api_url = "data:text/javascript;base64," + base64.b64encode(api_source.encode()).decode()
    source = Path("frontend/js/modbus-evidence.js").read_text(encoding="utf-8")
    source = source.replace('from "./api.js"', f'from "{api_url}"')
    module_url = "data:text/javascript;base64," + base64.b64encode(source.encode()).decode()
    program = f'''
class ClassList {{ toggle() {{}} }}
function node(value = "") {{
  return {{textContent:value, value, disabled:false, classList:new ClassList(), addEventListener(){{}}, replaceChildren(){{this.children=[];}}, appendChild(child){{this.children.push(child);}}, children:[]}};
}}
const nodes = new Map();
for (const id of [
  "modbus-evidence-state", "modbus-evidence-message", "modbus-evidence-source", "modbus-evidence-observed",
  "modbus-error-raw", "modbus-warning-raw", "modbus-error-flags", "modbus-warning-flags",
  "modbus-evidence-read", "modbus-evidence-probe-grid"
]) nodes.set(id, node());
const energy = new Map();
for (const phase of ["A","B","C","TOTAL"]) for (const field of ["kwh_in","kwh_out"]) energy.set(`${{phase}}:${{field}}`, node("—"));
const connected = new Map();
for (const phase of ["A","B","C"]) connected.set(phase, node("—"));
globalThis.document = {{
  getElementById(id) {{ return nodes.get(id); }},
  createElement() {{ return node(); }},
  querySelector(selector) {{
    let match = selector.match(/data-modbus-energy-phase="([^"]+)".*data-modbus-energy-field="([^"]+)"/);
    if (match) return energy.get(`${{match[1]}}:${{match[2]}}`);
    match = selector.match(/data-modbus-connected-phase="([^"]+)"/);
    return match ? connected.get(match[1]) : null;
  }},
}};
const mod = await import('{module_url}');
{program_body}
'''
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", program],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_partial_observation_keeps_successful_values_and_renders_failed_probe_detail() -> None:
    result = _run_modbus_module(r'''
mod.renderModbusEvidence({
  device_id:"device-a",
  status:"PARTIAL",
  evidence:{
    source:"EMONIO_MODBUS_TCP_DEVICE_EVIDENCE",
    observed_utc:"2026-08-28T19:00:00+00:00",
    read_status:"PARTIAL",
    values:{
      energy:{A:{kwh_in:1.5,kwh_out:0.25},B:null,C:{kwh_in:3.5,kwh_out:0.75},TOTAL:{kwh_in:5,kwh_out:1}},
      connected:{A:true,B:false,C:true},
      error_raw:0, warning_raw:0, error_flags:[], warning_flags:[],
      read_diagnostics:[
        {key:"ENERGY_A",function_code:3,address:40,count:4,status:"OK",elapsed_ms:1.2,error_type:null,error_detail:null},
        {key:"ENERGY_B",function_code:3,address:140,count:4,status:"ERROR",elapsed_ms:8.1,error_type:"ModbusExceptionResponse",error_detail:"exception code 2"}
      ]
    }
  }
});
console.log(JSON.stringify({
  state:nodes.get("modbus-evidence-state").textContent,
  aIn:energy.get("A:kwh_in").textContent,
  bIn:energy.get("B:kwh_in").textContent,
  errorFlags:nodes.get("modbus-error-flags").textContent,
  probeRows:nodes.get("modbus-evidence-probe-grid").children.map((row) => row.children.map((cell) => cell.textContent).join("|"))
}));
''')
    assert result["state"] == "MODBUS EVIDENCE: PARTIAL"
    assert result["aIn"] == "1.5"
    assert result["bIn"] == "—"
    assert result["errorFlags"] == "NONE"
    assert any(
        "ENERGY_B" in row
        and "FC03" in row
        and "140" in row
        and "exception code 2" in row
        for row in result["probeRows"]
    )


def test_transport_abort_renders_failed_and_skipped_probes_as_distinct_states() -> None:
    result = _run_modbus_module(r'''
mod.renderModbusEvidence({
  device_id:"device-a",
  status:"PARTIAL",
  evidence:{
    source:"EMONIO_MODBUS_TCP_DEVICE_EVIDENCE",
    observed_utc:"2026-08-28T20:00:00+00:00",
    read_status:"PARTIAL",
    values:{
      energy:{A:{kwh_in:1.5,kwh_out:0.25},B:null,C:null,TOTAL:null},
      connected:{A:null,B:null,C:null},
      error_raw:null, warning_raw:null, error_flags:null, warning_flags:null,
      read_diagnostics:[
        {key:"ENERGY_A",function_code:3,address:40,count:4,status:"OK",elapsed_ms:1.2,error_type:null,error_detail:null},
        {key:"ENERGY_B",function_code:3,address:140,count:4,status:"ERROR",elapsed_ms:8.1,error_type:"ConnectionResetError",error_detail:"Connection reset by peer"},
        {key:"ENERGY_C",function_code:3,address:240,count:4,status:"SKIPPED",elapsed_ms:0,error_type:"EvidenceSequenceAborted",error_detail:"not attempted after transport failure in ENERGY_B"}
      ]
    }
  }
});
console.log(JSON.stringify({
  state:nodes.get("modbus-evidence-state").textContent,
  message:nodes.get("modbus-evidence-message").textContent,
  probeRows:nodes.get("modbus-evidence-probe-grid").children.map((row) => row.children.map((cell) => cell.textContent).join("|"))
}));
''')
    assert result["state"] == "MODBUS EVIDENCE: PARTIAL"
    assert result["message"] == "1 failed · 1 skipped · 1 OK. Review probe diagnostics."
    assert any("ENERGY_B" in row and "|ERROR|" in row for row in result["probeRows"])
    assert any("ENERGY_C" in row and "|SKIPPED|" in row for row in result["probeRows"])
