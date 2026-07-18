"""
Simulates the Bluetooth mesh.

Each VirtualDevice represents a phone. The "gossip" step picks pairs of
devices that are nearby (we just say all devices are nearby for the demo)
and copies packets between them, decrementing TTL each hop.

When a device with internet (a "bridge node") holds a packet, the demo's
/api/mesh/flush endpoint causes it to actually POST that packet to our
backend — simulating the moment a phone walks outside and gets 4G.
"""

import logging
from dataclasses import dataclass
from typing import Optional

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
        # Default scenario: 4 offline phones in a basement, 1 phone outside with 4G
        for device_id in ("phone-alice", "phone-stranger1", "phone-stranger2", "phone-stranger3"):
            self.devices[device_id] = VirtualDevice(device_id, has_internet=False)
        self.devices["phone-bridge"] = VirtualDevice("phone-bridge", has_internet=True)

    def get_devices(self) -> list[VirtualDevice]:
        return list(self.devices.values())

    def get_device(self, device_id: str) -> Optional[VirtualDevice]:
        return self.devices.get(device_id)

    def inject(self, sender_device_id: str, packet: MeshPacket) -> None:
        """Sender drops a packet into the mesh by handing it to their own
        device."""
        sender = self.devices.get(sender_device_id)
        if sender is None:
            raise ValueError(f"Unknown device: {sender_device_id}")
        sender.hold(packet)
        log.info("Packet %s injected at %s (TTL=%s)", packet.packet_id[:8], sender_device_id, packet.ttl)

    def gossip_once(self) -> GossipResult:
        """One round of gossip. Every device shares everything it has with
        every other device. TTL is decremented per hop; packets at TTL 0
        stay where they are but are not forwarded further.

        Real BLE gossip would be pair-by-pair when devices come into
        range. For the demo we let everyone gossip with everyone in one
        round, which is equivalent to "fast-forward N rounds of pairwise
        gossip"."""
        transfers = 0
        device_list = list(self.devices.values())

        # Snapshot what each device holds at the start of this round, so we
        # don't gossip the same packet through 5 devices in 1 step.
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
        """Returns all packets held by devices with internet — these are
        what would be uploaded to the backend the moment they reach
        connectivity."""
        out: list[BridgeUpload] = []
        for d in self.devices.values():
            if not d.has_internet:
                continue
            for pkt in d.held_packets():
                out.append(BridgeUpload(d.device_id, pkt))
        return out

    def reset_mesh(self) -> None:
        for d in self.devices.values():
            d.clear()
