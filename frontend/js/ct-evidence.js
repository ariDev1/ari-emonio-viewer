import { getCtConfiguration, readCtConfiguration } from "./api.js";

const CT_KEYS = ["ct_type", "ct_voltage", "ct_range", "ct_invert", "ct_didt"];
let renderedDeviceId = null;

function valueNode(key) {
  return document.querySelector(`[data-ct-key="${key}"]`);
}

function setState(state, kind = "") {
  const node = document.getElementById("ct-evidence-state");
  node.textContent = `CT CONFIG: ${state}`;
  node.classList.toggle("observed", kind === "observed");
  node.classList.toggle("error", kind === "error");
}

function setMessage(text = "", kind = "") {
  const node = document.getElementById("ct-evidence-message");
  node.textContent = text;
  node.classList.toggle("error", kind === "error");
}

function resetEvidenceDisplay() {
  setState("NOT READ");
  setMessage();
  document.getElementById("ct-source").textContent = "—";
  document.getElementById("ct-observed").textContent = "—";
  document.getElementById("ct-physical-status").textContent = "NOT VERIFIED";
  for (const key of CT_KEYS) valueNode(key).textContent = "—";
}

function selectEvidenceDevice(deviceId) {
  if (renderedDeviceId === deviceId) return;
  resetEvidenceDisplay();
  renderedDeviceId = deviceId;
}

export function clearCtEvidence() {
  renderedDeviceId = null;
  resetEvidenceDisplay();
}

export function renderCtEvidence(payload) {
  const deviceId = payload?.device_id ?? null;
  if (deviceId !== null) selectEvidenceDevice(deviceId);

  if (!payload?.evidence) {
    resetEvidenceDisplay();
    return;
  }

  const evidence = payload.evidence;
  setState(payload.status ?? "OBSERVED", "observed");
  setMessage();
  document.getElementById("ct-source").textContent = evidence.source ?? "—";
  document.getElementById("ct-observed").textContent = evidence.observed_utc ?? "—";
  document.getElementById("ct-physical-status").textContent = evidence.physical_orientation_status ?? "NOT VERIFIED";
  for (const key of CT_KEYS) valueNode(key).textContent = String(evidence.values?.[key] ?? "—");
}

export async function refreshCtEvidence(deviceId) {
  if (!deviceId) {
    clearCtEvidence();
    return;
  }

  selectEvidenceDevice(deviceId);
  try {
    const payload = await getCtConfiguration(deviceId);
    if (renderedDeviceId !== deviceId) return;
    renderCtEvidence(payload);
  } catch (error) {
    if (renderedDeviceId !== deviceId) return;
    setState("READ ERROR", "error");
    setMessage(`Evidence refresh failed: ${error.message}`, "error");
  }
}

export function initializeCtEvidenceControls(getSelectedDevice) {
  const passwordInput = document.getElementById("ct-password");
  const readButton = document.getElementById("ct-read");

  const read = async () => {
    const deviceId = getSelectedDevice();
    const password = passwordInput.value;
    if (!deviceId) {
      setState("NO DEVICE", "error");
      return;
    }
    if (!password) {
      setState("PASSWORD REQUIRED", "error");
      return;
    }

    selectEvidenceDevice(deviceId);
    readButton.disabled = true;
    setState("READING");
    setMessage();
    try {
      const payload = await readCtConfiguration(deviceId, password);
      if (getSelectedDevice() === deviceId) renderCtEvidence(payload);
    } catch (error) {
      if (getSelectedDevice() === deviceId) {
        setState("READ ERROR", "error");
        setMessage(`Evidence read failed: ${error.message}`, "error");
      }
    } finally {
      passwordInput.value = "";
      readButton.disabled = false;
    }
  };

  readButton.addEventListener("click", read);
  passwordInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") read();
  });
}
