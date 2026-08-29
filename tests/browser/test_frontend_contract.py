from pathlib import Path


def test_frontend_has_fixed_phase_and_total_panels() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    for element_id in ("phase-a", "phase-b", "phase-c", "phase-total"):
        assert f'id="{element_id}"' in html


def test_css_is_split_by_responsibility() -> None:
    css = Path("frontend/css")
    assert {p.name for p in css.glob("*.css")} == {
        "base.css",
        "layout.css",
        "phase-panels.css",
        "quadrant.css",
        "diagnostics.css",
        "recording.css",
        "ct-evidence.css",
        "history.css",
        "scope.css",
        "modbus-evidence.css",
    }


def test_frontend_contains_no_emonio_ip_or_modbus_socket_logic() -> None:
    source = "\n".join(p.read_text(encoding="utf-8") for p in Path("frontend/js").glob("*.js"))
    assert "192.168." not in source
    assert ":502" not in source
    assert "build_read_holding_request" not in source
    assert "read_holding_registers" not in source
    assert "read_discrete_inputs" not in source


def test_frontend_has_explicit_quality_and_sample_age_elements() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    assert 'id="quality-state"' in html
    assert 'id="sample-age"' in html


def test_websocket_close_does_not_zero_measurements() -> None:
    source = "\n".join(p.read_text(encoding="utf-8") for p in Path("frontend/js").glob("*.js"))
    prohibited = (
        "resetMeasurementsToZero",
        "zeroAllMeasurements",
        "setAllMeasurements(0",
    )
    assert all(token not in source for token in prohibited)


def test_recording_options_are_derived_from_selected_device_poll_interval() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    source = Path("frontend/js/app.js").read_text(encoding="utf-8")
    assert '<option value="1">1 s</option>' not in html
    assert "configureRecordingIntervals" in source
    assert "poll_interval_s" in source


def test_measurement_display_uses_four_decimal_places() -> None:
    source = Path("frontend/js/measurements.js").read_text(encoding="utf-8")
    assert "const MEASUREMENT_DECIMALS = 4" in source
    assert "toFixed(MEASUREMENT_DECIMALS)" in source


def test_frontend_has_direct_emonio_target_connection_controls() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    source = Path("frontend/js/app.js").read_text(encoding="utf-8")
    api = Path("frontend/js/api.js").read_text(encoding="utf-8")
    assert 'id="device-target"' in html
    assert 'id="device-connect"' in html
    assert 'id="target-status"' in html
    assert "connectDevice" in source
    assert '"/api/v1/devices/connect"' in api


def test_scientific_layout_uses_full_width_four_phase_row_without_device_sidebar() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    css = Path("frontend/css/layout.css").read_text(encoding="utf-8")
    assert 'class="device-rail"' not in html
    assert "grid-template-columns: repeat(4" in css
    assert "target-strip" in css


def test_quadrant_renders_vectors_from_origin_for_all_series() -> None:
    source = Path("frontend/js/quadrant.js").read_text(encoding="utf-8")
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    assert "plot-vector" in source
    assert "data-vector" in source
    assert 'id="pq-vectors"' in html
    for label in ("A", "B", "C", "T"):
        assert f'[data-vector="${{label}}"]' in source or "dataset.vector = label" in source


def test_quadrant_plot_uses_svg_space_without_inner_border_and_keeps_legend_inside() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    css = Path("frontend/css/quadrant.css").read_text(encoding="utf-8")
    assert "plot-frame" not in html
    assert 'id="pq-legend"' in html
    assert 'id="pq-scale"' in html
    assert "plot-legend-item" in css
    assert "plot-scale-text" in css


def test_wide_science_workspace_places_square_quadrant_beside_history() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    css = Path("frontend/css/layout.css").read_text(encoding="utf-8")
    quadrant_css = Path("frontend/css/quadrant.css").read_text(encoding="utf-8")
    workspace_start = html.index('class="science-workspace"')
    workspace_end = html.index('</section>', html.index('id="history-section"', workspace_start))
    workspace = html[workspace_start:workspace_end]
    assert workspace.index('class="quadrant-card"') < workspace.index('id="history-section"')
    assert 'id="diagnostics-drawer"' not in workspace
    assert ".science-workspace {" in css
    science_first = css.index(".science-workspace {")
    science_start = css.index(".science-workspace {", science_first + 1)
    science = css[science_start:css.index(".quadrant-card {", science_start)]
    assert "grid-template-columns: clamp(400px, 24vw, 470px) minmax(0, 1fr);" in science
    assert "aspect-ratio: 1 / 1;" in quadrant_css


def test_quadrant_scale_is_adaptive_not_fixed_session_scale() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    source = Path("frontend/js/quadrant.js").read_text(encoding="utf-8")
    assert "Fixed session scale" not in html
    assert "id=\"pq-scale\"" in html
    assert "SCALE waiting for data" in html
    assert "computeAdaptiveLimit" in source
    assert "SHRINK_CONFIRMATION_SAMPLES" in source
    assert "SCALE_MARGIN" in source


def test_ct_configuration_is_compact_device_evidence_inside_diagnostics_drawer() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    source = Path("frontend/js/ct-evidence.js").read_text(encoding="utf-8")
    api = Path("frontend/js/api.js").read_text(encoding="utf-8")

    diagnostics_start = html.index('id="diagnostics-drawer"')
    diagnostics_end = html.index('</aside>', diagnostics_start)
    ct_details = html.index('id="ct-evidence-details"')
    assert diagnostics_start < ct_details < diagnostics_end
    assert 'id="ct-evidence-state"' in html
    assert '<details id="ct-evidence-details"' in html
    assert 'id="ct-password" type="password"' in html
    assert "CT CONFIG: TELNET NOT CHECKED" in html
    assert "TELNET REQUIRED" in html
    assert "Telnet is normally disabled" in html
    assert "Normal Modbus measurements and SCOPE do not require Telnet" in html
    assert 'autocomplete="off"' in html
    assert 'id="ct-values"' in html
    assert 'id="ct-physical-status"' in html
    for key in ("ct_type", "ct_voltage", "ct_range", "ct_invert", "ct_didt"):
        assert f'data-ct-key="{key}"' in html
    assert "RAW DEVICE CONFIGURATION" in html
    assert "PHYSICAL CT ORIENTATION IS NOT VERIFIED" in html
    assert "readCtConfiguration" in source
    assert "/ct-config/read" in api
    assert 'passwordInput.value = ""' in source


def test_ct_frontend_does_not_invent_unproven_sensor_mappings() -> None:
    source = "\n".join(
        [
            Path("frontend/index.html").read_text(encoding="utf-8"),
            Path("frontend/js/ct-evidence.js").read_text(encoding="utf-8"),
        ]
    )
    for unsupported_mapping in ("User Defined", "11100 mV/kA", "45 A max."):
        assert unsupported_mapping not in source


def test_history_view_is_structured_and_explicitly_unfiltered() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    source = Path("frontend/js/app.js").read_text(encoding="utf-8")
    assert 'id="history-section"' in html
    assert 'id="history-active-plot"' in html
    assert "ROLLING 10 MIN" in html
    assert "appendHistoryPayload" in source
    assert "renderMeasurementHistory" in source


def test_history_css_has_its_own_responsibility_file() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="/static/css/history.css">' in html


def test_quadrant_and_history_share_one_primary_science_row() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    css = Path("frontend/css/layout.css").read_text(encoding="utf-8")
    assert 'class="science-workspace"' in html
    science_start = html.index('class="science-workspace"')
    quadrant_index = html.index('class="quadrant-card"', science_start)
    history_index = html.index('id="history-section"', science_start)
    assert science_start < quadrant_index < history_index
    viewer_shell = css[css.index(".viewer-shell {"):css.index(".status-bar { grid-area: status; }")]
    assert '"science"' in viewer_shell
    assert '"analysis"' not in viewer_shell
    assert '"history"' not in viewer_shell


def test_history_has_metric_selector_and_compact_exact_sample_inspector() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    source = Path("frontend/js/history.js").read_text(encoding="utf-8")
    app = Path("frontend/js/app.js").read_text(encoding="utf-8")
    css = Path("frontend/css/history.css").read_text(encoding="utf-8")

    assert 'class="history-selector"' in html
    assert 'id="history-active-title"' in html
    assert 'id="history-active-scale-note"' in html
    assert 'id="history-active-plot"' in html
    assert 'id="history-inspector-phase-grid"' in html
    assert 'class="history-inspector-phase-card"' in html
    assert 'id="history-inspector-timestamp"' in html
    assert 'id="history-inspector-table"' not in html
    for field in ("p", "q", "vrms", "irms", "s", "pf", "frequency"):
        assert f'data-history-select-field="{field}"' in html
    for phase in ("A", "B", "C", "TOTAL"):
        assert f'data-history-inspector-phase="{phase}"' in html
    assert "initializeHistoryInspection" in source
    assert "initializeHistoryMetricSelector" in source
    assert "initializeHistoryInspection" in app
    assert "history-selector-button" in css
    assert "history-inspection-cursor" in css


def test_history_inspector_keeps_all_four_phase_blocks_visible_without_footer_notes() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    css = Path("frontend/css/history.css").read_text(encoding="utf-8")

    for phase in ("A", "B", "C", "TOTAL"):
        assert f'data-history-inspector-phase="{phase}"' in html

    assert 'class="history-inspector-note"' not in html
    assert 'class="history-science-note"' not in html

    phase_grid = css[
        css.index(".history-inspector-phase-grid {"):
        css.index(".history-inspector-phase-card {", css.index(".history-inspector-phase-grid {"))
    ]
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in phase_grid
    assert "grid-template-rows: repeat(2, minmax(0, 1fr));" in phase_grid


def test_history_view_contains_metric_selector_for_all_requested_canonical_fields() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    for field in ("p", "q", "vrms", "irms", "s", "pf", "frequency"):
        assert f'data-history-select-field="{field}"' in html
    for title in ("P(t)", "Q(t)", "U(t)", "I(t)", "S(t)", "PF(t)", "f(t)"):
        assert title in html
    assert "ROLLING 10 MIN · CANONICAL MEASUREMENTS" in html


def test_history_renderer_has_no_connected_sample_geometry() -> None:
    source = Path("frontend/js/history.js").read_text(encoding="utf-8")
    assert 'svgElement("path"' not in source
    assert 'svgElement("polyline"' not in source
    assert 'svgElement("polygon"' not in source


def test_history_inspection_maps_pointer_through_svg_coordinate_transform() -> None:
    source = Path("frontend/js/history.js").read_text(encoding="utf-8")
    assert "getScreenCTM" in source
    assert "createSVGPoint" in source
    assert "getBoundingClientRect" not in source


def test_history_inspection_keyboard_steps_only_exact_stored_samples() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    source = Path("frontend/js/history.js").read_text(encoding="utf-8")
    css = Path("frontend/css/history.css").read_text(encoding="utf-8")
    assert 'id="history-active-plot"' in html
    plot_tag = html[html.index('<svg id="history-active-plot"'):html.index('</svg>', html.index('<svg id="history-active-plot"'))]
    assert 'tabindex="0"' in plot_tag
    assert 'aria-keyshortcuts="ArrowLeft ArrowRight"' in plot_tag
    assert 'addEventListener("keydown"' in source
    assert 'event.key === "ArrowLeft"' in source
    assert 'event.key === "ArrowRight"' in source
    assert "adjacentHistorySample" in source
    assert "event.preventDefault()" in source
    assert "svg.focus" in source
    assert ".history-plot:focus-visible" in css


def test_workstation_shell_uses_fixed_viewport_layout_without_page_scroll() -> None:
    base = Path("frontend/css/base.css").read_text(encoding="utf-8")
    layout = Path("frontend/css/layout.css").read_text(encoding="utf-8")
    assert "html { min-width: 320px; background: var(--bg); height: 100%; overflow: hidden; }" in base
    assert "body { margin: 0; min-height: 100vh; height: 100vh; overflow: hidden;" in base
    assert "height: 100vh;" in layout
    viewer = layout[layout.index(".viewer-shell {"):layout.index(".status-bar { grid-area: status; }")]
    assert '"science"' in viewer
    assert '"recording-strip"' in viewer
    assert "grid-template-rows: auto auto auto minmax(0, 1fr) auto;" in viewer


def test_diagnostics_and_recording_are_overlay_drawers_with_persistent_top_status() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    app = Path("frontend/js/app.js").read_text(encoding="utf-8")
    workstation = Path("frontend/js/workstation.js").read_text(encoding="utf-8")
    assert 'id="diagnostics-toggle"' in html
    assert 'id="recording-toggle"' in html
    assert 'id="diagnostics-drawer" class="utility-drawer diagnostics-drawer"' in html
    assert 'id="recording-drawer" class="utility-drawer recording-drawer"' in html
    assert 'id="diagnostics-drawer" class="utility-drawer diagnostics-drawer"' in html and ' hidden' in html[html.index('id="diagnostics-drawer"')-80:html.index('id="diagnostics-drawer"')+180]
    assert 'id="recording-drawer" class="utility-drawer recording-drawer"' in html and ' hidden' in html[html.index('id="recording-drawer"')-80:html.index('id="recording-drawer"')+180]
    assert 'id="diagnostics-summary-state"' in html
    assert 'id="diagnostics-summary-cycles"' in html
    assert 'id="diagnostics-summary-errors"' in html
    assert 'id="recording-selected-device"' in html
    assert 'id="recording-selected-state"' in html
    assert "initializeUtilityDrawers" in app
    assert "initializeUtilityDrawers" in workstation


def test_closed_utility_drawers_consume_zero_scientific_grid_space() -> None:
    layout = Path("frontend/css/layout.css").read_text(encoding="utf-8")
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    viewer = layout[layout.index(".viewer-shell {"):layout.index(".status-bar { grid-area: status; }")]
    assert '"diagnostics"' not in viewer
    assert '"recording-drawer"' not in viewer
    assert 'position: fixed;' in layout
    assert '.utility-drawer[hidden]' in layout
    assert 'display: none;' in layout
    assert html.index('id="diagnostics-drawer"') > html.index('</main>')
    assert html.index('id="recording-drawer"') > html.index('</main>')


def test_utility_drawers_overlay_the_workstation_without_layout_shift() -> None:
    layout = Path("frontend/css/layout.css").read_text(encoding="utf-8")
    assert ".utility-drawer {" in layout
    drawer = layout[layout.index(".utility-drawer {"):layout.index(".utility-drawer[hidden]")]
    assert "position: fixed;" in drawer
    assert "right:" in drawer
    assert "z-index:" in drawer
    assert "overflow: auto;" in drawer
    assert "width: min(" in drawer


def test_history_uses_horizontal_plot_and_exact_sample_inspector_workspace() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    css = Path("frontend/css/history.css").read_text(encoding="utf-8")
    assert 'class="history-workspace"' in html
    workspace_start = html.index('class="history-workspace"')
    plot = html.index('id="history-active-plot"')
    inspector = html.index('id="history-inspector"')
    assert workspace_start < plot < inspector
    assert ".history-workspace {" in css
    workspace_css = css[css.index(".history-workspace {"):css.index(".history-plot-card {")]
    assert "grid-template-columns: minmax(0, 3fr) minmax(360px, 1fr);" in workspace_css
    assert "minmax(0, 1fr)" in css
    assert ".history-plot-active" in css
    assert "height: 100%;" in css


def test_recording_drawer_names_selected_device_and_active_recording_owners() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    app = Path("frontend/js/app.js").read_text(encoding="utf-8")
    api = Path("frontend/js/api.js").read_text(encoding="utf-8")
    drawer_start = html.index('id="recording-drawer"')
    drawer_end = html.index('</aside>', drawer_start)
    assert 'id="recording-control-device"' in html[drawer_start:drawer_end]
    assert 'id="recording-active-list"' in html[drawer_start:drawer_end]
    assert 'id="recording-selected-device"' in html[:drawer_start]
    assert 'id="recording-selected-state"' in html[:drawer_start]
    assert "RecordingState" in app
    assert "getRecordingStatus" in app
    assert '"/api/v1/recording/status"' in api


def test_status_bar_keeps_diag_and_recording_state_visible_with_drawers_closed() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    status_start = html.index('<header class="status-bar"')
    status_end = html.index('</header>', status_start)
    status = html[status_start:status_end]
    for element_id in (
        "diagnostics-toggle",
        "diagnostics-summary-state",
        "diagnostics-summary-cycles",
        "diagnostics-summary-errors",
        "recording-toggle",
        "recording-selected-device",
        "recording-selected-state",
        "recording-summary-state",
    ):
        assert f'id="{element_id}"' in status


def test_wide_workstation_does_not_reserve_horizontal_space_for_closed_diagnostics() -> None:
    layout = Path("frontend/css/layout.css").read_text(encoding="utf-8")
    assert ".science-workspace {" in layout
    assert "minmax(280px, 0.85fr)" not in layout
    assert "minmax(320px, 0.85fr)" not in layout
    assert ".analysis-grid" not in layout


def test_static_diagnostics_defaults_do_not_claim_unobserved_online_state() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    assert 'id="diagnostics-summary-state">NO DATA<' in html
    assert 'id="diagnostics-summary-cycles">— VALID<' in html
    assert 'id="diagnostics-summary-errors">— ERRORS<' in html
    diagnostics_start = html.index('id="diagnostics-drawer"')
    diagnostics_end = html.index('</aside>', diagnostics_start)
    assert ">ONLINE<" not in html[diagnostics_start:diagnostics_end]


def test_quadrant_svg_uses_square_coordinate_space_without_nonuniform_distortion() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    source = Path("frontend/js/quadrant.js").read_text(encoding="utf-8")
    css = Path("frontend/css/quadrant.css").read_text(encoding="utf-8")
    assert 'id="pq-plot" viewBox="0 0 430 430"' in html
    assert "const VIEWBOX_WIDTH = 430;" in source
    assert "const VIEWBOX_HEIGHT = 430;" in source
    assert "aspect-ratio: 1 / 1;" in css
    assert 'preserveAspectRatio="xMidYMid meet"' in html


def test_recording_strip_is_always_visible_and_keeps_primary_controls_outside_drawer() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    css = Path("frontend/css/recording.css").read_text(encoding="utf-8")
    workstation = Path("frontend/js/workstation.js").read_text(encoding="utf-8")
    main_end = html.index('</main>')
    for element_id in (
        "recording-strip",
        "recording-strip-device",
        "recording-state",
        "recording-interval",
        "record-start",
        "record-stop",
        "recording-more",
    ):
        assert f'id="{element_id}"' in html[:main_end]
    drawer_start = html.index('id="recording-drawer"')
    drawer_end = html.index('</aside>', drawer_start)
    drawer = html[drawer_start:drawer_end]
    assert 'id="session-note"' in drawer
    assert 'id="recording-active-list"' in drawer
    assert 'id="recording-interval"' not in drawer
    assert 'id="record-start"' not in drawer
    assert 'id="record-stop"' not in drawer
    assert ".recording-strip {" in css
    assert 'data-utility-open="recording-drawer"' in html
    assert "[data-utility-open]" in workstation


def test_recording_strip_names_selected_emonio_and_never_hides_record_state() -> None:
    app = Path("frontend/js/app.js").read_text(encoding="utf-8")
    assert 'setText("recording-strip-device", selectedName);' in app
    assert 'document.getElementById("recording-state")' in app


def test_history_has_selectable_display_windows_without_changing_ten_minute_storage_contract() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    source = Path("frontend/js/history.js").read_text(encoding="utf-8")
    app = Path("frontend/js/app.js").read_text(encoding="utf-8")
    css = Path("frontend/css/history.css").read_text(encoding="utf-8")

    assert "ROLLING 10 MIN · CANONICAL MEASUREMENTS" in html
    assert 'class="history-window-selector"' in html
    for milliseconds, label in (
        (30000, "30 s"),
        (60000, "1 min"),
        (120000, "2 min"),
        (300000, "5 min"),
        (600000, "10 min"),
    ):
        assert f'data-history-window-ms="{milliseconds}"' in html
        assert f">{label}</button>" in html
    assert 'id="history-display-window"' in html
    assert "initializeHistoryWindowSelector" in source
    assert "initializeHistoryWindowSelector" in app
    assert "HISTORY_DISPLAY_WINDOWS" in source
    assert "visibleHistorySamples" in source
    assert ".history-window-selector" in css
    assert "DISPLAY WINDOW" in html
    assert "export const HISTORY_WINDOW_MS = 10 * 60 * 1000;" in source


def test_scope_overlay_contract_requires_operator_credentials_and_preserves_workspace_layout() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    layout = Path("frontend/css/layout.css").read_text(encoding="utf-8")
    scope_css = Path("frontend/css/scope.css").read_text(encoding="utf-8")
    assert 'href="/static/css/scope.css"' in html
    assert 'id="scope-toggle"' in html
    assert 'aria-controls="scope-drawer"' in html
    assert 'id="scope-drawer"' in html
    assert 'class="utility-drawer scope-drawer"' in html
    assert 'id="scope-username"' in html
    assert 'id="scope-password" type="password"' in html
    assert 'id="scope-start"' in html
    assert 'id="scope-live"' in html
    assert 'id="scope-hold"' in html
    assert 'id="scope-stop"' in html
    assert 'id="scope-plot"' in html
    assert 'data-scope-phase="ABC"' in html
    assert 'data-scope-signal="U+I"' in html
    assert "position: fixed" in layout
    assert ".scope-drawer" in scope_css


def test_scope_frontend_uses_local_api_only_and_never_browser_storage_or_direct_emonio_websocket() -> None:
    api = Path("frontend/js/api.js").read_text(encoding="utf-8")
    scope = Path("frontend/js/scope.js").read_text(encoding="utf-8")
    app = Path("frontend/js/app.js").read_text(encoding="utf-8")
    workstation = Path("frontend/js/workstation.js").read_text(encoding="utf-8")
    for token in (
        "/scope`",
        "/scope/start`",
        "/scope/hold`",
        "/scope/live`",
        "/scope/stop`",
    ):
        assert token in api
    assert "localStorage" not in scope
    assert "sessionStorage" not in scope
    assert "new WebSocket" not in scope
    assert "scope-username" in scope
    assert "scope-password" in scope
    assert 'from "./scope.js"' in app
    assert "initializeScopeControls" in app
    assert 'drawerId: "scope-drawer"' in workstation


def test_scope_instrument_layout_has_compact_session_owner_evidence_and_plot_regions() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    css = Path("frontend/css/scope.css").read_text(encoding="utf-8")
    scope = Path("frontend/js/scope.js").read_text(encoding="utf-8")
    for token in (
        'class="scope-command-bar"',
        'id="scope-active-count"',
        'id="scope-active-owners"',
        'class="scope-evidence-strip"',
        'class="scope-plot-card"',
        'id="scope-legend"',
    ):
        assert token in html
    for selector in (
        ".scope-command-bar",
        ".scope-owner-strip",
        ".scope-owner-chip",
        ".scope-evidence-strip",
        ".scope-grid-major",
        ".scope-grid-minor",
        ".scope-state-badge",
    ):
        assert selector in css
    assert "scopeActiveOwners" in scope
    assert "scopeGridPositions" in scope


def test_scope_multi_device_frontend_preserves_device_local_view_and_rejects_stale_status_render() -> None:
    scope = Path("frontend/js/scope.js").read_text(encoding="utf-8")
    assert "scopeViewModeForDevice" in scope
    assert "setScopeViewModeForDevice" in scope
    assert "scopeResponseIsCurrent" in scope
    assert "active_sessions" in scope


def test_scope_evidence_strip_exposes_observed_frame_prefix_as_diagnostic_only() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    scope = Path("frontend/js/scope.js").read_text(encoding="utf-8")
    assert 'id="scope-prefix"' in html
    assert "scopeObservedHeaderPrefixes" in scope
    assert "OBSERVED" in scope


def test_scope_drawer_has_internal_emonio_selector_wired_to_global_device_selection() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    scope = Path("frontend/js/scope.js").read_text(encoding="utf-8")
    app = Path("frontend/js/app.js").read_text(encoding="utf-8")
    css = Path("frontend/css/scope.css").read_text(encoding="utf-8")

    assert 'id="scope-device-selector"' in html
    assert 'aria-label="Select Emonio for Scope"' in html
    assert "scopeSelectableDevices" in scope
    assert "renderScopeDeviceSelector" in scope
    assert "scope-device-selector" in scope
    assert "selectDevice" in app
    assert "runtimeConfig?.devices" in app
    assert ".scope-device-selector" in css


def test_scope_device_switch_clears_runtime_credentials_before_selecting_another_emonio() -> None:
    scope = Path("frontend/js/scope.js").read_text(encoding="utf-8")
    switch_start = scope.index('scopeDeviceSelector?.addEventListener("change"')
    switch_block = scope[switch_start:switch_start + 1800]
    assert 'username.value = ""' in switch_block
    assert 'password.value = ""' in switch_block
    assert "deviceSelectionWriter" in switch_block


def test_history_inspector_copy_exports_exact_selected_sample_to_clipboard() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    source = Path("frontend/js/history.js").read_text(encoding="utf-8")
    app = Path("frontend/js/app.js").read_text(encoding="utf-8")
    css = Path("frontend/css/history.css").read_text(encoding="utf-8")

    button_start = html.index('id="history-inspector-copy"')
    button_tag = html[button_start - 160:button_start + 320]
    assert 'type="button"' in button_tag
    assert 'aria-label="Copy selected sample to clipboard"' in button_tag
    assert "disabled" in button_tag

    assert "export function formatHistorySampleClipboardText" in source
    assert 'ARI Emonio Viewer - Exact Stored Sample' in source
    for label in ("Device:", "Cycle:", "Finished UTC:", "Quality:"):
        assert label in source
    for field in ("vrms", "irms", "p", "q", "s", "pf", "frequency"):
        assert f'key: "{field}"' in source
    for label in ("U / V", "I / A", "P / W", "Q / var", "S / VA", "PF / —", "f / Hz"):
        assert label in source

    formatter_start = source.index("export function formatHistorySampleClipboardText")
    formatter_source = source[formatter_start:formatter_start + 2200]
    assert "formatCanonicalHistoryValue" in formatter_source
    assert ".toFixed(" not in formatter_source

    assert 'navigator.clipboard.writeText' in source
    assert 'selectedHistorySample(deviceId, browserHistory.get(deviceId))' in source
    assert '"COPIED"' in source
    assert '"COPY FAILED"' in source
    assert "initializeHistoryInspectorCopy" in source
    assert "initializeHistoryInspectorCopy" in app
    assert ".history-inspector-copy" in css


def test_modbus_device_evidence_is_isolated_in_diagnostics_drawer() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    source = Path("frontend/js/modbus-evidence.js").read_text(encoding="utf-8")
    api = Path("frontend/js/api.js").read_text(encoding="utf-8")
    assert 'id="modbus-evidence-details"' in html
    assert 'id="modbus-evidence-read"' in html
    for phase in ("A", "B", "C", "TOTAL"):
        assert f'data-modbus-energy-phase="{phase}"' in html
    for phase in ("A", "B", "C"):
        assert f'data-modbus-connected-phase="{phase}"' in html
    assert 'id="modbus-error-raw"' in html
    assert 'id="modbus-warning-raw"' in html
    assert "renderModbusEvidence" in source
    assert 'modbus-evidence/read' in api
    assert 'id="modbus-evidence-probe-grid"' in html
    assert "read_diagnostics" in source
    for label in ("PROBE", "FC", "ADDRESS", "COUNT", "RESULT", "ELAPSED", "DETAIL"):
        assert label in html


def test_scope_drawer_publishes_existing_per_phase_metadata_without_relabeling_as_modbus() -> None:
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    source = Path("frontend/js/scope.js").read_text(encoding="utf-8")
    assert 'id="scope-metadata-grid"' in html
    for phase in ("a", "b", "c"):
        for field in ("connected", "vrms", "irms", "frequency", "pf"):
            assert f'id="scope-meta-{phase}-{field}"' in html
    assert "renderScopeMetadata" in source
    assert "SCOPE METADATA" in html
