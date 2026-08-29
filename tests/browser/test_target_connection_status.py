from __future__ import annotations

import base64
import json
from pathlib import Path
import re
import subprocess


def _run_node(source: str, expression: str) -> object:
    encoded = base64.b64encode(source.encode()).decode("ascii")
    program = f'''
const mod = await import("data:text/javascript;base64,{encoded}");
const result = await ({expression});
console.log(JSON.stringify(result));
'''
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", program],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_connect_device_preserves_structured_target_failure_state() -> None:
    source = Path("frontend/js/api.js").read_text(encoding="utf-8")
    harness = r'''
globalThis.fetch = async () => ({
  ok: false,
  status: 502,
  statusText: "Bad Gateway",
  headers: { get: () => "application/json" },
  json: async () => ({
    state: "TARGET_UNAVAILABLE",
    message: "Target could not be qualified.",
    detail: "A: TRANSPORT: [Errno -2] Name or service not known",
  }),
  text: async () => JSON.stringify({
    state: "TARGET_UNAVAILABLE",
    message: "Target could not be qualified.",
    detail: "A: TRANSPORT: [Errno -2] Name or service not known",
  }),
});
'''
    result = _run_node(
        harness + source,
        r'''(async () => {
          try {
            await mod.connectDevice("emonio-missing");
            return {threw:false};
          } catch (error) {
            return {
              threw:true,
              state:error.targetState ?? null,
              detail:error.targetDetail ?? null,
              message:error.message,
              status:error.httpStatus ?? null,
            };
          }
        })()''',
    )
    assert result == {
        "threw": True,
        "state": "TARGET_UNAVAILABLE",
        "detail": "A: TRANSPORT: [Errno -2] Name or service not known",
        "message": "Target could not be qualified.",
        "status": 502,
    }


def test_failed_target_attempt_keeps_active_device_and_hides_transport_exception() -> None:
    source = Path("frontend/js/app.js").read_text(encoding="utf-8")
    source = re.sub(r'import[\s\S]*?from "\./[^\"]+";\n', "", source)
    source = source[: source.index("main().catch")]
    source = source.replace(
        "function initializeTargetControls()",
        "export function initializeTargetControls()",
    )
    source = source.replace(
        "let selectedDevice = null;",
        "let selectedDevice = null;\n"
        "export function __setSelectedDeviceForTest(value) { selectedDevice = value; }\n"
        "export function __getSelectedDeviceForTest() { return selectedDevice; }",
    )

    harness = r'''
class RecordingState {
  forDevice() { return null; }
  activeRecordings() { return []; }
  isActive() { return false; }
}
const connectDevice = async () => {
  const error = new Error("Target could not be qualified.");
  error.targetState = "TARGET_UNAVAILABLE";
  error.targetDetail = "A: TRANSPORT: [Errno -2] Name or service not known";
  error.httpStatus = 502;
  throw error;
};
const nodes = new Map();
function nodeFor(id) {
  if (!nodes.has(id)) nodes.set(id, {
    id,
    textContent: "",
    value: "",
    disabled: false,
    listeners: {},
    classList: { toggle(){}, add(){}, remove(){} },
    addEventListener(type, fn) { this.listeners[type] = fn; },
  });
  return nodes.get(id);
}
globalThis.document = { getElementById: nodeFor };
'''
    result = _run_node(
        harness + source,
        r'''(async () => {
          mod.__setSelectedDeviceForTest("emonio-active");
          const input = document.getElementById("device-target");
          input.value = "emonio-missing";
          mod.initializeTargetControls();
          await document.getElementById("device-connect").listeners.click();
          return {
            selected: mod.__getSelectedDeviceForTest(),
            status: document.getElementById("target-status").textContent,
            disabled: document.getElementById("device-connect").disabled,
          };
        })()''',
    )
    assert result == {
        "selected": "emonio-active",
        "status": "TARGET UNAVAILABLE",
        "disabled": False,
    }
