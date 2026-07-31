# GetME!

Scan your face, get your photos.

GetME! is a small FastAPI web app for events. An organizer points it at a Google
Drive folder of high-quality photos; the app streams each photo, detects faces
with **ArcFace** (via DeepFace + RetinaFace), and groups them into people. Guests
then upload a selfie and instantly get a gallery of every photo they appear in,
plus a one-click ZIP download.

Everything runs **locally on your machine** - photos stay in Google Drive and are
streamed on demand, so nothing is copied to disk. Expose it to guests with a
managed tunnel (ngrok or Cloudflare Tunnel).

## How it works

```
Drive folder -> stream each image -> detect + embed faces (ArcFace)
            -> cluster into people (agglomerative) -> store centroids + file ids (SQLite)

Guest selfie -> embed -> cosine match vs centroids -> token
            -> in-session thumbnail gallery + Download all (ZIP), streamed from Drive
```

## Continuous Processing (Polling Mode)

**NEW**: GetME! now supports continuous monitoring for new images added to your Drive folder.

### Two Processing Modes

1. **Full Processing** (default): Processes all images in the folder, resets clusters
2. **Incremental Processing**: Only processes new images, merges with existing clusters

### Polling Feature

Start continuous monitoring:
```bash
POST /api/drive/polling/start
{
  "drive_link": "https://drive.google.com/...",
  "interval_seconds": 300  // Check every 5 minutes (60-3600s range)
}
```

Stop polling:
```bash
POST /api/drive/polling/stop
```

Check polling status:
```bash
GET /api/drive/polling/status
```

### How It Works

When polling is active:
- GetME! checks the Drive folder at regular intervals (default: 5 minutes)
- Only new images are downloaded and processed
- New faces are intelligently merged into existing clusters
- Previously processed images are tracked in the database and skipped
- No data is lost - the system incrementally updates clusters

### Use Cases

- **Live Events**: Start polling before the event, and new photos uploaded by photographers are automatically processed
- **Multi-Day Events**: Keep polling active across days as new photos arrive
- **Continuous Updates**: Perfect for events where photos trickle in over time

### Manual Incremental Processing

You can also manually trigger incremental processing:
```bash
POST /api/drive/process
{
  "drive_link": "https://drive.google.com/...",
  "incremental": true
}
```

## Project layout

```
app/
  main.py              FastAPI entry point (serves pages + mounts routers)
  config.py            Settings (env / .env)
  routers/
    drive.py           POST /api/drive/process, GET /api/drive/status/{job_id}
                       POST /api/drive/polling/start, /stop, GET /status
    local.py           GET /api/local/status, POST /api/local/process (folder photos)
    match.py           POST /api/match, gallery/thumb/download endpoints
    clusters.py        GET /clusters, GET /api/clusters (people viewer)
  services/
    drive_service.py   Drive link parsing, listing, in-memory streaming
    local_photos.py    List/stream images from LOCAL_PHOTOS_DIR
    face_service.py    Detection, ArcFace embeddings, quality filter, clustering (+ incremental)
    processing.py      Background job orchestration, polling, status registry
    match_service.py   Selfie matching, thumbnails, ZIP streaming
  database/db.py       SQLite: clusters, cluster_files, tokens, processed_files
  models/schemas.py    Pydantic models
static/                index.html (guest), admin.html (organizer), clusters.html, css/js
test-photos/           Demo images for Drive-free local clustering
```

## Setup

1. **Python 3.10–3.13** required (TensorFlow has no wheels for 3.14 yet). Create a virtualenv and install deps:

   ```bash
   git clone https://github.com/kambstreat/getme.git
   cd getme
   # Prefer an explicit version if `python3` is 3.14+:
   python3.12 -m venv .venv   # or python3.11 / python3.10
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

   The first face operation downloads the ArcFace + RetinaFace weights (~hundreds of MB).
   Optionally pre-warm:

   ```bash
   python -c "from deepface import DeepFace; DeepFace.build_model('ArcFace')"
   ```

2. Google Drive access (read-only). Two options:

   **Option A - "Sign in with Google" (recommended).** One-time setup by the
   developer; organizers just click Connect and log in:

   1. In [Google Cloud Console](https://console.cloud.google.com), create a
      project and enable the **Google Drive API**.
   2. Configure the **OAuth consent screen**: User type *External*, publishing
      status *Testing*. Add each organizer's Gmail address under **Test users**
      (max 100).
   3. Create an **OAuth client ID** of type *Web application*, and add
      `http://localhost:8000/api/auth/google/callback` to **Authorized redirect
      URIs**.
   4. Download the client secrets JSON and save it as `oauth_client.json` in the
      project root (or set `GOOGLE_OAUTH_CLIENT_FILE`).
   5. Start the app, open `/admin`, enter the admin token, and click
      **Connect Google Drive**.

   Note: while the OAuth app is in *Testing* status, Google expires refresh
   tokens after **7 days** - reconnect weekly (one click). Publishing the app
   removes this limit but requires Google's restricted-scope verification.

   **Option B - service account (fallback).** Create a **service account**,
   enable the Drive API, download its JSON key, and **share the photo folder**
   with the service account's email. Save the key as `service_account.json`
   (or set `GOOGLE_SERVICE_ACCOUNT_FILE`). Used automatically when no Google
   account is connected.

3. Configure the app:

   ```bash
   cp .env.example .env
   # edit .env — at minimum set ADMIN_TOKEN
   # leave RELAY_URL / RELAY_SESSION / RELAY_AGENT_SECRET empty for pure local use
   # optional: LOCAL_PHOTOS_DIR=test-photos (default) for Drive-free testing
   ```

## Running locally

Fastest path: cluster the demo images in `test-photos/` (no Google Drive).

### 1. Start the server

From the repo root, with the venv activated and `ADMIN_TOKEN` set in `.env`:

```bash
# Pure local (no cloud relay):
env RELAY_URL= RELAY_SESSION= RELAY_AGENT_SECRET= \
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Or, if your `.env` has no `RELAY_*` values:

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Leave that terminal open. Stop with `Ctrl+C`.

### 2. Cluster `test-photos/`

The repo ships demo images under [`test-photos/`](test-photos/) (Tom Cruise ×3, Zendaya ×2).
`LOCAL_PHOTOS_DIR` defaults to that folder.

1. Open **Admin**: [http://127.0.0.1:8000/admin](http://127.0.0.1:8000/admin)
2. Enter the `ADMIN_TOKEN` from your `.env`.
3. Click **Process local folder**.

That runs face detection + ArcFace embeddings and agglomerative clustering
(`CLUSTER_EPS`, default `0.4`). Wait until the admin status shows the job finished
(first run also downloads model weights).

Optional — same step via curl:

```bash
curl -X POST http://127.0.0.1:8000/api/local/process \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" \
  -d '{}'
```

Check what the folder contains:

```bash
curl -s http://127.0.0.1:8000/api/local/status
```

To use your own images instead, drop JPG/PNG/WebP files into `test-photos/`
(or set `LOCAL_PHOTOS_DIR` in `.env`) and process again.

### 3. View clusters

After processing finishes, open the people viewer:

**[http://127.0.0.1:8000/clusters](http://127.0.0.1:8000/clusters)**

You should see one group per person (for the demo set: Cruise and Zendaya), with
face crops and links back to the source photos in `test-photos/`.

### Other local URLs

| Page | URL |
|------|-----|
| Guest (selfie match) | [http://127.0.0.1:8000/](http://127.0.0.1:8000/) |
| Admin (process folder / Drive) | [http://127.0.0.1:8000/admin](http://127.0.0.1:8000/admin) |
| Clusters (people + crops) | [http://127.0.0.1:8000/clusters](http://127.0.0.1:8000/clusters) |
| Health | [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) |

Try a selfie on the Guest page after clustering — gallery thumbs and ZIP downloads
read from the same local folder (no Drive needed).

### Running with Google Drive

1. Open [Admin](http://127.0.0.1:8000/admin), enter `ADMIN_TOKEN`.
2. **Connect Google Drive** (OAuth) if not using a service account.
3. Paste a Drive folder link and start processing (full or incremental).
4. Review people at [http://127.0.0.1:8000/clusters](http://127.0.0.1:8000/clusters).
5. Open the Guest page, upload a selfie, and confirm matched photos.

### Expose to guests with a tunnel

```bash
# ngrok
ngrok http 8000

# or Cloudflare Tunnel
cloudflared tunnel --url http://localhost:8000
```

Share the public URL (a QR code works great at events). Stop the tunnel to take
the app offline.

### Cloud relay (recommended for videographers)

Deploy a small relay server with a **stable public URL**; processing still runs on
the videographer's laptop. See **[RELAY.md](RELAY.md)** for VPS setup, Mac one-command
install, and `GETME_OAUTH_CLIENT_URL`. Use `requirements-relay.txt` on the cloud (no TensorFlow).


## Configuration reference

See `.env.example`. Key knobs:

| Setting | Meaning | Default |
|---------|---------|---------|
| `MATCH_THRESHOLD` | Min cosine similarity for a selfie match | `0.50` |
| `CLUSTER_EPS` | Agglomerative cosine-distance threshold (lower = stricter) | `0.4` |
| `CLUSTER_MIN_SAMPLES` | Legacy setting (unused by agglomerative clustering) | `2` |
| `MIN_FACE_WIDTH_FRACTION` | Drop faces narrower than this fraction of image width | `0.03` |
| `MIN_FACE_CONFIDENCE` | Drop low-confidence detections | `0.50` |
| `ADMIN_TOKEN` | Shared secret guarding admin/process endpoints | `change-me` |
| `LOCAL_PHOTOS_DIR` | Folder of JPGs for local testing (Admin → Process local folder) | `test-photos` |
| `TOKEN_TTL_SECONDS` | Lifetime of a guest's download token | `86400` |

## Scope & future work

Current scope is the **live-event flow**: scan, gallery, ZIP. Designed but
deferred: durable delivery after shutdown (capture email/phone, grant each guest
read access to only their matched files via the Drive API, and send Drive links
via email / WhatsApp / SMS).

## Notes

- Selfies are processed in memory and never stored.
- Keep the admin token secret; the app is publicly reachable through the tunnel.
- Processing ~2k photos on a multi-core CPU takes roughly 15-25 minutes; matching is instant.
