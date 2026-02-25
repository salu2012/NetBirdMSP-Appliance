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
- **SSL Certificate Modes** — Choose between per-customer Let's Encrypt certificates or a shared wildcard certificate
- **Docker-Based** — Everything runs in containers for easy deployment

### Dashboard
- **Modern Web UI** — Responsive Bootstrap 5 interface with dark/light mode toggle
- **Real-Time Monitoring** — Container status, health checks, resource usage
- **Container Logs** — View logs per container directly in the browser
- **Start / Stop / Restart** — Control customer instances from the dashboard
- **Customer Status Tracking** — Automatic status sync (active / inactive / error)
- **Update Indicators** — Per-customer badges when container images are outdated

### NetBird Container Updates
- **Docker Hub Digest Check** — Compare locally pulled image digests against Docker Hub without pulling
- **One-Click Pull** — Pull all NetBird images from Docker Hub via Settings
- **Bulk Update** — Update all outdated customer containers at once from the Monitoring page
- **Per-Customer Update** — Update a single customer's containers from the customer detail view
- **Zero Data Loss** — Container recreation preserves all bind-mounted volumes
- **Sequential Updates** — Customers are updated one at a time to minimize risk

### Multi-Language (i18n)
- **English and German** — Full UI translation
- **Global Default Language** — Set a system-wide default language in Settings > Branding
- **Per-User Language** — Each user can have their own preferred language
- **Language Priority** — User preference > System default > Browser language

### Customization
- **Branding** — Configure platform name, subtitle, and logo via Settings
- **Login Page** — Branding is applied to the login page automatically
- **Configurable Docker Images** — Use custom or specific NetBird image versions

### Authentication & User Management
- **JWT Authentication** — Token-based API authentication
- **Multi-Factor Authentication (MFA)** — Optional TOTP-based MFA for all local users, activatable in Security settings
- **Azure AD / OIDC** — Optional single sign-on via Microsoft Entra ID (exempt from MFA)
- **LDAP / Active Directory** — Allow AD users to authenticate; local admin accounts always work as fallback
- **Encrypted Credentials** — NPM passwords, relay secrets, TOTP secrets, and LDAP bind passwords are Fernet-encrypted at rest
- **User Management** — Create, edit, delete admin users, reset passwords and MFA

### Integrations
- **Windows DNS** — Automatically create and delete DNS A-records when deploying or removing customers
- **MSP Updates** — In-UI appliance update check with configurable release branch

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
  customer-a.domain.de                  customer-x.domain.de
         |                                     |3478+N-1
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
| 9000+ | TCP | NetBird Web Management per customer (only internal, one per customer, increments by 1) |
| 3478+ | UDP | STUN/TURN relay per customer (one per customer, increments by 1) |

Example for 3 customers:

| Customer | Dashboard (TCP) | Relay (UDP) |
|----------|----------------|-------------|
| Customer-A | 9001           | 3478        |
| Customer-C | 9002           | 3479        |
| Customer-X | 9003           | 3480        |

**Your firewall must allow both the TCP dashboard ports and the UDP relay ports!**

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

> **Note:** On a fresh Debian minimal install, `sudo` is not pre-installed. Install it as root first:

```bash
# As root — only needed on fresh Debian minimal (sudo not pre-installed):
apt update && apt install -y sudo

# Install remaining prerequisites:
sudo apt install -y curl git openssl
```

If `sudo` is already available (Ubuntu, most standard installs):

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
HOST_IP=<your-server-ip>
```

> **All application settings** (domain, NPM credentials, Docker images, branding, etc.) are stored in the SQLite database and editable via the Web UI under **Settings**.

### Web UI Settings

Available under **Settings** in the web interface, organized into tabs:

#### User Management

| Tab | Settings |
|-----|----------|
| **Azure AD** | Azure AD / Entra ID SSO configuration (tenant ID, client ID/secret, optional group restriction) |
| **Users** | Create/edit/delete admin users, per-user language preference, MFA reset |
| **LDAP / AD** | LDAP/Active Directory authentication (server, base DN, bind credentials, group restriction), enable/disable |
| **Security** | Change admin password, enable/disable MFA globally, manage own TOTP |

#### System

| Tab | Settings |
|-----|----------|
| **Branding** | Platform name, subtitle, logo upload, default language |
| **NetBird Docker Images** | Configured NetBird image tags (management, signal, relay, dashboard), pull images from Docker Hub |
| **NetBird MSP System** | Base domain, admin email, port ranges, data directory |
| **NetBird MSP Updates** | Appliance version info, check for updates, switch release branch |

#### External Systems

| Tab | Settings |
|-----|----------|
| **NPM Proxy** | NPM API URL, login credentials, SSL certificate mode (Let's Encrypt / Wildcard), wildcard certificate selection |
| **Windows DNS** | Windows DNS server integration for automatic DNS A-record creation/deletion on customer deploy/delete |

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

The **Monitoring** page shows:
- **System Overview** — Total customers, active/inactive, errors
- **Host Resources** — CPU, RAM, disk usage of the host machine
- **Customer Status** — Container health per customer (running/stopped)
- **NetBird Container Updates** — Compare local image digests against Docker Hub, pull new images, and update all outdated customer containers

### NetBird Container Updates

#### Workflow

1. **Check for updates** — Go to **Monitoring > NetBird Container Updates**, click **"Check Updates"**
   - Compares local image digests against Docker Hub
   - Shows which images have a new version available
   - Shows which customer containers are running outdated images
   - An orange badge appears next to customers in the dashboard list that need updating

2. **Pull new images** — Go to **Settings > NetBird Docker Images**, click **"Pull from Docker Hub"**
   - Pulls all 4 NetBird images (`management`, `signal`, `relay`, `dashboard`) in the background
   - Wait for the pull to complete before updating customers

3. **Update customers** — Return to **Monitoring > NetBird Container Updates**, click **"Update All Customers"**
   - Recreates containers for all customers whose running image is outdated
   - Customers are updated **sequentially** — one at a time
   - All bind-mounted volumes (database, keys, config) are preserved — **no data loss**
   - A per-customer results table is shown after completion

#### Per-Customer Update

To update a single customer:
1. Open the customer detail view
2. Go to the **Deployment** tab
3. Click **"Update Images"**

#### Update Badges

The dashboard customer list shows an orange **"Update"** badge next to any customer whose running containers are using an outdated local image. This check is fast (local-only, no network call) and runs automatically when the dashboard loads.

### Language Settings

- **Switch language** — Use the language switcher in the top navigation bar
- **Per-user default** — Set in Settings > Users during user creation
- **System default** — Set in Settings > Branding

### Dark Mode

Toggle dark/light mode using the moon/sun icon in the top navigation bar. The preference is saved in the browser.

### Multi-Factor Authentication (MFA)

TOTP-based MFA can be enabled globally for all local users. Azure AD and LDAP users are not affected (they use their own authentication systems).

#### Enable MFA
1. Go to **Settings > Security**
2. Toggle **"Enable MFA for all local users"**
3. Click **"Save MFA Settings"**

#### First Login with MFA
When MFA is enabled and a user logs in for the first time:
1. Enter username and password as usual
2. A QR code is displayed — scan it with an authenticator app (Google Authenticator, Microsoft Authenticator, Authy, etc.)
3. Enter the 6-digit code from the app to complete setup

#### Subsequent Logins
1. Enter username and password
2. Enter the 6-digit code from the authenticator app

#### Admin MFA Management
- **Reset a user's MFA** — In Settings > Users, click "Reset MFA" to force re-enrollment on next login
- **Disable own TOTP** — In Settings > Security, click "Disable my TOTP" to remove your own MFA setup
- **Disable MFA globally** — Uncheck the toggle in Settings > Security to allow login without MFA

### LDAP / Active Directory Authentication

Active Directory users can log in to the appliance using their AD credentials. Local admin accounts always work as a fallback regardless of LDAP status.

#### Setup
1. Go to **Settings > LDAP / AD**
2. Enable **"LDAP / AD Authentication"**
3. Enter LDAP server, port, bind DN (service account), bind password, and base DN
4. Optionally restrict access to members of a specific AD group
5. Click **Save LDAP Settings**

### Windows DNS Integration

Automatically create and delete DNS A-records in a Windows DNS server when customers are deployed or deleted.

#### Setup
1. Go to **Settings > Windows DNS**
2. Enable **"Windows DNS Integration"**
3. Enter the DNS server details
4. Click **Save DNS Settings**

### SSL Certificate Mode

The appliance supports two SSL certificate modes for customer proxy hosts, configurable under **Settings > NPM Proxy**:

#### Let's Encrypt (default)
Each customer gets an individual Let's Encrypt certificate via HTTP-01 validation. This is the default behavior and requires no additional setup beyond a valid admin email.

#### Wildcard Certificate
Use a pre-existing wildcard certificate (e.g. `*.yourdomain.com`) already uploaded in NPM. All customer proxy hosts share this certificate — no per-customer LE validation needed.

**Setup:**
1. Upload a wildcard certificate in Nginx Proxy Manager (e.g. via DNS challenge)
2. Go to **Settings > NPM Proxy**
3. Set **SSL Mode** to "Wildcard Certificate"
4. Click the refresh button to load certificates from NPM
5. Select your wildcard certificate from the dropdown
6. Click **Save NPM Settings**

New customer deployments will automatically use the selected wildcard certificate.

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
http://your-server:8000/api/docs
```

**Common Endpoints:**
```
POST   /api/customers                    # Create customer + deploy
GET    /api/customers                    # List all customers
GET    /api/customers/{id}               # Get customer details
PUT    /api/customers/{id}               # Update customer
DELETE /api/customers/{id}               # Delete customer

POST   /api/customers/{id}/start         # Start containers
POST   /api/customers/{id}/stop          # Stop containers
POST   /api/customers/{id}/restart       # Restart containers
GET    /api/customers/{id}/logs          # Get container logs
GET    /api/customers/{id}/health        # Health check
POST   /api/customers/{id}/update-images # Recreate containers with new images

GET    /api/settings/branding            # Get branding (public, no auth)
GET    /api/settings/npm-certificates    # List NPM SSL certificates
PUT    /api/settings                     # Update system settings

GET    /api/users                        # List users
POST   /api/users                        # Create user
POST   /api/users/{id}/reset-mfa         # Reset user's MFA

POST   /api/auth/mfa/setup               # Generate TOTP secret + QR code
POST   /api/auth/mfa/setup/complete      # Verify first TOTP code
POST   /api/auth/mfa/verify              # Verify TOTP code on login
GET    /api/auth/mfa/status              # Get MFA status
POST   /api/auth/mfa/disable             # Disable own TOTP

GET    /api/monitoring/images/check                  # Check Hub vs local digests for all images
POST   /api/monitoring/images/pull                   # Pull all NetBird images from Docker Hub (background)
GET    /api/monitoring/customers/local-update-status # Fast local-only update check (no network)
POST   /api/monitoring/customers/update-all          # Recreate outdated containers for all customers
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

NetBird image updates are managed entirely through the Web UI — no manual config changes required.

#### Step 1 — Pull new images

1. Go to **Settings > NetBird Docker Images**
2. Click **"Pull from Docker Hub"**
3. Wait for the pull to complete (progress shown inline)

#### Step 2 — Check which customers need updating

1. Go to **Monitoring > NetBird Container Updates**
2. Click **"Check Updates"**
3. The table shows per-image Hub vs. local digest comparison and which customers are running outdated containers

#### Step 3 — Update customer containers

- **All customers**: Click **"Update All Customers"** in the Monitoring page
  - Customers are updated sequentially, one at a time
  - A results table is shown after completion
- **Single customer**: Open the customer detail view > **Deployment** tab > **"Update Images"**

> All bind-mounted volumes (database, keys, config files) are preserved. Container recreation does not cause data loss.

---

## Security Best Practices

1. **Enable MFA** — activate TOTP-based multi-factor authentication in Settings > Security
2. **Change default credentials** immediately after installation
3. **Use strong passwords** (12+ characters recommended)
4. **Keep NPM credentials secure** — they are stored encrypted in the database
5. **Enable firewall** and only open required ports (TCP 8000, UDP relay range)
6. **Use HTTPS** — put the MSP appliance behind a reverse proxy with SSL
7. **Regular updates** — both the appliance and NetBird images
8. **Backup your database** — `data/netbird_msp.db` contains all configuration
9. **Monitor logs** — check for suspicious activity
10. **Restrict access** — use VPN or IP whitelist for the management interface

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

This software was developed with [Claude Code](https://claude.ai/claude-code) (Anthropic Claude Sonnet 4.6) — from architecture and backend logic to frontend UI and deployment scripts.

## Acknowledgments

- [Claude Code](https://claude.ai/claude-code) — AI-powered software development by Anthropic
- [NetBird](https://netbird.io/) — Open-source VPN solution
- [FastAPI](https://fastapi.tiangolo.com/) — High-performance Python framework
- [Nginx Proxy Manager](https://nginxproxymanager.com/) — Reverse proxy management
