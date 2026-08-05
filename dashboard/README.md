# mpopbot dashboard

A web management interface for the mpopbot Discord bot. Log in with Discord and
edit the companies, groups, albums, and members you own — changes hit the running
bot immediately, because the dashboard talks to the bot's live in-memory state.

Authentication, an overview, and editing of group details/fandom/members and
album cover/era images — including **direct image upload with an in-browser crop
editor** (pick from your device/gallery, position and zoom, save). It does not
touch game logic, and the bot always remains the only process that runs the game
— this is an external admin panel, never a bot runner.


## How it fits together

```
Browser ──► Cloudflare Pages (this project)
              static UI  +  Pages Functions
                              /auth/*  Discord OAuth  (holds client secret)
                              /api/*   proxy, adds shared secret + your user id
                                 │
                                 ▼  Cloudflare Tunnel
                           Bot process  (dashboard_api.py, in the bot's event loop)
                                 └─ scopes every response to what you own,
                                    using the same ownership rules as the slash commands
```

Why this shape:

- The bot keeps all data **in memory** and owns `data.json`. Editing the file
  from outside would be overwritten by the bot's next save and never seen live.
  So the dashboard talks to the running bot, not its file.
- The bot API runs **inside the bot's event loop**, so it shares state with the
  commands with no locking and edits are immediate.
- Discord's client secret and the bot's shared secret live **only** in Pages
  Functions, never in the browser.

## Editable vs read-only

The dashboard edits **metadata** only — the tedious-to-type-in-Discord stuff:

- **Groups:** korean name, description, fandom name, fandom color, profile
  picture, banner.
- **Albums:** cover image, era image, title track.
- **Members:** name, image, bio.

Game state (streams, sales, wins, popularity, funds, member levels/skills,
buildings, tiers) is **read-only** here and stays under the bot's control. The
API rejects any attempt to edit a field outside the allow-list.

### Image upload

Image fields are set by uploading a file, not by pasting a URL. You pick an image
from your device or gallery, crop and position it in the browser (fixed aspect
per field: square covers/avatars, wide banners, 16:9 era images, 3:4 member
photos), and it uploads. The flow:

1. The browser crops to a compressed WebP entirely client-side (no image library
   on the server) and POSTs the bytes to `/api/upload`.
2. That function stores the object in **Cloudflare R2** and then calls the bot's
   normal PATCH endpoint to point the field at the new URL — so uploads are
   ownership-checked exactly like text edits, and **no bot change is needed**.
3. If the bot rejects the change, the stored object is deleted, so there are no
   orphans.

R2 is used rather than Discord's CDN because Discord attachment URLs now expire.

**One-time R2 setup:**

```
npx wrangler r2 bucket create mpopbot-media
```

Enable public access on the bucket (or attach a custom domain), and set
`R2_PUBLIC_URL` to that public base. The `MEDIA` binding in `wrangler.toml`
already points functions at the bucket.

## Setup

### 1. Bot side (already added to the bot)

`dashboard_api.py` starts automatically from the bot's `setup_hook`, but only if
these are set in the **bot's** `.env`:

```
DASHBOARD_API_SECRET=<long random string>   # required to enable the API
DASHBOARD_API_HOST=127.0.0.1                 # optional (default)
DASHBOARD_API_PORT=8787                      # optional (default)
```

Without `DASHBOARD_API_SECRET` the API never starts and the bot runs exactly as
before.

### 2. Expose the bot with a Cloudflare Tunnel

Once you've chosen a host for the bot, run `cloudflared` next to it so the API is
reachable without opening any ports:

```
cloudflared tunnel --url http://127.0.0.1:8787
```

For a permanent setup, create a named tunnel and map a hostname
(e.g. `bot.yourdomain.com`) to `http://127.0.0.1:8787`. That hostname is your
`BOT_API_URL`.

### 3. Discord application

In the Discord Developer Portal → your app → OAuth2:

- Copy the **Client ID** and **Client Secret**.
- Add a redirect: `https://<your-pages-domain>/auth/callback`
  (and `http://localhost:8788/auth/callback` for local dev).

### 4. Deploy on Cloudflare Pages

- Push this `dashboard/` folder to GitHub.
- Cloudflare Pages → Create project → connect the repo.
- Build command: `npm run build` · Output directory: `dist`.
- Set these as Pages environment variables (encrypt the secrets):
  `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `SESSION_SECRET`,
  `BOT_API_URL`, `DASHBOARD_API_SECRET` (must match the bot), `R2_PUBLIC_URL`.
- Bind the R2 bucket: Pages project → Settings → Functions → R2 bindings →
  add binding `MEDIA` → bucket `mpopbot-media`.

## Local development

```
npm install
cp .dev.vars.example .dev.vars   # fill in values
npm run pages:dev                # Vite + Pages Functions together
```

## Project layout

```
dashboard/
├── functions/            Cloudflare Pages Functions (server-side)
│   ├── auth/             Discord OAuth: login, callback, logout, me
│   ├── api/[[path]].js   authenticated proxy to the bot API
│   └── _lib/session.js   signed session cookies (Web Crypto HMAC)
├── src/
│   ├── pages/            Overview, Groups, GroupEdit, Albums, AlbumEdit
│   ├── components/       Layout (sidebar), EditForm, Toast
│   └── lib/api.js        fetch wrapper for /api and /auth
├── public/_redirects     SPA fallback
└── wrangler.toml         Pages config
```

## Roadmap

- **Increment 2:** company detail view; album ↔ group navigation.
- **Increment 3:** orphaned-image cleanup (delete the previous R2 object when an
  image is replaced) via an R2 lifecycle rule or on-replace deletion.
- **Increment 4:** audit log of dashboard edits.
