"""
A simulated phone in the mesh. Holds packets it has seen.

In the real system, this state would be on a physical Android device, with
packets exchanged via BLE GATT characteristics.
"""

import threading

from app.schemas import MeshPacket


class VirtualDevice:
    def __init__(self, device_id: str, has_internet: bool):
        self.device_id = device_id
        self.has_internet = has_internet
        self._held_packets: dict[str, MeshPacket] = {}
        self._lock = threading.Lock()

    def hold(self, packet: MeshPacket) -> None:
        with self._lock:
            self._held_packets.setdefault(packet.packet_id, packet)

    def held_packets(self) -> list[MeshPacket]:
        with self._lock:
            return list(self._held_packets.values())

    def holds(self, packet_id: str) -> bool:
        with self._lock:
            return packet_id in self._held_packets

    def packet_count(self) -> int:
        with self._lock:
            return len(self._held_packets)

    def clear(self) -> None:
        with self._lock:
            self._held_packets.clear()
