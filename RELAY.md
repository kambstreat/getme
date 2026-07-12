# GetME! Studio + Cloud Relay

Videographers sign up on your public URL, run one install command, and control everything from the **studio** web page. **GetME! is the agent** — one process on the laptop handles photos and the cloud connection.

## Flow

```
1. Videographer → https://your-relay.com/  (signup)
2. Studio page  → copy install command, run once in Terminal
3. GetME starts   → connects to cloud automatically (built-in relay client)
4. Studio       → Connect Google Drive, paste folder link, Start processing
5. Guests       → https://your-relay.com/e/{session-id}/
```

## One process on the laptop

Previously: agent + GetME (two programs).  
Now: **only GetME** (`uvicorn app.main:app`). When `RELAY_URL`, `RELAY_SESSION`, and `RELAY_AGENT_SECRET` are set, it connects to your relay over WebSocket and proxies guest/admin traffic — no separate agent process.

**Python:** GetME needs **3.10–3.13** (not 3.14). The install script picks `python3.12` / `3.11` / `3.10` if available.

## Deploy relay (you)

```bash
export RELAY_PUBLIC_ORIGIN=https://relay.yourdomain.com
python -m relay server --port 9000
```

Put HTTPS (Caddy/nginx) in front on port 443.

Add OAuth redirect per session in Google Cloud:

```
https://relay.yourdomain.com/e/{session-id}/api/auth/google/callback
```

## Local test

```bash
# Terminal 1 — relay + studio UI
RELAY_PUBLIC_ORIGIN=http://localhost:9000 python -m relay server --port 9000

# Browser: http://localhost:9000 → create session → run install command

# Or manually:
RELAY_URL=http://localhost:9000 RELAY_SESSION=YOUR-SESSION RELAY_AGENT_SECRET=YOUR-SECRET \\
  uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Videographer experience

1. Open your public URL, enter event name → **Create session**
2. **Run install command** in Terminal (one time per machine)
3. Wait for **Agent: online** in studio
4. **Connect Google Drive** → paste folder link → **Start processing**
5. Share **guest link** with attendees

The install script clones GetME, sets relay env vars in `.env`, and starts uvicorn. Leave that Terminal window open during the event.
