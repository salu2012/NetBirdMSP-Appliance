# NetBird MSP Appliance

**Self-Hosted Multi-Tenant NetBird Management Platform**

A management solution for running isolated NetBird instances for your MSP business. Manage all your customers' NetBird networks from a single web interface.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Docker](https://img.shields.io/badge/docker-required-blue.svg)
![Python](https://img.shields.io/badge/python-3.11+-blue.svg)

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [System Requirements](#system-requirements)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Usage](#usage)
- [API Documentation](#api-documentation)
- [Troubleshooting](#troubleshooting)
- [Updates](#updates)
- [Security Best Practices](#security-best-practices)
- [License](#license)

---

## Features

### Core
- **Multi-Tenant Management** — Deploy and manage isolated NetBird instances per customer
- **Complete Isolation** — Each customer gets their own NetBird stack with separate data
- **One-Click Deployment** — Deploy new customer instances in under 2 minutes
- **Nginx Proxy Manager Integration** — Automatic SSL certificates and reverse proxy setup
- **Docker-Based** — Everything runs in containers for easy deployment

### Dashboard
- **Modern Web UI** — Responsive Bootstrap 5 interface
- **Real-Time Monitoring** — Container status, health checks, resource usage
- **Container Logs** — View logs per container directly in the browser
- **Start / Stop / Restart** — Control customer instances from the dashboard
- **Customer Status Tracking** — Automatic status sync (active / inactive / error)

### Multi-Language (i18n)
- **English and German** — Full UI translation
- **Global Default Language** — Set a system-wide default language in Settings > Branding
- **Per-User Language** — Each user can have their own preferred language
- **Language Priority** — User preference > System default > Browser language

### Customization
- **Branding** — Configure platform name, subtitle, and logo via Settings
- **Login Page** — Branding is applied to the login page automatically
- **Configurable Docker Images** — Use custom or specific NetBird image versions

### Security
- **JWT Authentication** — Token-based API authentication
- **Azure AD / OIDC** — Optional single sign-on via Microsoft Entra ID
- **Encrypted Credentials** — NPM passwords and relay secrets are Fernet-encrypted
- **User Management** — Create, edit, and delete admin users

---

## Architecture

```
+-------------------------------------------------------------+
|                    NetBird MSP Appliance                      |
|                                                               |
|  +--------------+    +--------------+   +---------------+    |
|  |   Web GUI    |--->|  FastAPI     |-->|   SQLite DB   |    |
|  |  (Bootstrap) |    |   Backend    |   |               |    |
|  +--------------+    +--------------+   +---------------+    |
|                             |                                 |
|         +-------------------+-------------------+            |
|         v                   v                   v             |
|  +-------------+    +-------------+    +---------------+     |
|  |   Docker    |    |    NPM      |    |   Template    |     |
|  |   Engine    |    |     API     |    |   Renderer    |     |
|  +-------------+    +-------------+    +---------------+     |
+-------------------------------------------------------------+
                            |
        +-------------------+-------------------+
        v                                       v
+------------------+                  +------------------+
|  Customer 1      |                  |  Customer N      |
|  +------------+  |                  |  +------------+  |
|  | Management |  |                  |  | Management |  |
|  | Signal     |  |      ...        |  | Signal     |  |
|  | Relay      |  |                  |  | Relay      |  |
|  | Dashboard  |  |                  |  | Dashboard  |  |
|  | Caddy      |  |                  |  | Caddy      |  |
|  +------------+  |                  |  +------------+  |
+------------------+                  +------------------+
  kunde1.domain.de                      kundeN.domain.de
  UDP 3478                              UDP 3478+N-1
```

### Components per Customer Instance (5 containers):
- **Management** — API and network state management
- **Signal** — WebRTC signaling for peer connections
- **Relay** — STUN/TURN server for NAT traversal (requires public UDP port)
- **Dashboard** — Web UI for end-users
- **Caddy** — Reverse proxy / entry point for the customer stack

All services are accessible via HTTPS through Nginx Proxy Manager, except the Relay STUN port which requires direct UDP access.

---

## System Requirements

### Hardware Scaling

Based on real-world measurements: **2 customers (11 containers) use ~220 MB RAM**.

Per customer instance (5 containers): **~100 MB RAM**

| Customers | Container RAM | Recommended Total | vCPU | Storage |
|-----------|--------------|-------------------|------|---------|
| 10        | ~1.0 GB      | 2 GB              | 2    | 20 GB   |
| 25        | ~2.5 GB      | 4 GB              | 2    | 50 GB   |
| 50        | ~5.0 GB      | 8 GB              | 4    | 100 GB  |
| 100       | ~10.0 GB     | 16 GB             | 8    | 200 GB  |
| 200       | ~20.0 GB     | 32 GB             | 16   | 500 GB  |

> **Note:** "Recommended Total" includes OS overhead and headroom. SSD/NVMe storage is recommended for Docker performance.

### Port Requirements

| Port | Protocol | Purpose |
|------|----------|---------|
| 8000 | TCP | NetBird MSP Appliance Web UI |
| 3478+ | UDP | STUN/TURN relay (one per customer) |

Example: Customer 1 = UDP 3478, Customer 2 = UDP 3479, ..., Customer 100 = UDP 3577.

**Your firewall must allow the UDP relay ports for NetBird to function!**

---

## Prerequisites

The following tools and services must be available **before** running the installer.

### Required on the Host

| Tool | Purpose | Check Command |
|------|---------|---------------|
| **Linux OS** | Ubuntu 22.04+, Debian 12+, or similar | `cat /etc/os-release` |
| **sudo / root** | Installation requires root privileges | `sudo -v` |
| **curl** | Used by the installer to install Docker | `curl --version` |
| **git** | Clone the repository | `git --version` |
| **openssl** | Generate encryption keys during install | `openssl version` |

### Installed Automatically

| Tool | Purpose | Notes |
|------|---------|-------|
| **Docker Engine** 24.0+ | Container runtime | Installed by `install.sh` if missing |
| **Docker Compose Plugin** | Multi-container orchestration | Installed with Docker |

### External Services

| Service | Purpose | Notes |
|---------|---------|-------|
| **Nginx Proxy Manager** | Reverse proxy + SSL certificates | Must be running and accessible from the host. Can be on the same server or a separate one. |
| **Wildcard DNS** | Route `*.yourdomain.com` to the server | Configure `*.yourdomain.com` as an A record pointing to your server IP |

### Install Prerequisites (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install -y curl git openssl
```

---

## Quick Start

### 1. Clone the Repository

```bash
git clone https://git.0x26.ch/BurgerGames/NetBirdMSP-Appliance.git
cd NetBirdMSP-Appliance
```

### 2. Run the Interactive Installation Script

```bash
chmod +x install.sh
sudo ./install.sh
```

The installer will **interactively ask you** for:
- Admin username and password
- Admin email address
- Base domain (e.g., `yourdomain.com`)
- Nginx Proxy Manager API URL, email, and password
- Data directory location
- NetBird Docker images (optional customization)

**No manual .env file editing required!** All configuration is stored in the database and editable via the Web UI.

The installer will then:
- Check system requirements
- Install Docker if needed
- Create directories and Docker network
- Generate encryption keys
- Build and start all containers
- Seed configuration into the database
- Optionally configure the firewall (ufw)

### 3. Access the Web Interface

After installation completes, open your browser:
```
http://your-server-ip:8000
```

Login with the credentials you provided during installation.

### 4. Deploy Your First Customer

1. Click **"New Customer"** button
2. Fill in customer details (name, subdomain, email, max devices)
3. Click **"Deploy"**
4. Wait ~60-90 seconds
5. Done!

The system will automatically:
- Assign a unique UDP port for the relay
- Generate all config files from templates
- Start the 5 Docker containers
- Create NPM proxy hosts with SSL
- Provide the setup URL for the customer

---

## Configuration

### Environment Variables

The installer generates a minimal `.env` file with container-level variables only:

```bash
SECRET_KEY=<auto-generated>
DATABASE_PATH=/app/data/netbird_msp.db
DATA_DIR=/opt/netbird-instances
DOCKER_NETWORK=npm-network
LOG_LEVEL=INFO
WEB_UI_PORT=8000
```

> **All application settings** (domain, NPM credentials, Docker images, branding, etc.) are stored in the SQLite database and editable via the Web UI under **Settings**.

### Web UI Settings

Available under **Settings** in the web interface:

| Tab | Settings |
|-----|----------|
| **System** | Base domain, admin email, NPM credentials, Docker images, port ranges, data directory |
| **Branding** | Platform name, subtitle, logo upload, default language |
| **Users** | Create/edit/delete admin users, per-user language preference |
| **Monitoring** | System resources, Docker stats |

Changes are applied immediately without restart.

---

## Usage

### Managing Customers

#### Create a New Customer
1. Dashboard > **New Customer**
2. Fill in details
3. Click **Deploy**
4. Share the setup URL with your customer

#### View Customer Details
- Click on customer name in the list
- See deployment status, container health, logs
- Copy setup URL and credentials

#### Start / Stop / Restart Containers
- Use the action buttons in the customer detail view
- Stopping all containers sets the customer status to "inactive"
- Starting containers sets the status back to "active"

#### Delete a Customer
- Click **Delete** > Confirm
- All containers, data, and NPM entries are removed

### Monitoring

The dashboard shows:
- **System Overview** — Total customers, active/inactive, errors
- **Resource Usage** — RAM, CPU per container
- **Container Health** — Running/stopped per container with color-coded status
- **Deployment Logs** — Action history per customer

### Language Settings

- **Switch language** — Use the language switcher in the top navigation bar
- **Per-user default** — Set in Settings > Users during user creation
- **System default** — Set in Settings > Branding

---

## API Documentation

The appliance provides a REST API.

### Authentication
```bash
curl -X POST http://localhost:8000/api/auth/token \
  -d "username=admin&password=yourpassword"
```

### Endpoints

Full interactive documentation available at:
```
http://your-server:8000/docs
```

**Common Endpoints:**
```
POST   /api/customers              # Create customer + deploy
GET    /api/customers              # List all customers
GET    /api/customers/{id}         # Get customer details
PUT    /api/customers/{id}         # Update customer
DELETE /api/customers/{id}         # Delete customer

POST   /api/customers/{id}/start   # Start containers
POST   /api/customers/{id}/stop    # Stop containers
POST   /api/customers/{id}/restart # Restart containers
GET    /api/customers/{id}/logs    # Get container logs
GET    /api/customers/{id}/health  # Health check

GET    /api/settings/branding      # Get branding (public, no auth)
PUT    /api/settings               # Update system settings
GET    /api/users                  # List users
POST   /api/users                  # Create user
```

### Example: Create Customer via API
```bash
curl -X POST http://localhost:8000/api/customers \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Acme Corp",
    "subdomain": "acme",
    "email": "admin@acme.com",
    "max_devices": 20
  }'
```

---

## Troubleshooting

### Customer deployment fails
**Symptom**: Status shows "error" after deployment

**Solutions**:
- Check Docker logs: `docker logs netbird-msp-appliance`
- Verify NPM is accessible from the appliance container
- Check available UDP ports: `ss -ulnp | grep 347`
- View detailed logs in the customer detail page (Logs tab)

### NetBird clients can't connect
**Symptom**: Clients show "relay unavailable"

**Solutions**:
- **Most common**: UDP port not open in firewall
  ```bash
  sudo ufw allow 3478/udp
  ```
- Verify relay container is running: `docker ps | grep relay`

### NPM integration not working
**Symptom**: Proxy hosts or SSL certificates not created

**Solutions**:
- Verify NPM email and password are correct in Settings
- Check NPM is on same Docker network (`npm-network`)
- Check NPM logs for errors

### Debug Mode

Enable debug logging:
```bash
# In your .env file:
LOG_LEVEL=DEBUG

# Restart the appliance:
docker compose restart
```

View logs:
```bash
docker logs -f netbird-msp-appliance
```

---

## Updates

### Updating the Appliance

```bash
cd /opt/netbird-msp
git pull
docker compose down
docker compose up -d --build
```

The database migrations run automatically on startup.

### Updating NetBird Images

Via the Web UI:
1. Settings > System Configuration
2. Change image tags (e.g., `netbirdio/management:0.35.0`)
3. Click "Save"
4. Re-deploy individual customers to apply the new images

---

## Security Best Practices

1. **Change default credentials** immediately after installation
2. **Use strong passwords** (12+ characters recommended)
3. **Keep NPM credentials secure** — they are stored encrypted in the database
4. **Enable firewall** and only open required ports (TCP 8000, UDP relay range)
5. **Use HTTPS** — put the MSP appliance behind a reverse proxy with SSL
6. **Regular updates** — both the appliance and NetBird images
7. **Backup your database** — `data/netbird_msp.db` contains all configuration
8. **Monitor logs** — check for suspicious activity
9. **Restrict access** — use VPN or IP whitelist for the management interface

---

## Performance Tuning

### For 100+ Customers

```bash
# Increase Docker ulimits — add to /etc/docker/daemon.json
{
  "default-ulimits": {
    "nofile": {
      "Name": "nofile",
      "Hard": 64000,
      "Soft": 64000
    }
  }
}

# Restart Docker
sudo systemctl restart docker

# Increase inotify limits
echo "fs.inotify.max_user_instances=512" | sudo tee -a /etc/sysctl.conf
echo "fs.inotify.max_user_watches=524288" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

---

## License

MIT License — see [LICENSE](LICENSE) file for details.

---

## Built With AI

This software was developed with [Claude Code](https://claude.ai/claude-code) (Anthropic Claude Opus 4.6) — from architecture and backend logic to frontend UI and deployment scripts.

## Acknowledgments

- [Claude Code](https://claude.ai/claude-code) — AI-powered software development by Anthropic
- [NetBird](https://netbird.io/) — Open-source VPN solution
- [FastAPI](https://fastapi.tiangolo.com/) — High-performance Python framework
- [Nginx Proxy Manager](https://nginxproxymanager.com/) — Reverse proxy management
