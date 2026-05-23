# Deploying the Catalyst dashboard

The dashboard in this `web/` folder is a **fully static site** - just HTML, CSS
and JavaScript. There is no server, no build step, and no framework. That means
it can be hosted for free on any static host, it never "sleeps", and it loads
instantly.

## What's in this folder

| File         | Purpose                                                        |
|--------------|----------------------------------------------------------------|
| `index.html` | the dashboard page                                             |
| `styles.css` | all styling                                                    |
| `app.js`     | rendering, charts, sorting/filtering                           |
| `data.js`    | the data snapshot - **generated**, see below                   |
| `DEPLOY.md`  | this file                                                      |

`Chart.js` and the fonts load from public CDNs at runtime, so the folder above
is everything that needs to be hosted.

## The data workflow

The dashboard reads `data.js`, which is produced from `catalyst.db` by the
`export_data.py` script one level up. Whenever you want the site to show fresh
numbers:

```
python run.py --source live --currencies BTC,ETH,SOL   # 1. run the pipeline
python export_data.py                                  # 2. regenerate web/data.js
```

Then redeploy (or, on a git-connected host, commit and push - see below).

`data.js` is plain JavaScript (`window.CATALYST_DATA = {...}`) rather than JSON
on purpose: a `<script>` tag works when the page is opened directly from disk,
whereas `fetch()` of a local JSON file is blocked by browsers.

## Preview it locally

Just double-click `index.html` - because the data is a `<script>`, it opens
straight from the filesystem with no server needed.

If you prefer a server (closer to production):

```
cd web
python -m http.server 8000
# open http://localhost:8000
```

## Deploy - pick one

### Option A - Netlify Drop (fastest, no account setup)

1. Go to <https://app.netlify.com/drop>.
2. Drag the whole `web/` folder onto the page.
3. It's live in seconds at a `*.netlify.app` URL.

To update later, regenerate `data.js` and drag the folder again.

### Option B - Git-connected (auto-deploys on every push)

Works with **Vercel**, **Netlify**, or **Cloudflare Pages**. All three are free
for a project this size and the steps are nearly identical:

1. Push this repository to GitHub.
2. In the host's dashboard, create a new project and import the repo.
3. Set the configuration:
   - **Build command:** leave empty (there is no build).
   - **Output / publish / root directory:** `web`
4. Deploy. From then on, every `git push` redeploys automatically.

To update the data: run the pipeline, run `python export_data.py`, then
`git add web/data.js && git commit && git push`.

### Option C - GitHub Pages

GitHub Pages serves from a repo root or a `/docs` folder, not an arbitrary
subfolder. Easiest path: copy the contents of `web/` into a `docs/` folder at
the repo root, then in **Settings → Pages** set the source to `main` / `/docs`.

## Custom domain

A custom domain removes the `*.netlify.app` / `*.pages.dev` URL and looks far
more professional (e.g. `catalyst.yourdomain.com`).

1. In the host's project settings, open the **Domains** section and add your
   domain or subdomain.
2. The host shows a DNS record to create - usually a **CNAME** for a subdomain
   pointing at the host (e.g. `catalyst → your-project.netlify.app`).
3. Add that record at your domain registrar. HTTPS is provisioned automatically
   once DNS propagates (minutes to a couple of hours).

## Notes

- The dashboard is read-only and contains no secrets - `data.js` holds only the
  already-public news/classification data, never API keys.
- If you ever see "No data snapshot found", `data.js` is missing or empty - run
  `python export_data.py`.
