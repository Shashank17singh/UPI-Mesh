<div align="center">

# 📡 UPI_Mesh — Offline-First Payments over a Bluetooth Mesh

**A payment backend that settles UPI-style transactions with zero internet — hybrid RSA/AES-GCM encryption, a Bluetooth mesh simulator, and idempotent settlement, served through a FastAPI dashboard**

[![Python](https://img.shields.io/badge/Python-3.x-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-REST%20API-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-ORM-D71F00?style=for-the-badge&logo=python&logoColor=white)](https://www.sqlalchemy.org/)
[![Cryptography](https://img.shields.io/badge/RSA%2FAES--GCM-Hybrid%20Encryption-4B8BBE?style=for-the-badge&logoColor=white)](https://cryptography.io/)

</div>

---

## 📖 Overview

UPI_Mesh simulates a UPI payment that has to survive **zero internet connectivity**. A sender's phone encrypts a payment instruction and hands it to a mesh of nearby phones over Bluetooth. The packet hops phone-to-phone with no intermediate ever able to read or forge it, until one phone in the chain regains internet access ("bridge node") and uploads it to the backend — which decrypts, checks for replays and duplicates, and settles the ledger. All of it is served through a FastAPI backend with a live browser dashboard.

---

## ✨ Pipeline

| Stage | What Happens |
|---|---|
| 🔐 **Encrypt** | The sender's phone wraps the payment in RSA-2048 (OAEP/SHA-256) + AES-256-GCM hybrid encryption before it ever leaves the device |
| 🕸️ **Gossip** | Simulated phones relay the encrypted packet to each other over Bluetooth, decrementing a TTL each hop |
| 🌉 **Bridge** | Once a phone with internet holds the packet, it uploads it to the backend as if it just got signal |
| 🔁 **Dedup** | The ciphertext's SHA-256 hash — not the packet ID, which a relay could rewrite — is checked against an idempotency cache so duplicate deliveries settle only once |
| ⏳ **Freshness Check** | Packets signed too long ago are rejected outright, closing the replay window |
| 💰 **Settle** | The backend decrypts, then debits and credits accounts atomically with optimistic locking |
| 📊 **Dashboard** | A live browser UI to send payments, run gossip rounds, flush bridges, and watch the ledger update |

---

## 🛠️ Tech Stack

**Backend** — Python · FastAPI · Uvicorn
**Data** — SQLAlchemy ORM · SQLite · Pydantic
**Security** — `cryptography` (RSA-OAEP + AES-256-GCM)
**Frontend** — HTML · CSS · JavaScript (served via Jinja2)
**Testing** — pytest · GitHub Actions CI

---

## 📂 Directory Structure

```
UPI_Mesh/
│
├── app/
│   ├── main.py                       # FastAPI app + routes
│   ├── models.py                     # SQLAlchemy models (accounts, transactions)
│   ├── schemas.py                    # Pydantic DTOs (wire format)
│   ├── database.py                   # Engine/session setup
│   ├── crypto_service.py             # Hybrid RSA + AES-GCM encrypt/decrypt/hash
│   ├── idempotency_service.py        # Thread-safe dedup cache with TTL eviction
│   ├── settlement_service.py         # Ledger debit/credit, optimistic locking
│   ├── mesh_simulator_service.py     # Gossip simulation across virtual phones
│   ├── virtual_device.py             # A single simulated phone
│   ├── bridge_ingestion_service.py   # decrypt → dedup → freshness → settle pipeline
│   ├── demo_service.py               # Seed accounts + build sample packets
│   └── templates/dashboard.html      # Live dashboard UI
│
├── tests/                            # pytest suite (27 tests)
├── .github/workflows/ci.yml          # CI across Python 3.10–3.12
├── requirements.txt
├── requirements-dev.txt
└── README.md                         # You are here
```

---

## ⚙️ Setup and Installation

### Prerequisites

- Python 3.x
- pip

### 1. Clone the repository

```bash
git clone https://github.com/Shashank17singh/UPI_Mesh.git
cd UPI_Mesh
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Start the server

```bash
uvicorn app.main:app --reload --port 8080
```

### 4. Open the dashboard

Once the server is running, open `http://localhost:8080` in your browser. Compose a payment, run gossip rounds, flush bridge nodes, and watch the mesh state and ledger update live.

---

## 📡 API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/server-key` | Fetch the server's RSA public key |
| `POST` | `/api/demo/send` | Simulate a sender phone creating and injecting a packet |
| `GET` | `/api/mesh/state` | What each simulated device currently holds |
| `POST` | `/api/mesh/gossip` | Run one round of phone-to-phone packet exchange |
| `POST` | `/api/mesh/flush` | Bridge nodes upload everything they hold (parallelized, to exercise idempotency under concurrency) |
| `POST` | `/api/mesh/reset` | Clear the mesh and idempotency cache |
| `POST` | `/api/bridge/ingest` | The production endpoint — headers `X-Bridge-Node-Id`, `X-Hop-Count` |
| `GET` | `/api/accounts` | List demo accounts and balances |
| `GET` | `/api/transactions` | Last 20 settled/rejected transactions |

### Example: send a demo payment via curl

```bash
curl -X POST http://localhost:8080/api/demo/send \
  -H "Content-Type: application/json" \
  -d '{"sender_vpa":"alice@demo","receiver_vpa":"bob@demo","amount":500,"pin":"1234","ttl":5,"start_device":"phone-alice"}'
```

---

## 🧪 Running the Tests

```bash
pip install -r requirements-dev.txt
pytest -v
```

27 tests cover the crypto round-trip and tamper detection, idempotency claim/evict semantics, ledger debit/credit correctness, mesh gossip/TTL behavior, and the full decrypt → dedup → freshness → settle pipeline.

---

## 🔬 Design Notes

- **Why hash the ciphertext, not the packet ID, for idempotency?** An intermediate phone can freely rewrite the outer `packet_id`; it cannot forge a ciphertext that decrypts to a different valid payload. Two delivered copies of the same encrypted packet always hash identically.
- **Why optimistic locking on accounts?** The idempotency layer should always catch duplicates first, but a version column on `Account` means a race that somehow slips past it fails loudly (`StaleDataError`) instead of silently corrupting a balance.
- **SQLite gotcha:** autoincrement primary keys on SQLite only work with a plain `Integer` column — a `BigInteger` primary key silently stays `NULL` on insert.

---

## 📜 License

MIT — see [LICENSE](LICENSE).
