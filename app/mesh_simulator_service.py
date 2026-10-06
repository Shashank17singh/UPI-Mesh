"""
Mesh simulator service modeling device-to-device gossip propagation.
Manages the virtual device network and simulates packet transfer over Bluetooth/Wi-Fi Direct.
"""
import logging
from dataclasses import dataclass

from app.schemas import MeshPacket
from app.virtual_device import VirtualDevice

log = logging.getLogger("upimesh.mesh")


@dataclass
class GossipResult:
    transfers: int
    device_counts: dict[str, int]


@dataclass
class BridgeUpload:
    bridge_node_id: str
    packet: MeshPacket


class MeshSimulatorService:
    def __init__(self):
        self.devices: dict[str, VirtualDevice] = {}
        self._seed_default_devices()

    def _seed_default_devices(self) -> None:
        for device_id in (
            "phone-sender",
            "phone-stranger1",
            "phone-stranger2",
            "phone-stranger3",
        ):
            self.devices[device_id] = VirtualDevice(device_id, has_internet=False)
        self.devices["phone-bridge"] = VirtualDevice("phone-bridge", has_internet=True)

    def get_devices(self) -> list[VirtualDevice]:
        return list(self.devices.values())

    def get_device(self, device_id: str) -> VirtualDevice | None:
        return self.devices.get(device_id)

    def inject(self, sender_device_id: str, packet: MeshPacket) -> None:
        sender = self.devices.get(sender_device_id)
        if sender is None:
            raise ValueError(f"Unknown device: {sender_device_id}")
        sender.hold(packet)
        log.info(
            "Packet %s injected at %s (TTL=%s)",
            packet.packet_id[:8],
            sender_device_id,
            packet.ttl,
        )

    def gossip_once(self) -> GossipResult:
        transfers = 0
        device_list = list(self.devices.values())
        snapshot = {d.device_id: d.held_packets() for d in device_list}
        for src in device_list:
            for pkt in snapshot[src.device_id]:
                if pkt.ttl <= 0:
                    continue
                for dst in device_list:
                    if dst is src:
                        continue
                    if dst.holds(pkt.packet_id):
                        continue
                    copy = MeshPacket(
                        packet_id=pkt.packet_id,
                        ttl=pkt.ttl - 1,
                        created_at=pkt.created_at,
                        ciphertext=pkt.ciphertext,
                    )
                    dst.hold(copy)
                    transfers += 1
        log.info("Gossip round complete: %s packet transfers", transfers)
        return GossipResult(transfers, self.snapshot_map())

    def snapshot_map(self) -> dict[str, int]:
        return {d.device_id: d.packet_count() for d in self.devices.values()}

    def collect_bridge_uploads(self) -> list[BridgeUpload]:
        return [
            BridgeUpload(d.device_id, pkt)
            for d in self.devices.values() if d.has_internet
            for pkt in d.held_packets()
        ]

    def reset_mesh(self) -> None:
        for d in self.devices.values():
            d.clear()
