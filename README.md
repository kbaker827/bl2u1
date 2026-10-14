# Bambu Lab to Snapmaker U1 Converter

A web-based tool to convert Bambu Lab .3mf projects to Snapmaker U1 format, preserving multi-color painting and filament assignments.

> This is a fork of [josuanbn/bl2u1](https://github.com/josuanbn/bl2u1) that includes the
> changes proposed in the upstream pull requests (security fixes, original filenames,
> no 4-filament cap, batch conversion, a model library and Docker support), plus
> its own fixes: correct colours for multi-plate and painted models, an optional
> password for the Library, keeping your print setting changes, safer upload
> handling, and an automated test suite.

**Original live version:** [https://bl2u1.nbn.cat](https://bl2u1.nbn.cat)

**This fork's live version:** [https://bl2u1.onrender.com](https://bl2u1.onrender.com)
(free hosting: the first visit after a quiet spell can take ~30 seconds to load)

**Run your own copy as a website (one click):**

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/kbaker827/bl2u1)

## Features

- Converts Bambu Lab/Bambu Studio .3mf files to Snapmaker U1 compatible format
- Preserves color painting and multi-color assignments
- Applies the 0.20mm Standard print profile for U1
- Remaps filament types to U1 compatible profiles, applying each profile's own
  temperatures, fan, flow and retraction settings (an ABS slot prints at ABS temperatures)
- Flags materials that have no U1 profile (e.g. PA, PC) so you can pick a type yourself
- Automatically enables Tree Supports (auto) if the original model has supports enabled
- Optionally keeps the print settings you changed in Bambu Studio (layer height,
  walls, infill, brim, support options); speeds and temperatures always come from the U1 profiles
- Multi-plate projects are handled; filaments not used by any sliced plate are marked "unused"
- Supports files with more than 4 filaments (all colors are kept)
- Batch conversion of multiple files, with a single ZIP download
- Library tab to keep converted models, with title, description, tags and search
  (can be password protected)
- Real-time upload progress bar
- Downloaded file keeps the original name (e.g. `my_model-U1.3mf`)
- Simple drag & drop interface
- No installation required (web-based)

## How It Works

1. Upload one or more Bambu Lab .3mf files (or a whole folder)
2. Review and adjust filament colors/types if needed. Each filament is listed
   once, in its original slot order; filaments that no sliced plate uses are
   dimmed and marked "unused". Filaments marked **no U1 profile** use PLA
   settings unless you pick another type
3. Leave **Keep my print setting changes** ticked to carry over the settings you
   changed in Bambu Studio, or untick it to use the plain U1 0.20mm Standard profile
4. Click "Convert and Download" (or "Convert All", then "ZIP All" for a batch)
5. Open the converted file in **Snapmaker Orca** for final slicing

## Hosting This Fork on the Web

The app is a Python (Flask) server, so it needs a host that can run Python or
Docker. Static hosts such as GitHub Pages will not work. The repo includes a
`render.yaml` for [Render](https://render.com), which has a free tier:

1. Click the **Deploy to Render** button above and sign in with GitHub.
2. Accept the defaults and click **Apply**. Render builds the `Dockerfile`.
3. After a few minutes the site is live at `https://bl2u1-XXXX.onrender.com`.
   Every push to `main` redeploys automatically.
4. Render generates a random **Library password** (`ADMIN_TOKEN`). Find it, or
   replace it with your own, under *Environment* in the Render dashboard. The
   Library tab asks for it once per browser.
5. Optional: add your own domain under *Settings → Custom Domains* in Render.

`render.yaml` also sets `TRUST_PROXY_HOPS=1` so upload limits count each
visitor separately. Check it appears under *Environment* in the Render dashboard;
without it, all visitors share one upload limit.

If your Render service was created by hand rather than with the button,
`render.yaml` is not used: add the `ADMIN_TOKEN` and `TRUST_PROXY_HOPS=1`
environment variables yourself.

Free-tier notes: the site sleeps after 15 minutes without visitors (the next
visit takes about 30 seconds to wake it), and the disk is reset on each deploy
or restart, so the Library tab is not permanent. Attach a Render persistent
disk at `/app/inventory` (paid plan) if the library needs to persist.

Any other Docker host (Fly.io, Railway, a VPS) also works. The container
listens on `$PORT` (default `8080`) and runs as an unprivileged user.
`/healthz` returns `{"ok": true}`, or HTTP 503 if the U1 templates failed to
load, for health checks.

Run a single server process (the Dockerfile uses `gunicorn --workers 1
--threads 8`). Upload sessions are kept in memory, so a second worker would not
recognise sessions created by the first. Add threads, not workers, to handle
more users.

## Self-Hosting

### Requirements

- Python 3.10+
- Flask, defusedxml and gunicorn (pinned in `requirements.txt`)

### Installation

```bash
# Clone the repository
git clone https://github.com/kbaker827/bl2u1.git
cd bl2u1

# Install dependencies
pip install -r requirements.txt

# Run the application
python app.py
```

The application will be available at `http://localhost:8080`

### Docker

```bash
docker compose up -d
```

Uploads and the library are stored in Docker volumes. To password-protect the
Library, start it with `ADMIN_TOKEN=your-long-password docker compose up -d`.

The container runs as user `app` (uid 1000). If you created the volumes with an
older version of this image (which ran as root), give them to that user once:

```bash
docker compose run --rm --user root bl2u1 chown -R 1000:1000 /app/uploads /app/inventory
```

### Settings

| Environment variable | Default | Purpose |
|---|---|---|
| `ADMIN_TOKEN` | empty | Password for the Library tab. Empty means no password, so set one on any server other people can reach. |
| `LIBRARY_ENABLED` | `true` | Set to `false` to hide the Library tab and disable its API. |
| `PORT` | `8080` | Port the Docker image listens on. |
| `BL2U1_UPLOAD_DIR` / `BL2U1_INVENTORY_DIR` | `uploads/` / `inventory/` | Storage folders. |
| `UPLOADS_PER_HOUR` | `200` | Uploads allowed per visitor IP per hour (each file in a batch counts once). `0` disables the limit. |
| `MAX_UPLOAD_STORAGE_MB` | `2048` | New uploads are refused while the uploads folder is bigger than this. `0` disables the check. |
| `LIBRARY_LOGIN_ATTEMPTS_PER_HOUR` | `20` | Wrong Library passwords allowed per IP per hour before that IP is locked out for the rest of the hour. |
| `TRUST_PROXY_HOPS` | `0` | Number of proxies in front of the app whose `X-Forwarded-For` should be trusted for the visitor IP. Set to `1` on Render; leave `0` when nothing sits in front. |
| `FLASK_DEBUG` | `false` | Flask debug mode when running `python app.py`. Never enable it on a public server. |

### Library Password

When `ADMIN_TOKEN` is set, every Library request (listing, upload, download,
edit, delete) needs the password; the converter itself stays public. The web
page asks for it once and remembers it in that browser's local storage. To
forget it, clear the site's data in your browser. Scripts send it in an
`X-Admin-Token` header:

```bash
curl -H "X-Admin-Token: your-long-password" https://your-site/api/inventory
```

Use a long random value. Wrong passwords are limited per IP (see
`LIBRARY_LOGIN_ATTEMPTS_PER_HOUR`).

### Running the Tests

```bash
pip install -r requirements-dev.txt
pytest --cov=.
```

GitHub Actions runs the same tests (Python 3.10 and 3.12) on every pull
request and every push to `main`, and fails if coverage drops below 80%.
The tests build small synthetic .3mf files, so no real models are needed.

### Page Styles

The page uses [Tailwind CSS](https://tailwindcss.com). The built stylesheet,
`static/css/app.css`, is committed so the server needs no Node.js. After
changing classes in `templates/`, rebuild it:

```bash
npm install
npm run build:css
```

GitHub Actions fails if `static/css/app.css` is out of date.

### Project Structure

```
bl2u1/
├── app.py                    # Flask app: upload, convert and download routes
├── converter.py              # Conversion logic (no Flask)
├── library.py                # Library API (password check lives here)
├── db.py                     # SQLite storage for the Library tab
├── utils.py                  # Path and filename helpers
├── limits.py                 # Upload rate limit and storage guard
├── tests/                    # pytest suite
├── Dockerfile / docker-compose.yml
├── render.yaml               # One-click Render deployment
├── templates/
│   └── index.html            # Frontend interface
├── static/                   # Built CSS (static/css/app.css) and favicon
├── assets/tailwind.css       # Tailwind source for static/css/app.css
├── uploads/                  # Temporary file storage (auto-cleaned)
├── inventory/                # Library files and database
├── u1_template.3mf           # U1 template without supports
├── u1_template_supports.3mf  # U1 template with tree supports
└── filament_types.3mf        # Available filament profiles
```

### Template Files

The converter requires template .3mf files configured for Snapmaker U1:

- `u1_template.3mf` - Base template with 0.20mm Standard profile, supports disabled
- `u1_template_supports.3mf` - Same as above but with Tree Supports (auto) enabled
- `filament_types.3mf` - Reference file containing available U1 filament profiles,
  including each profile's temperatures, fan, flow and other per-filament settings

## Technical Details

The converter performs the following transformations:

1. **Printer Profile**: Replaces the project settings with the U1 template and
   sets the printer model in `slice_info.config` to Snapmaker U1
2. **Filament Mapping**: Picks the U1 profile for each filament type: an exact
   match first, then a few aliases (ASA → ABS, PCTG → PETG), then the longest
   U1 type contained in the original (e.g. `PLA-CF` → PLA). Anything else falls
   back to the first profile (PLA) and is flagged "no U1 profile" in the page.
   You can override every choice in the page. Every per-filament setting
   (`filament_*` plus temperatures, plate temperatures, fan, cooling and pressure
   advance) is then taken from the chosen profile in `filament_types.3mf`, while
   per-toolhead machine settings (nozzle diameter, retraction, z-hop) stay as in the template
3. **Color Preservation**: Filament numbers are never changed, so object
   assignments (`model_settings.config`) and painted regions (`3D/Objects/*.model`)
   keep pointing at the right filament; those files are copied unchanged.
   The filament list comes from `project_settings.config`, which covers every plate;
   `slice_info.config` is only used to see which filaments are actually used
4. **Support Detection**: Reads `enable_support` from the project settings and uses the appropriate template
5. **Print Settings**: Settings listed as changed in `different_settings_to_system`
   are copied over if they are on a safe list: layer heights, wall loops,
   top/bottom shells, infill density and pattern, surface patterns, single top wall, brim, support
   type/style/angle, seam position, ironing, fuzzy skin and print sequence.
   Layer heights are only kept between 0.04 and 0.32 mm (suitable for the U1's
   0.4 mm nozzle). Speeds and accelerations come from the U1 print profile;
   temperatures come from the chosen filament profiles
6. **Filament Padding**: Ensures at least 4 filaments are configured (fills empty slots with white PLA)

Uploads are checked before processing: archives with more than 10,000 entries or
more than 1 GB of uncompressed data are rejected, settings files over 32 MB are
refused, entries with unsafe paths (such as `../`) are skipped, and XML is parsed
with defusedxml. Files are copied in a streaming fashion rather than loaded into
memory. Error messages shown in the browser never include server internals; full
details go to the server log.

### File Cleanup

Uploaded files are automatically deleted after 8 hours to save disk space.
ZIP bundles are deleted as soon as they have been downloaded.

## Limitations

- The U1 has 4 toolheads; files with more than 4 colors convert fine, but printing them needs filament swaps
- Unused filaments are kept rather than removed, because removing them would mean
  renumbering the painted regions. A project with 8 filaments loaded but only 2
  used converts with all 8 (the unused ones are marked in the page)
- Up to 200 MB per file and 50 files per batch; 200 uploads per visitor per hour by default
- The converted file must be sliced in Snapmaker Orca before printing
- Some advanced Bambu-specific features may not transfer

## Contributing

Contributions are welcome! Feel free to:

- Report bugs
- Suggest features
- Submit pull requests

## License

MIT License - feel free to use, modify, and distribute.

## Acknowledgments

- Snapmaker community for feedback and testing
- Bambu Lab for the excellent .3mf format documentation

## Support

If you find this tool useful, consider [buying me a coffee](https://buymeacoffee.com/goofoo)!
