"""
FastAPI application entrypoint — wires up the singleton services and
exposes the HTTP routes.

Endpoint groups:
  /                      -> dashboard page
  /api/server-key        -> so simulated senders can fetch the server's public key
  /api/demo/*            -> demo helpers
  /api/mesh/*            -> simulator endpoints (state, gossip, flush, reset)
  /api/bridge/ingest     -> THE real production endpoint a real bridge node would hit
  /api/accounts          -> for the dashboard
  /api/transactions      -> for the dashboard
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.bridge_ingestion_service import BridgeIngestionService
from app.crypto_service import HybridCryptoService, ServerKeyHolder
from app.database import Base, SessionLocal, engine, get_db
from app.demo_service import DemoService
from app.idempotency_service import IdempotencyService
from app.mesh_simulator_service import MeshSimulatorService
from app.models import Account, Transaction
from app.schemas import DemoSendRequest, MeshPacket
from app.settlement_service import SettlementService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)-5s %(name)s - %(message)s",
)

# ----------------------------------------------------------------------
# Singleton services — constructed once at import time and shared across
# requests, since none of them hold per-request state.
# ----------------------------------------------------------------------
IDEMPOTENCY_TTL_SECONDS = 86400
PACKET_MAX_AGE_SECONDS = 86400

server_key = ServerKeyHolder()
crypto = HybridCryptoService(server_key)
idempotency = IdempotencyService(ttl_seconds=IDEMPOTENCY_TTL_SECONDS)
settlement = SettlementService()
mesh = MeshSimulatorService()
bridge = BridgeIngestionService(crypto, idempotency, settlement, max_age_seconds=PACKET_MAX_AGE_SECONDS)
demo = DemoService(crypto)

_bridge_upload_pool = ThreadPoolExecutor(max_workers=8)


def _eviction_loop():
    """Background housekeeping thread — periodically evicts idempotency
    entries past their TTL so the cache doesn't grow forever."""
    while True:
        time.sleep(60)
        idempotency.evict_expired()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        demo.seed_accounts(db)
    threading.Thread(target=_eviction_loop, daemon=True).start()
    log = logging.getLogger("upimesh.startup")
    log.info(
        "Server RSA keypair generated (2048-bit). Public key fingerprint: %s...",
        server_key.public_key_base64()[:32],
    )
    yield


app = FastAPI(title="UPI Offline Mesh — Demo", lifespan=lifespan)
templates = Jinja2Templates(directory="app/templates")


# ------------------------------------------------------------------ dashboard

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


# ------------------------------------------------------------------ key

@app.get("/api/server-key")
def get_server_public_key():
    return {
        "publicKey": server_key.public_key_base64(),
        "algorithm": "RSA-2048 / OAEP-SHA256",
        "hybridScheme": "RSA-OAEP encrypts an AES-256-GCM session key",
    }


# ---------------------------------------------------------------- demo

@app.post("/api/demo/send")
def demo_send(req: DemoSendRequest):
    """Demo helper: build a packet on the server (simulating a sender
    phone) and inject it into the mesh at the given device."""
    packet = demo.create_packet(
        req.sender_vpa, req.receiver_vpa, req.amount, req.pin, req.ttl or 5
    )

    start_device = req.start_device or "phone-alice"
    mesh.inject(start_device, packet)

    return {
        "packetId": packet.packet_id,
        "ciphertextPreview": packet.ciphertext[:64] + "...",
        "ttl": packet.ttl,
        "injectedAt": start_device,
    }


# -------------------------------------------------------------- mesh sim

@app.get("/api/mesh/state")
def mesh_state():
    device_data = []
    for d in mesh.get_devices():
        device_data.append({
            "deviceId": d.device_id,
            "hasInternet": d.has_internet,
            "packetCount": d.packet_count(),
            "packetIds": [p.packet_id[:8] for p in d.held_packets()],
        })
    return {
        "devices": device_data,
        "idempotencyCacheSize": idempotency.size(),
    }


@app.post("/api/mesh/gossip")
def mesh_gossip():
    result = mesh.gossip_once()
    return {"transfers": result.transfers, "deviceCounts": result.device_counts}


@app.post("/api/mesh/flush")
def mesh_flush():
    """"All bridge nodes simultaneously walk outside and get 4G." They
    all upload everything they hold to /api/bridge/ingest.

    THIS is the moment the duplicate-storm idempotency case is tested: if
    multiple bridge nodes hold the same packet, the server gets multiple
    concurrent uploads of the same ciphertext, and only one should
    settle. Uploads run in parallel (thread pool) so this actually
    exercises concurrent idempotency, not just sequential dedup.
    """
    uploads = mesh.collect_bridge_uploads()

    def process(upload):
        with SessionLocal() as db:
            r = bridge.ingest(db, upload.packet, upload.bridge_node_id, 5 - upload.packet.ttl)
        return {
            "bridgeNode": upload.bridge_node_id,
            "packetId": upload.packet.packet_id[:8],
            "outcome": r.outcome,
            "reason": r.reason or "",
            "transactionId": r.transaction_id if r.transaction_id is not None else -1,
        }

    results = list(_bridge_upload_pool.map(process, uploads))

    return {"uploadsAttempted": len(uploads), "results": results}


@app.post("/api/mesh/reset")
def mesh_reset():
    mesh.reset_mesh()
    idempotency.clear()
    return {"status": "mesh and idempotency cache cleared"}


# -------------------------------------------------------------- bridge

@app.post("/api/bridge/ingest")
def ingest(
    packet: MeshPacket,
    x_bridge_node_id: str = Header(default="unknown"),
    x_hop_count: int = Header(default=0),
    db: Session = Depends(get_db),
):
    """THE PRODUCTION ENDPOINT. In a real deployment, the Android app's
    bridge logic POSTs here whenever the device has internet and is
    holding mesh packets."""
    r = bridge.ingest(db, packet, x_bridge_node_id, x_hop_count)
    return r


# ------------------------------------------------------------- accounts

@app.get("/api/accounts")
def list_accounts(db: Session = Depends(get_db)):
    accounts = db.query(Account).all()
    return [
        {"vpa": a.vpa, "holderName": a.holder_name, "balance": str(a.balance)}
        for a in accounts
    ]


@app.get("/api/transactions")
def list_transactions(db: Session = Depends(get_db)):
    txs = db.query(Transaction).order_by(Transaction.id.desc()).limit(20).all()
    return [
        {
            "id": t.id,
            "senderVpa": t.sender_vpa,
            "receiverVpa": t.receiver_vpa,
            "amount": str(t.amount),
            "status": t.status.value,
            "bridgeNodeId": t.bridge_node_id,
            "hopCount": t.hop_count,
            "settledAt": t.settled_at.isoformat(),
        }
        for t in txs
    ]
