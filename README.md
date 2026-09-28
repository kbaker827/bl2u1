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
- Supports files with more than 4 filaments (all colors are kept)
- Batch conversion of multiple files, with a single ZIP download
- Library tab to keep converted models, with title, description, tags and search
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
4. Optional: add your own domain under *Settings → Custom Domains* in Render.

Free-tier notes: the site sleeps after 15 minutes without visitors (the next
visit takes about 30 seconds to wake it), and the disk is reset on each deploy
or restart, so the Library tab is not permanent. Attach a Render persistent
disk at `/app/inventory` (paid plan) if the library needs to persist.

Any other Docker host (Fly.io, Railway, a VPS) also works. The container
listens on `$PORT` (default `8080`).

## Self-Hosting

### Requirements

- Python 3.8+
- Flask

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

Uploads and the library are stored in Docker volumes.

### Project Structure

```
bl2u1/
├── app.py                    # Flask backend
├── db.py                     # SQLite storage for the Library tab
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
3. **Color Preservation**: Maintains all color painting data from the original file
4. **Support Detection**: Checks `different_settings_to_system` for `enable_support` and uses the appropriate template
5. **Filament Padding**: Ensures at least 4 filaments are configured (fills empty slots with white PLA)

### File Cleanup

Uploaded files are automatically deleted after 8 hours to save disk space.

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
