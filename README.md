<p align="center">
  <img src="TEREDACTA.png" alt="TEREDACTA" width="600">
</p>

<p align="center">
  <em>A discovery-first web interface for <a href="https://github.com/networkingguru/Unobfuscator">Unobfuscator</a> — explore recovered redactions, trace entity connections, and investigate government documents.</em>
</p>

---

## What It Does

When government agencies release the same documents multiple times with different redaction patterns, [Unobfuscator](https://github.com/networkingguru/Unobfuscator) cross-references the releases and recovers the hidden text. TEREDACTA makes those recoveries explorable through an investigative web interface designed for reporters and researchers.

**Currently deployed against 1.4 million documents from the Congressional Epstein/Maxwell releases** (DOJ volumes, House Oversight releases), with 6,400+ recovered redactions across 15,220 document match groups.

### Key Features

**For Investigators:**
- **Entity Explorer** — Interactive three-column graph showing connections between people, organizations, locations, emails, and phone numbers found in recovered text. Click an entity to see its connections; click a connection to drill deeper.
- **Highlights** — Auto-generated summary of the most significant findings: top recoveries by volume, notable entities, and most frequently recovered strings.
- **Recovery Viewer** — Read recovered redactions with green-highlighted passages, click any passage to see its source document context, navigate between passages with keyboard shortcuts (j/k).
- **Source Panel** — Click a recovered passage to see where it came from: the excerpt from the less-redacted release with the passage highlighted, plus links to the full PDF and document details.
- **Boolean Search** — Search recovered text with AND, OR, and quoted exact phrases. Search documents by filename, ID, or entity name.

**For Administrators:**
- **Pipeline Dashboard** — Live progress, stats, and daemon status via Server-Sent Events.
- **Document Browser** — Paginated, filterable table of all ingested documents.
- **Match Groups** — Explore clusters of overlapping documents with similarity scores.
- **Job Queue** — Monitor pending, running, completed, and failed pipeline jobs.
- **Admin Panel** — Start/stop the daemon, edit config, tail logs, trigger searches, manage dataset downloads, build/rebuild the entity index.

### Screenshots

<p align="center">
  <img src="docs/screenshots/explore.png" alt="Entity Explorer" width="800"><br>
  <em>Entity Explorer — three-column graph of people, organizations, and documents</em>
</p>

<p align="center">
  <img src="docs/screenshots/highlights.png" alt="Highlights" width="800"><br>
  <em>Highlights — top recoveries and notable entities at a glance</em>
</p>

<p align="center">
  <img src="docs/screenshots/recovery-detail.png" alt="Recovery Detail" width="800"><br>
  <em>Recovery detail — merged text with recovered passages highlighted in green</em>
</p>

<p align="center">
  <img src="docs/screenshots/documents.png" alt="Document Browser" width="800"><br>
  <em>Document browser with search across 1.4 million records</em>
</p>

## Tech Stack

Pure Python. No Node.js, no build step, no JS framework.

| Layer | Choice |
|-------|--------|
| Server | **FastAPI** + **Uvicorn** |
| Reactivity | **HTMX** (vendored) |
| PDF rendering | **PDF.js** (vendored) |
| Live updates | **Server-Sent Events** |
| Templating | **Jinja2** |
| Entity index | **SQLite** (separate from Unobfuscator DB) |
| Auth | Signed cookies + CSRF tokens |
| Database | Read-only SQLite queries against the Unobfuscator DB |

---

## Installation Guide

### Prerequisites

- **Linux server** (Ubuntu 22.04+ recommended) or macOS
- **Python 3.10+**
- **git**
- **~200 GB disk space** for the full dataset (PDF cache + database)

### Step 1: Clone TEREDACTA

```bash
git clone git@github.com:networkingguru/TEREDACTA.git
cd TEREDACTA
```

### Step 2: Create virtualenv and install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Step 3: Run the installer

```bash
python -m teredacta install
```

The installer will:
1. Search for an existing Unobfuscator installation (checks `../Unobfuscator`, `~/Unobfuscator`, `~/Scripts/Unobfuscator`)
2. If not found, offer to clone it from GitHub and set up its virtualenv/dependencies
3. Read Unobfuscator's config to auto-detect database, PDF cache, and output paths
4. Ask for deployment mode (local or server) and port
5. Write config to `./teredacta.yaml` and `~/.teredacta/config.yaml`
6. Offer to start both the Unobfuscator daemon and the TEREDACTA web server

### Step 4: Download datasets

If Unobfuscator doesn't have datasets yet:

```bash
cd ../Unobfuscator
source .venv/bin/activate
python download_datasets.py
```

This downloads the DOJ Epstein disclosure datasets from archive.org mirrors (~200 GB total). Downloads are resumable — if interrupted, re-run the same command.

### Step 5: Start the pipeline

```bash
# Start Unobfuscator (processes documents in the background)
python unobfuscator.py start

# Check status
python unobfuscator.py status
```

The pipeline runs through 5 stages: indexing → fingerprinting/matching → merging → PDF processing → output generation. On first run with all datasets, expect several hours for full processing.

### Step 6: Start TEREDACTA

```bash
cd ../TEREDACTA
source .venv/bin/activate
python -m teredacta run
```

Open [http://localhost:8000](http://localhost:8000). For network access: `python -m teredacta run --host 0.0.0.0`.

### Step 7: Build the entity index

In the browser, go to **Admin → Build / Rebuild** (the Entity Index card). This scans all recovered text and builds the searchable entity graph. Takes 2-10 seconds.

Or wait — if you visit the Explore page before building, it will prompt you.

### Running as a service (Linux)

The installer can generate systemd unit files for both services:

```bash
# During install, choose "server" mode and say yes to systemd
python -m teredacta install

# Or manually:
systemctl --user enable --now unobfuscator
systemctl --user enable --now teredacta
```

---

## Quick Start (if Unobfuscator is already running)

```bash
git clone git@github.com:networkingguru/TEREDACTA.git
cd TEREDACTA
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m teredacta install   # detects existing Unobfuscator
python -m teredacta run
```

---

## Configuration

Config lives at `./teredacta.yaml` or `~/.teredacta/config.yaml`:

```yaml
unobfuscator_path: /path/to/Unobfuscator
unobfuscator_bin: /path/to/Unobfuscator/.venv/bin/python /path/to/Unobfuscator/unobfuscator.py
db_path: /path/to/Unobfuscator/data/unobfuscator.db
pdf_cache_dir: /path/to/Unobfuscator/pdf_cache
output_dir: /path/to/Unobfuscator/output
log_path: /path/to/Unobfuscator/data/unobfuscator.log
host: 127.0.0.1       # 0.0.0.0 for network access, 127.0.0.1 behind reverse proxy
port: 8000
workers: 1             # Uvicorn worker processes (4 recommended for production)
secret_key: <generated-by-installer>  # persist this for stable sessions
log_level: info
```

For server mode (non-localhost), set an admin password:

```bash
export TEREDACTA_ADMIN_PASSWORD=your-password
python -m teredacta run --host 0.0.0.0
```

---

## Architecture

```
Browser ─── Caddy (HTTPS) ─── Uvicorn (N workers) ─┬─ SQLite (read-only, pooled) ── Unobfuscator DB
                                                     ├─ SQLite (read/write, WAL) ──── Entity Index DB
                                                     ├─ SSE (admin only)
                                                     └─ subprocess (admin) ─────────── Unobfuscator CLI
```

FastAPI application with configurable Uvicorn worker processes. Public routes are read-only with pooled SQLite connections. SSE live updates are restricted to admin pages. The entity index is a separate TEREDACTA-owned SQLite database — Unobfuscator's database is never modified.

For production deployment behind a reverse proxy, see [deploy/README.md](deploy/README.md).

---

## Troubleshooting

### "Database not found" on startup

TEREDACTA can't find Unobfuscator's database. Check `db_path` in your config:

```bash
cat teredacta.yaml | grep db_path
ls -la /path/shown/above
```

If the file doesn't exist, Unobfuscator hasn't been initialized yet. Run `python unobfuscator.py status` in the Unobfuscator directory.

### "No secret_key found in config file"

This warning means sessions won't survive server restarts. The installer generates a key automatically, but if you created the config manually, add one:

```bash
python3 -c "import os; print('secret_key:', os.urandom(32).hex())" >> teredacta.yaml
```

### Explore page says "Entity index has not been built yet"

Go to **Admin** (top nav) and click **Build / Rebuild** in the Entity Index card. This takes 2-10 seconds.

### PDFs show "not yet downloaded" or "No PDF available"

Two different situations:

- **"PDF not yet downloaded"** — The PDF file exists on the DOJ website but hasn't been cached locally. Run `python download_datasets.py` in the Unobfuscator directory to download datasets.
- **"No PDF available — this is an email record"** — This document was extracted from an email archive (MBOX/EML), not a PDF. The text is available but there's no visual PDF to display. This is normal for datasets 9, 10, and 11 which are primarily email archives.

### "Address already in use" on port 8000

Another process is using the port:

```bash
# Find what's using it
lsof -i :8000

# Kill it, or use a different port
python -m teredacta run --port 8001
```

### Daemon status shows "STOPPED" but Unobfuscator is running

TEREDACTA checks daemon status by reading Unobfuscator's PID file and process list. If Unobfuscator was started from a different directory or user, the check may fail. Verify with:

```bash
cd /path/to/Unobfuscator
source .venv/bin/activate
python unobfuscator.py status
```

### Search returns no results

- **Document search** matches filenames and document IDs as substrings, plus entity names from the entity index. Try shorter search terms.
- **Recovery search** searches the raw recovered text using JSON-encoded matching. Quotes and special characters are handled automatically. Use `AND`, `OR`, or quoted phrases: `"Prince Andrew" AND FBI`.

### Entity index seems incomplete or has wrong entries

The entity index is a rebuildable cache. If results seem off after a pipeline update, rebuild it from **Admin → Entity Index → Build / Rebuild**. The extraction uses regex patterns with a stop list — some false positives are expected for edge cases.

### High memory usage

The Unobfuscator database can be 6+ GB. TEREDACTA opens read-only connections per request and closes them immediately. If memory is a concern, reduce concurrent users or add swap space.

### Permission denied errors

On Linux, ensure the TEREDACTA user can read the Unobfuscator database and PDF cache:

```bash
chmod -R o+r /path/to/Unobfuscator/data/
chmod -R o+r /path/to/Unobfuscator/pdf_cache/
```

---

## License

MIT. See [LICENSE](LICENSE).
