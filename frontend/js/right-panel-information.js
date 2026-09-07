const STYLE_MARKER = "right-panel-information-styles";

function ensureStylesheet() {
  if (document.getElementById(STYLE_MARKER)) return;
  const link = document.createElement("link");
  link.id = STYLE_MARKER;
  link.rel = "stylesheet";
  link.href = new URL("../css/panel-information.css", import.meta.url).href;
  document.head.append(link);
}

function makePurpose(text) {
  const node = document.createElement("p");
  node.className = "panel-purpose";
  node.textContent = text;
  return node;
}

function makeCriticalBoundary(items) {
  const node = document.createElement("div");
  node.className = "panel-critical-boundary";
  node.setAttribute("aria-label", "Critical operating boundary");
  for (const text of items) {
    const item = document.createElement("span");
    item.className = "panel-critical-boundary-item";
    item.textContent = text;
    node.append(item);
  }
  return node;
}

function makeTechnicalBoundary(paragraphs) {
  const details = document.createElement("details");
  details.className = "panel-technical-boundary";

  const summary = document.createElement("summary");
  summary.textContent = "TECHNICAL BOUNDARY";
  details.append(summary);

  const body = document.createElement("div");
  body.className = "panel-technical-boundary-body";
  for (const text of paragraphs) {
    const paragraph = document.createElement("p");
    paragraph.textContent = text;
    body.append(paragraph);
  }
  details.append(body);
  return details;
}

function replaceTextBlock(target, { purpose = null, critical = [], technical = [] }) {
  if (!target) return false;
  const fragment = document.createDocumentFragment();
  if (purpose) fragment.append(makePurpose(purpose));
  if (critical.length) fragment.append(makeCriticalBoundary(critical));
  if (technical.length) fragment.append(makeTechnicalBoundary(technical));
  target.replaceWith(fragment);
  return true;
}

function insertPanelIntro(panel, purpose, critical = []) {
  if (!panel || panel.dataset.panelInformation === "true") return false;
  const header = panel.querySelector(".utility-drawer-header, .load-control-panel-header");
  if (!header) return false;

  const fragment = document.createDocumentFragment();
  fragment.append(makePurpose(purpose));
  if (critical.length) fragment.append(makeCriticalBoundary(critical));
  header.after(fragment);
  panel.dataset.panelInformation = "true";
  return true;
}

function insertSectionInformation(section, purpose, critical = [], technical = []) {
  if (!section || section.dataset.panelInformation === "true") return false;
  const header = section.querySelector(".load-control-section-header");
  if (!header) return false;

  const fragment = document.createDocumentFragment();
  fragment.append(makePurpose(purpose));
  if (critical.length) fragment.append(makeCriticalBoundary(critical));
  if (technical.length) fragment.append(makeTechnicalBoundary(technical));
  header.after(fragment);
  section.dataset.panelInformation = "true";
  return true;
}

function decorateDiagnostics() {
  const drawer = document.getElementById("diagnostics-drawer");
  insertPanelIntro(drawer, "Shows runtime and device evidence for the selected Emonio.");

  replaceTextBlock(drawer?.querySelector(".diagnostics-quality-note"), {
    critical: [
      "OBSERVATIONAL EVIDENCE",
      "VALID does not mean scientifically qualified.",
    ],
    technical: [
      "Scientific warning thresholds are unqualified and disabled.",
      "Residuals remain observational evidence.",
    ],
  });

  const modbusBody = document.querySelector("#modbus-evidence-details .modbus-evidence-body");
  if (modbusBody && modbusBody.dataset.panelInformation !== "true") {
    const message = modbusBody.querySelector(".modbus-evidence-message");
    message?.after(makePurpose("Reads documented energy, phase activity, error, and warning evidence without changing device state."));
    replaceTextBlock(modbusBody.querySelector(".modbus-evidence-note"), {
      critical: [
        "READ-ONLY DEVICE EVIDENCE",
        "RESET-ON-READ MIN/MAX REGISTERS ARE NOT READ",
        "SEPARATE FROM CANONICAL ACQUISITION",
      ],
      technical: [
        "Each documented range is probed independently so one failure cannot hide other results.",
        "KWH IN/OUT use holding registers 40/42, 140/142, 240/242 and 340/342. CONNECTED uses discrete inputs 0..2. ERROR/WARNING use holding registers 1000..1001.",
        "This evidence is separate from the canonical U/I/P/Q/S/PF/f acquisition path.",
      ],
    });
    modbusBody.dataset.panelInformation = "true";
  }

  const ctBody = document.querySelector("#ct-evidence-details .ct-evidence-body");
  if (ctBody && ctBody.dataset.panelInformation !== "true") {
    const message = ctBody.querySelector(".ct-evidence-message");
    message?.after(makePurpose("Reads raw current-sensor configuration through fixed Telnet commands."));
    replaceTextBlock(ctBody.querySelector(".ct-evidence-prerequisite"), {
      critical: [
        "TELNET REQUIRED",
        "READ-ONLY CT COMMANDS",
        "RAW DEVICE CONFIGURATION",
        "PHYSICAL CT ORIENTATION IS NOT VERIFIED",
      ],
    });
    replaceTextBlock(ctBody.querySelector(".ct-evidence-note"), {
      technical: [
        "The Emonio Telnet service must be enabled before CT configuration can be read. Telnet is normally disabled.",
        "This function uses only five fixed read-only CT commands. Normal Modbus measurements and SCOPE do not require Telnet.",
        "The Viewer does not infer physical direction from P or Q and does not interpret ct_type, ct_voltage, ct_range, or ct_didt without qualified mapping evidence.",
      ],
    });
    ctBody.dataset.panelInformation = "true";
  }
}

function decorateRecording() {
  insertPanelIntro(
    document.getElementById("recording-drawer"),
    "Manages session recording for the selected Emonio.",
  );
}

function decorateScope() {
  const drawer = document.getElementById("scope-drawer");
  insertPanelIntro(drawer, "Shows the Emonio waveform capture for selected phases and signals.", [
    "READ-ONLY",
    "P(t)=U[k]×I[k] IS SCOPE-DERIVED",
    "NOT CANONICAL MODBUS P",
  ]);

  replaceTextBlock(drawer?.querySelector(".scope-science-note"), {
    technical: [
      "Source is the Emonio WebSocket SCOPE.",
      "U and I are the exact received FLOAT32 samples. P(t)=U[k]×I[k] is calculated from same-index samples.",
      "NO SMOOTHING. NO AVERAGING. NO RESAMPLING.",
      "Display scales only. Rate is derived from the capture axis.",
    ],
  });
}

function sectionByHeading(panel, headingText) {
  for (const section of panel?.querySelectorAll(".load-control-section") || []) {
    if (section.querySelector(".load-control-section-header h3")?.textContent?.trim() === headingText) {
      return section;
    }
  }
  return null;
}

function decorateLoadControlBase() {
  const panel = document.getElementById("load-control-panel");
  if (!panel) return false;

  insertPanelIntro(panel, "Connects one qualified actuator and runs the zero-export controller.", [
    "PHYSICAL PWM COMMANDS",
    "QUALIFIED ACTUATOR",
    "OFF CONFIRMATION REQUIRED",
  ]);
  panel.querySelector(".load-control-stage-note")?.remove();

  const actuator = sectionByHeading(panel, "Actuator");
  if (actuator && actuator.dataset.panelInformation !== "true") {
    replaceTextBlock(actuator.querySelector(".load-control-section-note"), {
      purpose: "Finds, selects, and qualifies one compatible actuator.",
    });
    actuator.dataset.panelInformation = "true";
  }

  const engineering = document.getElementById("lc-engineering-diagnostics");
  if (engineering && engineering.dataset.panelInformation !== "true") {
    replaceTextBlock(engineering.querySelector(":scope > .load-control-section-note"), {
      purpose: "Provides manual PWM control and protocol evidence for engineering work.",
      technical: ["These tools are not required for normal zero-export operation."],
    });
    engineering.dataset.panelInformation = "true";
  }

  const diagnosticLog = sectionByHeading(panel, "Diagnostic log");
  if (diagnosticLog && diagnosticLog.dataset.panelInformation !== "true") {
    replaceTextBlock(diagnosticLog.querySelector(".load-control-section-note"), {
      purpose: "Shows backend LAN, WebSocket/HELLO, PWM command, ACK, and rejection evidence.",
      technical: ["CLEAR VIEW does not delete the backend log."],
    });
    diagnosticLog.dataset.panelInformation = "true";
  }
  return true;
}

function decorateManualPwm() {
  const section = document.querySelector(".load-control-pwm-section");
  if (!section || section.dataset.panelInformation === "true") return false;
  section.querySelector(".load-control-section-note")?.remove();
  insertSectionInformation(
    section,
    "Sends direct PWM duty commands to the qualified actuator.",
    [
      "PHYSICAL PWM COMMANDS",
      "DO NOT USE WITH AUTOMATIC CONTROL",
    ],
    [
      "This control does not use Emonio measurements.",
      "This control does not convert watts to duty.",
      "Do not use it while automatic zero-export control owns PWM authority.",
    ],
  );
  return true;
}

function decorateZeroExport() {
  const section = document.querySelector(".load-control-zero-export");
  if (!section || section.dataset.panelInformation === "true") return false;
  section.querySelector(".load-control-zero-export-boundary")?.remove();
  insertSectionInformation(
    section,
    "Uses canonical signed P to drive the qualified actuator toward 0 W.",
    [
      "AUTOMATIC PHYSICAL PWM CONTROL",
      "P ONLY",
      "OFF MUST BE CONFIRMED",
      "OFF 0 % · ACTIVE 5–95 %",
    ],
    [
      "Automatic physical PWM control is active when enabled. Canonical signed P is the only measurement feedback input. Target is fixed at 0 W.",
      "No watts-to-duty calibration is used. No operator-selected duty increment is used. No Q or PF control is used. No PID is active. No automatic reconnect is used.",
      "The qualified requested-duty range is OFF 0 % and active 5–95 %. Actual PWM duty is quantized by actuator timer-tick resolution.",
      "LIMIT_LOW holds confirmed OFF after opposite P signs were observed at OFF and the 5 % active minimum. No qualified requested duty exists between OFF and 5 %, so automatic control does not repeat the 0↔5 sequence until the operator disables and re-enables automatic control.",
      "RESOLUTION_LIMIT holds the current physical PWM state after a requested adjustment produces no timer-tick change. Further commands in that same direction are suppressed until canonical P changes direction or enters the deadband, or automatic control is restarted.",
      "A control fault requests one explicit OFF. If OFF cannot be confirmed, the state is SAFE_UNCONFIRMED.",
    ],
  );
  return true;
}

function decorateStaticPanels() {
  decorateDiagnostics();
  decorateRecording();
  decorateScope();
}

function decorateDynamicPanels() {
  decorateLoadControlBase();
  decorateManualPwm();
  decorateZeroExport();
}

export function initializeRightPanelInformation() {
  ensureStylesheet();
  decorateStaticPanels();
  if (document.readyState === "complete") {
    decorateDynamicPanels();
  } else {
    window.addEventListener("load", decorateDynamicPanels, { once: true });
  }
}
