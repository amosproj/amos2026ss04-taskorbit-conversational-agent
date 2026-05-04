# LiveKit Cloud — Developer Setup

This document covers the developer setup for the LiveKit Cloud
integration delivered in ticket
[#26](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/issues/26):

1. Get LiveKit Cloud credentials.
2. Configure the backend and frontend environment files.
3. Run the stack.
4. Verify the token endpoint.
5. Verify an end-to-end browser → backend → LiveKit Cloud connection.

The companion piece is the system architecture documented in
[#12](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/issues/12) —
the token issuance flow described here is the "client + realtime layer"
of that diagram.

> **Scope.** This is the *infrastructure* slice. Audio publish/subscribe
> over LiveKit lives in tickets #14 (STT) and #15 (TTS); the agent worker
> that joins rooms server-side lives in `backend/src/taskorbit/livekit_agent/`
> and is owned by a downstream ticket.

---

## 1. Prerequisites

- A LiveKit Cloud account — sign up at [cloud.livekit.io](https://cloud.livekit.io). The free tier is more than enough for development.
- Docker Desktop running (the dev environment is containerised; see [#17](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/issues/17)).
- Read access to this repo and the `feature/setup-livekit-infrastructure` branch (or `main` once #26 is merged).

---

## 2. Get your LiveKit Cloud credentials

You need three values:

| Variable | What it is |
|---|---|
| `LIVEKIT_URL` | The WebSocket URL of your LiveKit Cloud project, e.g. `wss://your-project.livekit.cloud` |
| `LIVEKIT_API_KEY` | The public part of an API key pair, e.g. `APIxxxxxxxxxxxxx` |
| `LIVEKIT_API_SECRET` | The corresponding secret. **Shown once at creation** — copy it immediately. |

### How to generate them

1. Sign in to [cloud.livekit.io](https://cloud.livekit.io).
2. In the left sidebar go to **Settings → API keys**.
3. Click **Create key** (top right).
4. Give it a description (e.g. `taskorbit-dev`) and confirm.
5. The dialog displays both the **API Key** and the **API Secret**. Copy both into a temporary note immediately. The secret will not be shown again.
6. To find the **WebSocket URL**, open the **Overview** page or **Settings → Project**. The URL has the form `wss://<project-handle>.livekit.cloud`.

### One key per developer

LiveKit Cloud lets each project member generate their own keys. Generate
your own — do not share keys between developers. The "Owner" column on
the API keys page shows whose key it is.

---

## 3. Configure the environment files

Both files are git-ignored. Never commit real values.

### `backend/.env`

```bash
cd backend
cp .env.example .env
```

Then open `backend/.env` and fill in the LiveKit section:

```env
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxxxxx
LIVEKIT_API_SECRET=your-long-secret-string
```

**Format rules:** no quotes around the values, no spaces around `=`, no
trailing whitespace. Save the file.

### `frontend/.env.local`

```bash
cd frontend
cp .env.example .env.local   # if you don't already have it
```

Set `VITE_LIVEKIT_URL` to the **same** WebSocket URL you used in
`backend/.env`:

```env
VITE_LIVEKIT_URL=wss://your-project.livekit.cloud
```

The frontend never sees `LIVEKIT_API_KEY` or `LIVEKIT_API_SECRET` —
those stay on the backend. The frontend only needs the URL so the
LiveKit client knows where to connect after the backend hands it a
signed token.

---

## 4. Run the stack

From the repository root:

```bash
docker compose up --build
```

The first build is slow (~5 minutes) — Poetry resolves Python deps and
npm installs the frontend bundle. Subsequent builds are cached and take
seconds.

A healthy startup looks like:

```
Container taskorbit-postgres   Healthy
Container taskorbit-backend    Healthy
Container taskorbit-frontend   Started
taskorbit-backend  | INFO  api_starting env=development version=0.1.0 host=0.0.0.0 port=8000
taskorbit-backend  | Uvicorn running on http://0.0.0.0:8000
taskorbit-frontend |   ➜  Local:   http://localhost:5173/
```

Service URLs:

| Service | URL |
|---|---|
| Backend (FastAPI) | http://localhost:8000 |
| OpenAPI docs | http://localhost:8000/docs |
| Frontend (Vite) | http://localhost:5173 |
| Postgres | `localhost:5432` (user `taskorbit`, db `taskorbit`) |

---

## 5. Verify the token endpoint

In a second terminal — leave the compose terminal running — request a
token from the backend:

```bash
curl -s -X POST http://localhost:8000/v1/livekit/token \
  -H "Content-Type: application/json" \
  -d '{"identity":"dev-user","room":"taskorbit-dev-room"}'
```

A successful response returns four fields:

```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ...long.string",
  "url": "wss://your-project.livekit.cloud",
  "room": "taskorbit-dev-room",
  "identity": "dev-user"
}
```

### Decode the token to verify the claims

To confirm the token is signed correctly and scoped to the right room
and identity, decode the middle segment of the JWT:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/v1/livekit/token \
  -H "Content-Type: application/json" \
  -d '{"identity":"dev-user","room":"taskorbit-dev-room"}' | \
  sed -n 's/.*"token":"\([^"]*\)".*/\1/p')

PAYLOAD=$(echo "$TOKEN" | cut -d. -f2)
PADDED="$PAYLOAD$(printf '%*s' $(( (4 - ${#PAYLOAD} % 4) % 4 )) '' | tr ' ' '=')"
echo "$PADDED" | tr '_-' '/+' | base64 -D 2>/dev/null | python3 -m json.tool
```

Expected payload:

```json
{
    "video": {
        "roomJoin": true,
        "room": "taskorbit-dev-room",
        "canPublish": true,
        "canSubscribe": true,
        "canPublishData": true
    },
    "sub": "dev-user",
    "iss": "APIxxxxxxxxxxxxx",
    "nbf": 1777900000,
    "exp": 1777921600
}
```

What to check:

- `iss` matches your `LIVEKIT_API_KEY` from `backend/.env`.
- `sub` and `video.room` match the values you sent in the request body.
- `exp - nbf == 21600` (the backend signs tokens with a 6-hour TTL).
- `video.roomJoin`, `canPublish`, `canSubscribe` are all `true`.

If any of those are wrong, the credentials in `backend/.env` are likely
out of sync with the LiveKit project the URL points at.

---

## 6. Verify end-to-end connection from the browser

This is the proof that the full path works: browser → Vite proxy →
backend → LiveKit Cloud signal handshake.

1. Open http://localhost:5173 in a browser.
2. Open DevTools (Cmd+Option+I on macOS, F12 on Windows/Linux) and switch to the **Console** tab.
3. Paste the following snippet and press Enter:

```javascript
(async () => {
  const res = await fetch("/api/v1/livekit/token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identity: "dev-browser", room: "dev-browser-room" }),
  });
  if (!res.ok) {
    console.error("Token request failed:", res.status, await res.text());
    return;
  }
  const { token, url } = await res.json();
  const { Room, RoomEvent } = await import(
    "/node_modules/livekit-client/dist/livekit-client.esm.mjs"
  );
  const room = new Room();
  window.__lkRoom = room;
  room
    .on(RoomEvent.SignalConnected, () => console.log("Signal connected"))
    .on(RoomEvent.Connected, () => console.log("✅ CONNECTED to LiveKit Cloud."))
    .on(RoomEvent.Disconnected, (r) => console.log("Disconnected:", r));
  await room.connect(url, token, { autoSubscribe: false });
  console.log("State:", room.state, "| identity:", room.localParticipant.identity);
})();
```

A successful run prints:

```
Signal connected
✅ CONNECTED to LiveKit Cloud.
State: connected | identity: dev-browser
```

When you see this line you can also open the **Sessions** tab in the
LiveKit Cloud dashboard and the `dev-browser-room` room will be visible
with a live participant.

Disconnect cleanly when done so you do not consume free-tier minutes:

```javascript
await window.__lkRoom.disconnect();
```

---

## 7. Troubleshooting

### `503 Service Unavailable` from `/v1/livekit/token`

Body says *"LiveKit is not configured on this server."*

The backend cannot read one or more of `LIVEKIT_URL`, `LIVEKIT_API_KEY`,
`LIVEKIT_API_SECRET` from its environment. Check:

- `backend/.env` exists and contains all three variables with non-empty values.
- The Docker container picked up the file. After editing `backend/.env`, restart compose so the backend container re-reads the file:

  ```bash
  docker compose restart backend
  ```

### `422 Unprocessable Entity` from `/v1/livekit/token`

The request body is missing `identity` or `room`, or one of them is the
empty string. Both fields are required and must be 1–128 characters.

### `connect failed: invalid token` from `livekit-client`

The token signature is valid but LiveKit Cloud rejected it. The most
common cause: `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` and `LIVEKIT_URL`
are from **different projects**. Verify all three values come from the
same project in the LiveKit Cloud dashboard.

### `ECONNREFUSED` errors in the frontend container logs

The Vite proxy cannot reach the backend service. This usually means a
docker-compose configuration issue rather than an application bug — see
the dev-environment ticket
[#17](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/issues/17)
for the canonical fix.

### Token connects, then immediately disconnects

Either the token has already expired (the backend signs with a 6-hour
TTL, so this is unusual unless the system clock is far off), or the
`iss` claim does not match a valid project key. Re-run the decode step
in §5 and double-check the values.

---

## 8. Where the code lives

| File | Role |
|---|---|
| `backend/src/taskorbit/api/routes/livekit.py` | The `POST /v1/livekit/token` route |
| `backend/src/taskorbit/types.py` | `LiveKitTokenRequest` / `LiveKitTokenResponse` Pydantic models |
| `backend/src/taskorbit/config.py` | `Settings` — reads the `LIVEKIT_*` env vars |
| `backend/tests/test_livekit_route.py` | Unit tests covering the route |
| `frontend/src/lib/livekitToken.ts` | The frontend's typed client for the token endpoint |
| `backend/.env.example` | Template that lists every required environment variable |
| `frontend/.env.example` | Frontend env template |

---

## 9. References

- Ticket [#26 — Setup LiveKit Infrastructure](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/issues/26)
- Ticket [#12 — System Architecture](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/issues/12)
- LiveKit Cloud documentation — [docs.livekit.io](https://docs.livekit.io/)
- `livekit-api` Python SDK — [github.com/livekit/python-sdks](https://github.com/livekit/python-sdks)
- `livekit-client` JS SDK — [github.com/livekit/client-sdk-js](https://github.com/livekit/client-sdk-js)
