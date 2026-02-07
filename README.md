# NetBird MSP Appliance

🚀 **Self-Hosted Multi-Tenant NetBird Management Platform**

A complete management solution for running 100+ isolated NetBird instances for your MSP business. Manage all your customers' NetBird networks from a single, powerful web interface.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Docker](https://img.shields.io/badge/docker-required-blue.svg)
![Python](https://img.shields.io/badge/python-3.11+-blue.svg)

---

## 📋 Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [System Requirements](#system-requirements)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Usage](#usage)
- [API Documentation](#api-documentation)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

---

## ✨ Features

- **🎯 Multi-Tenant Management**: Manage 100+ isolated NetBird instances from one dashboard
- **🔒 Complete Isolation**: Each customer gets their own NetBird instance with separate databases
- **🌐 Nginx Proxy Manager Integration**: Automatic SSL certificate management and reverse proxy setup
- **🐳 Docker-Based**: Everything runs in containers for easy deployment and updates
- **📊 Web Dashboard**: Modern, responsive UI for managing customers and deployments
- **🚀 One-Click Deployment**: Deploy new customer instances in under 2 minutes
- **📈 Monitoring**: Real-time status monitoring and health checks
- **🔄 Automated Updates**: Bulk update NetBird containers across all customers
- **💾 Backup & Restore**: Built-in backup functionality for all customer data
- **🔐 Secure by Default**: Encrypted credentials, API tokens, and secrets management

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    NetBird MSP Appliance                    │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐   ┌───────────────┐ │
│  │   Web GUI    │───▶│  FastAPI     │──▶│   SQLite DB   │ │
│  │  (Bootstrap) │    │   Backend    │   │               │ │
│  └──────────────┘    └──────────────┘   └───────────────┘ │
│                             │                              │
│         ┌───────────────────┼───────────────────┐         │
│         ▼                   ▼                   ▼          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐   │
│  │   Docker    │    │    NPM      │    │  Firewall   │   │
│  │   Engine    │    │     API     │    │   Manager   │   │
│  └─────────────┘    └─────────────┘    └─────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┴───────────────────┐
        ▼                                       ▼
┌──────────────────┐                  ┌──────────────────┐
│  Customer 1      │                  │  Customer 100    │
│  ┌────────────┐  │                  │  ┌────────────┐  │
│  │ Management │  │                  │  │ Management │  │
│  │   Signal   │  │       ...        │  │   Signal   │  │
│  │   Relay    │  │                  │  │   Relay    │  │
│  │  Dashboard │  │                  │  │  Dashboard │  │
│  └────────────┘  │                  │  └────────────┘  │
└──────────────────┘                  └──────────────────┘
  kunde1.domain.de                      kunde100.domain.de
  UDP 3478                              UDP 3577
```

### Components per Customer Instance:
- **Management Service**: API and network state management
- **Signal Service**: WebRTC signaling for peer connections
- **Relay Service**: STUN/TURN server for NAT traversal (requires public UDP port)
- **Dashboard**: Web UI for end-users

All services are accessible via HTTPS through Nginx Proxy Manager, except the Relay STUN port which requires direct UDP access.

---

## 💻 System Requirements

### For 100 Customers (10-20 devices per customer)

| Component | Minimum | Recommended | Notes |
|-----------|---------|-------------|-------|
| **CPU** | 8 cores | 16 cores | More cores = better concurrent deployment performance |
| **RAM** | 64 GB | 128 GB | ~600 MB per customer instance + OS overhead |
| **Storage** | 500 GB SSD | 1 TB NVMe SSD | Fast I/O critical for Docker performance |
| **Network** | 100 Mbps | 1 Gbps | Dedicated server recommended |
| **OS** | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS | Other Debian-based distros work too |

### Resource Calculation Formula:
```
Per Customer Instance:
- Management: ~100 MB RAM
- Signal: ~50 MB RAM
- Relay: ~150 MB RAM
- Dashboard: ~100 MB RAM
Total: ~400-600 MB RAM per customer

For 100 customers: 40-60 GB RAM + 8 GB for OS + 8 GB for Appliance = ~64 GB minimum
```

### Port Requirements:
- **TCP 8000**: NetBird MSP Appliance Web UI
- **UDP 3478-3577**: STUN/TURN relay ports (one per customer)
  - Customer 1: UDP 3478
  - Customer 2: UDP 3479
  - ...
  - Customer 100: UDP 3577

**⚠️ Important**: Your firewall must allow UDP ports 3478-3577 for full NetBird functionality!

### Prerequisites:
- **Docker Engine** 24.0+ with Docker Compose plugin
- **Nginx Proxy Manager** (running separately or on same host)
- **Domain with wildcard DNS** (e.g., `*.yourdomain.com` → your server IP)
- **Root or sudo access** to the Linux VM

---

## 🚀 Quick Start

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
- ✅ Admin username and password
- ✅ Admin email address
- ✅ Base domain (e.g., `yourdomain.com`)
- ✅ Nginx Proxy Manager API URL and token
- ✅ Data directory location
- ✅ NetBird Docker images (optional customization)

**No manual .env file editing required!** Everything is configured through the installation wizard.

The installer will then:
- ✅ Check system requirements
- ✅ Install Docker if needed
- ✅ Create directories and Docker network
- ✅ Generate encryption keys
- ✅ Build and start all containers
- ✅ Configure firewall (optional)
- ✅ Initialize the database

### 3. Access the Web Interface

After installation completes, open your browser:
```
http://your-server-ip:8000
```

Login with the credentials you provided during installation.

**All settings can be changed later via the Web UI!**

### 4. Deploy Your First Customer

1. Click **"New Customer"** button
2. Fill in customer details:
   - Name
   - Subdomain (e.g., `customer1` → `customer1.yourdomain.com`)
   - Email
   - Max Devices
3. Click **"Deploy"**
4. Wait ~60-90 seconds
5. Done! ✅

The system will automatically:
- Assign a unique UDP port for the relay
- Generate all config files
- Start Docker containers
- Create NPM proxy hosts with SSL
- Provide the setup URL

---

## ⚙️ Configuration

### Environment Variables

Create a `.env` file (or use the one generated by installer):

```bash
# Security
SECRET_KEY=your-secure-random-key-here
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your-secure-password

# Nginx Proxy Manager
NPM_API_URL=http://nginx-proxy-manager:81/api
NPM_API_TOKEN=your-npm-api-token

# System
DATA_DIR=/opt/netbird-instances
DOCKER_NETWORK=npm-network
BASE_DOMAIN=yourdomain.com
ADMIN_EMAIL=admin@yourdomain.com

# NetBird Images (optional - defaults to latest)
NETBIRD_MANAGEMENT_IMAGE=netbirdio/management:latest
NETBIRD_SIGNAL_IMAGE=netbirdio/signal:latest
NETBIRD_RELAY_IMAGE=netbirdio/relay:latest
NETBIRD_DASHBOARD_IMAGE=netbirdio/dashboard:latest

# Database
DATABASE_PATH=/app/data/netbird_msp.db

# Logging
LOG_LEVEL=INFO
```

### System Configuration via Web UI

All settings can be configured through the web interface under **Settings** → **System Configuration**:

- Base Domain
- Admin Email
- NPM Integration
- Docker Images
- Port Ranges
- Data Directories

Changes are applied immediately without restart.

---

## 📖 Usage

### Managing Customers

#### Create a New Customer
1. Dashboard → **New Customer**
2. Fill in details
3. Click **Deploy**
4. Share the setup URL with your customer

#### View Customer Details
- Click on customer name in the list
- See deployment status, container health, logs
- Copy setup URL and credentials

#### Start/Stop/Restart Containers
- Click the action buttons in the customer list
- Or use the detail view for more control

#### Delete a Customer
- Click **Delete** → Confirm
- All containers, data, and NPM entries are removed

### Monitoring

The dashboard shows:
- **System Overview**: Total customers, active/inactive, errors
- **Resource Usage**: RAM, CPU, disk usage
- **Container Status**: Running/stopped/failed
- **Recent Activity**: Deployment logs and events

### Bulk Operations

Select multiple customers using checkboxes:
- **Bulk Update**: Update NetBird images across selected customers
- **Bulk Restart**: Restart all selected instances
- **Bulk Backup**: Create backups of selected customers

### Backups

#### Manual Backup
```bash
docker exec netbird-msp-appliance python -m app.backup --customer-id 1
```

#### Automatic Backups
Configure in Settings → Backup:
- Schedule: Daily/Weekly
- Retention: Number of backups to keep
- Destination: Local path or remote storage

---

## 🔌 API Documentation

The appliance provides a REST API for automation.

### Authentication
```bash
# Get API token (after login)
curl -X POST http://localhost:8000/api/auth/token \
  -d "username=admin&password=yourpassword"
```

### API Endpoints

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
GET    /api/customers/{id}/logs    # Get container logs
GET    /api/customers/{id}/health  # Health check

GET    /api/status                 # System status
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

## 🔧 Troubleshooting

### Common Issues

#### 1. Customer deployment fails
**Symptom**: Status shows "error" after deployment

**Solutions**:
- Check Docker logs: `docker logs netbird-msp-appliance`
- Verify NPM is accessible: `curl http://npm-host:81/api`
- Check available UDP ports: `netstat -ulnp | grep 347`
- View detailed logs in the customer detail page

#### 2. NetBird clients can't connect
**Symptom**: Clients show "relay unavailable"

**Solutions**:
- **Most common**: UDP port not open in firewall
  ```bash
  # Check if port is open
  sudo ufw status
  
  # Open the relay port
  sudo ufw allow 3478/udp
  ```
- Verify relay container is running: `docker ps | grep relay`
- Test STUN server: Use online STUN tester with your port

#### 3. NPM integration not working
**Symptom**: SSL certificates not created

**Solutions**:
- Verify NPM API token is correct
- Check NPM is on same Docker network: `npm-network`
- Test NPM API manually:
  ```bash
  curl -X GET http://npm-host:81/api/nginx/proxy-hosts \
    -H "Authorization: Bearer YOUR_TOKEN"
  ```

#### 4. Out of memory errors
**Symptom**: Containers crashing, system slow

**Solutions**:
- Check RAM usage: `free -h`
- Reduce number of customers or upgrade RAM
- Stop inactive customer instances
- Configure swap space:
  ```bash
  sudo fallocate -l 16G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  ```

### Debug Mode

Enable debug logging:
```bash
# Edit .env
LOG_LEVEL=DEBUG

# Restart
docker-compose restart
```

View detailed logs:
```bash
docker logs -f netbird-msp-appliance
```

### Getting Help

1. **Check the logs**: Most issues are explained in the logs
2. **GitHub Issues**: Search existing issues or create a new one
3. **NetBird Community**: For NetBird-specific questions
4. **Documentation**: Read the full docs in `/docs` folder

---

## 🔄 Updates

### Updating the Appliance

```bash
cd netbird-msp-appliance
git pull
docker-compose down
docker-compose up -d --build
```

### Updating NetBird Images

**Via Web UI**:
1. Settings → System Configuration
2. Update image tags
3. Click "Save"
4. Use Bulk Update for customers

**Via CLI**:
```bash
# Update all customer instances
docker exec netbird-msp-appliance python -m app.update --all
```

---

## 🛡️ Security Best Practices

1. **Change default credentials** immediately after installation
2. **Use strong passwords** (20+ characters, mixed case, numbers, symbols)
3. **Keep NPM API token secure** - never commit to git
4. **Enable firewall** and only open required ports
5. **Regular updates** - both the appliance and NetBird images
6. **Backup regularly** - automate daily backups
7. **Use HTTPS** - always access the web UI via HTTPS (configure reverse proxy)
8. **Monitor logs** - check for suspicious activity
9. **Limit access** - use VPN or IP whitelist for the management interface

---

## 📊 Performance Tuning

### For 100+ Customers:

```bash
# Increase Docker ulimits
# Add to /etc/docker/daemon.json
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

## 🤝 Contributing

Contributions welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) first.

---

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **NetBird Team** - for the amazing open-source VPN solution
- **FastAPI** - for the high-performance Python framework
- **Nginx Proxy Manager** - for easy reverse proxy management

---

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/netbird-msp-appliance/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/netbird-msp-appliance/discussions)
- **Email**: support@yourdomain.com

---

**Made with ❤️ for MSPs and System Administrators**
