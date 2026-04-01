# Deploying TEREDACTA

## Reverse Proxy with Caddy

Caddy provides automatic HTTPS via Let's Encrypt, static file serving, and connection buffering.

### Install Caddy

```bash
# Ubuntu/Debian
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy

# macOS
brew install caddy
```

### Configure

1. Copy `Caddyfile` to `/etc/caddy/Caddyfile`
2. Replace `example.com` with your domain
3. Replace `/path/to/TEREDACTA` with the actual install path
4. Ensure DNS points to your server

### Start

```bash
sudo systemctl enable --now caddy
```

Caddy will automatically obtain and renew TLS certificates.

## File Descriptor Limits

For production, raise the file descriptor limit:

```bash
# Check current limit
ulimit -n

# Temporary (current session)
ulimit -n 4096

# Permanent (add to /etc/security/limits.conf)
* soft nofile 4096
* hard nofile 8192
```

The systemd service template already includes `LimitNOFILE=4096`.

## Recommended Production Config

```yaml
# teredacta.yaml
host: 127.0.0.1          # Bind to localhost (Caddy handles external traffic)
port: 8000
workers: 4                # Uvicorn worker processes
secret_key: <generate>    # python3 -c "import os; print(os.urandom(32).hex())"
```

Set admin password via environment variable:
```bash
export TEREDACTA_ADMIN_PASSWORD=your-secure-password
```

## Health Checks

TEREDACTA exposes health endpoints for monitoring:

- `GET /health/live` — Liveness probe (event loop alive?)
- `GET /health/ready` — Readiness probe (DB pool, SSE status)

### Caddy Health Check

Add to your Caddyfile reverse_proxy block:

```
reverse_proxy localhost:8000 {
    health_uri /health/live
    health_interval 5s
}
```

This lets Caddy detect and route around unresponsive workers.

### External Monitoring

Point your monitoring tool (UptimeRobot, Healthchecks.io, etc.) at:
- Liveness: `https://your-domain.com/health/live`
- Readiness: `https://your-domain.com/health/ready`
