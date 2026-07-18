from app.mesh_simulator_service import MeshSimulatorService
from app.schemas import MeshPacket


def _packet(packet_id="pkt-1", ttl=5) -> MeshPacket:
    return MeshPacket(packet_id=packet_id, ttl=ttl, created_at=1_700_000_000_000, ciphertext="ZmFrZQ==")


def test_default_devices_seeded():
    mesh = MeshSimulatorService()
    devices = mesh.get_devices()
    assert len(devices) == 5
    bridges = [d for d in devices if d.has_internet]
    assert len(bridges) == 1
    assert bridges[0].device_id == "phone-bridge"


def test_inject_places_packet_on_device():
    mesh = MeshSimulatorService()
    mesh.inject("phone-alice", _packet())
    assert mesh.get_device("phone-alice").packet_count() == 1


def test_inject_unknown_device_raises():
    mesh = MeshSimulatorService()
    try:
        mesh.inject("phone-nonexistent", _packet())
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_gossip_spreads_packet_to_all_devices():
    mesh = MeshSimulatorService()
    mesh.inject("phone-alice", _packet(ttl=5))
    mesh.gossip_once()
    counts = mesh.snapshot_map()
    assert all(count == 1 for count in counts.values())


def test_gossip_decrements_ttl_and_stops_at_zero():
    mesh = MeshSimulatorService()
    mesh.inject("phone-alice", _packet(ttl=1))
    result = mesh.gossip_once()
    assert result.transfers == 4  # spreads to the other 4 devices once
    # TTL is now 0 everywhere, so a second round should transfer nothing new.
    result2 = mesh.gossip_once()
    assert result2.transfers == 0


def test_bridge_upload_only_collects_from_internet_devices():
    mesh = MeshSimulatorService()
    mesh.inject("phone-alice", _packet())
    mesh.gossip_once()
    uploads = mesh.collect_bridge_uploads()
    assert len(uploads) == 1
    assert uploads[0].bridge_node_id == "phone-bridge"


def test_reset_clears_all_devices():
    mesh = MeshSimulatorService()
    mesh.inject("phone-alice", _packet())
    mesh.reset_mesh()
    assert all(count == 0 for count in mesh.snapshot_map().values())
