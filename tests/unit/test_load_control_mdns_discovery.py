from emonio_viewer.load_control import discovery


def test_mdns_record_maps_to_actuator_descriptor() -> None:
    assert discovery.LOAD_CONTROL_MDNS_SERVICE_TYPE == "_ari-emonio-load._tcp.local."
    assert hasattr(discovery, "parse_mdns_descriptor")

    descriptor = discovery.parse_mdns_descriptor(
        address="192.168.20.44",
        port=8765,
        properties={
            b"node_id": b"ARI-LOAD-001",
            b"device_class": b"ARI_LOAD_ACTUATOR",
            b"capabilities": b"ACTIVE_LOAD_CONTROL,REACTIVE_COMPENSATION",
            b"p_max_a_w": b"1200.0",
            b"p_max_b_w": b"1300.0",
            b"p_max_c_w": b"1400.0",
            b"ws_path": b"/control",
        },
    )

    assert descriptor.node_id == "ARI-LOAD-001"
    assert descriptor.location == "ws://192.168.20.44:8765/control"
    assert descriptor.device_class == "ARI_LOAD_ACTUATOR"
    assert descriptor.capabilities == ("ACTIVE_LOAD_CONTROL", "REACTIVE_COMPENSATION")
    assert descriptor.p_max.a == 1200.0
    assert descriptor.p_max.b == 1300.0
    assert descriptor.p_max.c == 1400.0
