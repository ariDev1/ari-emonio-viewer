const DRAWERS = Object.freeze([
  Object.freeze({ toggleId: "diagnostics-toggle", drawerId: "diagnostics-drawer" }),
  Object.freeze({ toggleId: "recording-toggle", drawerId: "recording-drawer" }),
  Object.freeze({ toggleId: "scope-toggle", drawerId: "scope-drawer" }),
]);

function setDrawerOpen(drawerId, open) {
  for (const definition of DRAWERS) {
    const drawer = document.getElementById(definition.drawerId);
    const toggle = document.getElementById(definition.toggleId);
    if (!drawer || !toggle) continue;
    const shouldOpen = definition.drawerId === drawerId && open;
    drawer.hidden = !shouldOpen;
    toggle.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
    toggle.classList.toggle("is-open", shouldOpen);
  }
}

export function closeUtilityDrawers() {
  setDrawerOpen("", false);
}

export function initializeUtilityDrawers() {
  for (const definition of DRAWERS) {
    const toggle = document.getElementById(definition.toggleId);
    const drawer = document.getElementById(definition.drawerId);
    if (!toggle || !drawer || toggle.dataset.utilityBound === "true") continue;
    toggle.dataset.utilityBound = "true";
    toggle.addEventListener("click", () => {
      setDrawerOpen(definition.drawerId, drawer.hidden);
    });
  }

  for (const open of document.querySelectorAll("[data-utility-open]")) {
    if (open.dataset.utilityOpenBound === "true") continue;
    open.dataset.utilityOpenBound = "true";
    open.addEventListener("click", () => {
      const drawerId = open.dataset.utilityOpen;
      if (drawerId) setDrawerOpen(drawerId, true);
    });
  }

  for (const close of document.querySelectorAll("[data-utility-close]")) {
    if (close.dataset.utilityCloseBound === "true") continue;
    close.dataset.utilityCloseBound = "true";
    close.addEventListener("click", closeUtilityDrawers);
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeUtilityDrawers();
  });
}
