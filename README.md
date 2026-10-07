# Bambu Lab to Snapmaker U1 Converter

A web-based tool to convert Bambu Lab .3mf projects to Snapmaker U1 format, preserving multi-color painting and filament assignments.

> This is a fork of [josuanbn/bl2u1](https://github.com/josuanbn/bl2u1) that includes the
> changes proposed in the upstream pull requests (security fixes, original filenames,
> no 4-filament cap, batch conversion, a model library and Docker support).

**Original live version:** [https://bl2u1.nbn.cat](https://bl2u1.nbn.cat)

**This fork's live version:** [https://bl2u1.onrender.com](https://bl2u1.onrender.com)
(free hosting: the first visit after a quiet spell can take ~30 seconds to load)

**Run your own copy as a website (one click):**

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/kbaker827/bl2u1)

## Features

- Converts Bambu Lab/Bambu Studio .3mf files to Snapmaker U1 compatible format
- Preserves color painting and multi-color assignments
- Applies the 0.20mm Standard print profile for U1
- Remaps filament types to U1 compatible profiles
- Automatically enables Tree Supports (auto) if the original model has supports enabled
- Optionally keeps the print settings you changed in Bambu Studio (layer height,
  walls, infill, brim, support options); speeds and temperatures always come from the U1 profile
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

1. Upload your Bambu Lab .3mf file
2. Review and adjust filament colors/types if needed
3. Click "Convert and Download"
4. Open the converted file in **Snapmaker Orca** for final slicing

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

If your Render service was created by hand rather than with the button,
`render.yaml` is not used: add an `ADMIN_TOKEN` environment variable yourself.

Free-tier notes: the site sleeps after 15 minutes without visitors (the next
visit takes about 30 seconds to wake it), and the disk is reset on each deploy
or restart, so the Library tab is not permanent. Attach a Render persistent
disk at `/app/inventory` (paid plan) if the library needs to persist.

Any other Docker host (Fly.io, Railway, a VPS) also works. The container
listens on `$PORT` (default `8080`).

## Self-Hosting

### Requirements

- Python 3.10+
- Flask and defusedxml (installed from `requirements.txt`)

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

### Settings

| Environment variable | Default | Purpose |
|---|---|---|
| `ADMIN_TOKEN` | empty | Password for the Library tab. Empty means no password, so set one on any server other people can reach. |
| `LIBRARY_ENABLED` | `true` | Set to `false` to hide the Library tab and disable its API. |
| `PORT` | `8080` | Port the Docker image listens on. |
| `BL2U1_UPLOAD_DIR` / `BL2U1_INVENTORY_DIR` | `uploads/` / `inventory/` | Storage folders. |

### Running the Tests

```bash
pip install -r requirements-dev.txt
pytest --cov=.
```

GitHub Actions runs the same tests on every push and pull request.

### Project Structure

```
bl2u1/
├── app.py                    # Flask app: upload, convert and download routes
├── converter.py              # Conversion logic (no Flask)
├── library.py                # Library API (password check lives here)
├── db.py                     # SQLite storage for the Library tab
├── utils.py                  # Path and filename helpers
├── tests/                    # pytest suite
├── Dockerfile / docker-compose.yml
├── render.yaml               # One-click Render deployment
├── templates/
│   └── index.html            # Frontend interface
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
- `filament_types.3mf` - Reference file containing available U1 filament profiles

## Technical Details

The converter performs the following transformations:

1. **Printer Profile**: Changes printer settings from Bambu Lab to Snapmaker U1
2. **Filament Mapping**: Remaps filament types to U1 compatible profiles
3. **Color Preservation**: Filament numbers are never changed, so object
   assignments and painted regions keep pointing at the right filament.
   The filament list comes from `project_settings.config`, which covers every plate.
4. **Support Detection**: Reads `enable_support` from the project settings and uses the appropriate template
5. **Print Settings**: Settings listed as changed in `different_settings_to_system`
   are copied over if they are on a safe list (layer heights are only kept between 0.04 and 0.32 mm)
6. **Filament Padding**: Ensures at least 4 filaments are configured (fills empty slots with white PLA)

Uploads are checked before processing: archives with more than 10,000 entries or
more than 1 GB of uncompressed data are rejected, and XML is parsed with defusedxml.

### File Cleanup

Uploaded files are automatically deleted after 8 hours to save disk space.
ZIP bundles are deleted as soon as they have been downloaded.

## Limitations

- The U1 has 4 toolheads; files with more than 4 colors convert fine, but printing them needs filament swaps
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
