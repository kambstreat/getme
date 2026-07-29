# GetME! Studio + Cloud Relay

Videographers sign up on your public URL, paste **one Terminal command** on their Mac, and control everything from the **studio** web page. Processing runs on their laptop; guests use your stable public link.

## Flow

```
1. Videographer → https://your-relay.com/  (signup)
2. Studio       → Copy install command → paste in Mac Terminal
3. GetME starts → studio shows GetME: online
4. Studio       → Connect Google Drive, paste folder link, Start processing
5. Guests       → https://your-relay.com/e/{session-id}/
```

## One process on the laptop

GetME includes the relay client. When `RELAY_URL`, `RELAY_SESSION`, and `RELAY_AGENT_SECRET` are set (the install script writes these), one `uvicorn` process handles photos **and** the cloud connection.

**Python:** 3.10–3.13 only (TensorFlow has no 3.14 wheels). The Mac installer picks `python3.12` / `3.11` / `3.10`, or installs 3.12 via Homebrew if needed.

---

## Deploy relay (you — operator)

Use a **VPS** (not Vercel). The relay needs a long-lived process and WebSockets.

```bash
git clone https://github.com/kambstreat/getme.git
cd getme
python3.12 -m venv .venv   # or 3.10 / 3.11
source .venv/bin/activate
pip install -r requirements-relay.txt

export RELAY_PUBLIC_ORIGIN=https://relay.yourdomain.com
# Optional: ship oauth_client.json to every Mac install
export GETME_OAUTH_CLIENT_URL=https://your-cdn.example.com/oauth_client.json
# Optional: override clone source
# export GETME_REPO=https://github.com/kambstreat/getme.git

python -m relay server --host 127.0.0.1 --port 9000
```

Put HTTPS (Caddy/nginx) in front on port 443. Share **`https://relay.yourdomain.com`** with videographers.

### OAuth (required for Connect Google Drive)

1. Host your Google OAuth web client JSON at a private HTTPS URL → set `GETME_OAUTH_CLIENT_URL` on the relay so the Mac installer downloads `oauth_client.json`.
2. In Google Cloud Console, add redirect URIs per session:

```
https://relay.yourdomain.com/e/{session-id}/api/auth/google/callback
```

3. While the OAuth app is in Testing, add each videographer Gmail as a test user.

---

## Videographer steps (Mac)

1. Open the studio URL you were given → enter event name → **Create session**.
2. On step **1. Run GetME on your Mac**:
   - Open **Terminal**
   - Click **Copy install command**
   - Paste and press Return
3. Wait until the studio pill shows **GetME: online** (first install can take 5–15 minutes).
4. **Connect Google Drive** (same browser tab → Google sign-in → back to studio).
5. Paste the Drive folder link → **Save** → **Start processing**.
6. Share the **guest link**. Keep Terminal open during the event.

If Python is missing, the installer uses Homebrew (`brew install python@3.12`). If Homebrew is missing, it prints the one-line Homebrew install — run that once, then paste the GetME command again.

---

## Local test (your machine)

```bash
# Terminal 1 — relay
export RELAY_PUBLIC_ORIGIN=http://localhost:9000
# optional: export GETME_OAUTH_CLIENT_URL=file URL or https URL to oauth_client.json
python -m relay server --port 9000

# Browser: http://localhost:9000 → create session → copy install command
# Terminal 2: paste the command (or run GetME from this repo with RELAY_* in .env)
```

Checklist:

- [ ] Studio opens after signup  
- [ ] Install command copies with toast “Copied — paste in Terminal”  
- [ ] GetME connects → pill turns green  
- [ ] Connect Google Drive returns to studio  
- [ ] Start processing updates progress in studio  

---

## Operator env reference

| Variable | Purpose |
|----------|---------|
| `RELAY_PUBLIC_ORIGIN` | Public base URL of the relay (must match what videographers open) |
| `GETME_OAUTH_CLIENT_URL` | HTTPS URL to `oauth_client.json` downloaded by the Mac installer |
| `GETME_REPO` | Git clone URL (default: GitHub getme repo) |
| `RELAY_ADMIN_TOKEN` | Optional admin API token |
| `RELAY_REQUEST_TIMEOUT` | Proxy timeout seconds (default 120) |

Laptop-only (written by installer): `RELAY_URL`, `RELAY_SESSION`, `RELAY_AGENT_SECRET`.
