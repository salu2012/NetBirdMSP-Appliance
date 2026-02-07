# 🚀 NetBird MSP Appliance - Quick Start Guide

Get up and running in 10 minutes!

## Prerequisites

- Ubuntu 22.04 or 24.04 LTS
- Root access
- 64GB RAM minimum (for 100 customers)
- 500GB SSD minimum
- Domain with wildcard DNS (*.yourdomain.com)

## Installation (3 commands!)

```bash
# 1. Clone repository
git clone https://github.com/yourusername/netbird-msp-appliance.git
cd netbird-msp-appliance

# 2. Run installer
chmod +x install.sh
sudo ./install.sh

# 3. Access web UI
# Open: http://YOUR_SERVER_IP:8000
# Default login will be shown at end of installation
```

## Post-Installation Configuration

### 1. First Login
- Use credentials displayed after installation
- **CHANGE PASSWORD IMMEDIATELY** in Settings

### 2. Configure System (Settings → System Configuration)

```yaml
Base Domain: yourdomain.com
Admin Email: admin@yourdomain.com
NPM API URL: http://nginx-proxy-manager:81/api
NPM API Token: <get from NPM interface>
```

### 3. Configure Firewall

```bash
# Allow web interface
sudo ufw allow 8000/tcp

# Allow NetBird relay ports (for up to 100 customers)
sudo ufw allow 3478:3577/udp

# Apply rules
sudo ufw reload
```

### 4. Get NPM API Token

1. Access your Nginx Proxy Manager
2. Go to Users → Edit your user
3. Copy the API token
4. Paste in NetBird MSP Appliance Settings

## Deploy Your First Customer

1. Click "New Customer"
2. Fill in:
   - Name: "Test Customer"
   - Subdomain: "test" (becomes test.yourdomain.com)
   - Email: customer@example.com
   - Max Devices: 20
3. Click "Deploy"
4. Wait 60-90 seconds
5. Done! Share the setup URL with your customer

## Verify DNS Configuration

Before deploying customers, ensure wildcard DNS works:

```bash
# Test DNS resolution
nslookup test.yourdomain.com
# Should return your server IP

# Or
dig test.yourdomain.com
```

## Troubleshooting

### Customer deployment fails
```bash
# Check logs
docker logs netbird-msp-appliance

# Check NPM connectivity
curl -I http://nginx-proxy-manager:81/api
```

### NPM not accessible
Make sure NPM is on the same Docker network:
```bash
docker network connect npm-network <npm-container-name>
```

### Ports already in use
```bash
# Check what's using port 8000
sudo lsof -i :8000

# Kill process if needed
sudo kill -9 <PID>
```

## Next Steps

- Read full [README.md](README.md) for details
- Check [CONTRIBUTING.md](CONTRIBUTING.md) to contribute
- Join discussions for support

## Quick Commands

```bash
# View logs
docker logs -f netbird-msp-appliance

# Restart appliance
docker restart netbird-msp-appliance

# Stop all customer instances
docker stop $(docker ps -q --filter "name=netbird-kunde")

# Backup database
docker exec netbird-msp-appliance cp /app/data/netbird_msp.db /app/data/backup-$(date +%Y%m%d).db
```

## System Requirements Calculator

| Customers | RAM | CPU | Disk |
|-----------|-----|-----|------|
| 25        | 16GB | 4 cores | 200GB |
| 50        | 32GB | 8 cores | 350GB |
| 100       | 64GB | 16 cores | 500GB |
| 200       | 128GB | 32 cores | 1TB |

Formula: `(Customers × 600MB) + 8GB (OS + Appliance)`

Happy MSP-ing! 🎉
