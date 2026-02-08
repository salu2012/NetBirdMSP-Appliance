#!/bin/bash

# NetBird MSP Appliance - Interactive Installation Script
# This script sets up the complete NetBird MSP management platform
# All configuration is done interactively and stored in the DATABASE.
# There is NO .env file for application config!

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Configuration
INSTALL_DIR="/opt/netbird-msp"
DOCKER_NETWORK="npm-network"
CONTAINER_NAME="netbird-msp-appliance"

clear
echo -e "${BLUE}"
cat << 'BANNER'
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║       NetBird MSP Appliance - Interactive Installer      ║
║                                                           ║
║   Multi-Tenant NetBird Management Platform               ║
║                                                           ║
║   All config stored in database - no .env editing!       ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
BANNER
echo -e "${NC}"

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}Error: This script must be run as root${NC}"
   echo "Please run: sudo $0"
   exit 1
fi

echo -e "${GREEN}Welcome to the NetBird MSP Appliance installer!${NC}"
echo -e "This wizard will guide you through the installation process.\n"
sleep 2

# ============================================================================
# STEP 1: SYSTEM REQUIREMENTS CHECK
# ============================================================================
echo -e "${BLUE}${BOLD}[Step 1/10]${NC} ${BLUE}Checking system requirements...${NC}\n"

# Check CPU cores
CPU_CORES=$(nproc)
echo -e "CPU Cores: ${CYAN}$CPU_CORES${NC}"
echo -e "${GREEN}✓ CPU cores detected${NC}"

# Check disk space
DISK_SPACE=$(df -BG / | awk 'NR==2 {print $4}' | sed 's/G//')
echo -e "Free Disk Space: ${CYAN}${DISK_SPACE}GB${NC}"
if [ "$DISK_SPACE" -lt 50 ]; then
    echo -e "${YELLOW}Warning: Only ${DISK_SPACE}GB free disk space.${NC}"
    echo -e "${YELLOW}  At least 50GB recommended.${NC}"
else
    echo -e "${GREEN}✓ Disk space: Sufficient${NC}"
fi

echo ""
read -p "Press ENTER to continue..."
clear

# ============================================================================
# STEP 2: DOCKER INSTALLATION
# ============================================================================
echo -e "${BLUE}${BOLD}[Step 2/10]${NC} ${BLUE}Checking Docker installation...${NC}\n"

if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}Docker not found. Installing Docker...${NC}"
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
    systemctl enable docker
    systemctl start docker
    echo -e "${GREEN}✓ Docker installed successfully${NC}"
else
    DOCKER_VERSION=$(docker --version | awk '{print $3}' | sed 's/,//')
    echo -e "${GREEN}✓ Docker already installed (${DOCKER_VERSION})${NC}"
fi

# Check Docker Compose
if ! docker compose version &> /dev/null; then
    echo -e "${RED}Error: Docker Compose plugin not found${NC}"
    echo "Please install Docker Compose plugin: https://docs.docker.com/compose/install/"
    exit 1
else
    echo -e "${GREEN}✓ Docker Compose available${NC}"
fi

echo ""
read -p "Press ENTER to continue..."
clear

# ============================================================================
# STEP 3: CONFIGURATION - BASIC SETTINGS
# ============================================================================
echo -e "${BLUE}${BOLD}[Step 3/10]${NC} ${BLUE}Basic Configuration${NC}\n"

echo -e "${CYAN}Please provide the following information:${NC}\n"

# Admin Username
while true; do
    read -p "Admin Username [admin]: " ADMIN_USERNAME
    ADMIN_USERNAME=${ADMIN_USERNAME:-admin}
    if [[ "$ADMIN_USERNAME" =~ ^[a-zA-Z0-9_-]+$ ]]; then
        break
    else
        echo -e "${RED}Invalid username. Use only letters, numbers, dash and underscore.${NC}"
    fi
done

# Admin Password
while true; do
    read -sp "Admin Password (min 12 chars): " ADMIN_PASSWORD
    echo ""
    if [ ${#ADMIN_PASSWORD} -ge 12 ]; then
        read -sp "Confirm Password: " ADMIN_PASSWORD_CONFIRM
        echo ""
        if [ "$ADMIN_PASSWORD" == "$ADMIN_PASSWORD_CONFIRM" ]; then
            break
        else
            echo -e "${RED}Passwords do not match. Try again.${NC}"
        fi
    else
        echo -e "${RED}Password must be at least 12 characters long.${NC}"
    fi
done

# Admin Email
while true; do
    read -p "Admin Email: " ADMIN_EMAIL
    if [[ "$ADMIN_EMAIL" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
        break
    else
        echo -e "${RED}Invalid email address.${NC}"
    fi
done

echo -e "\n${GREEN}✓ Basic configuration saved${NC}"
sleep 1
clear

# ============================================================================
# STEP 4: CONFIGURATION - DOMAIN
# ============================================================================
echo -e "${BLUE}${BOLD}[Step 4/10]${NC} ${BLUE}Domain Configuration${NC}\n"

echo -e "${CYAN}Your customers will get subdomains like: kunde1.yourdomain.com${NC}\n"

while true; do
    read -p "Base Domain (e.g., yourdomain.com): " BASE_DOMAIN
    if [[ "$BASE_DOMAIN" =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$ ]]; then
        echo -e "\n${YELLOW}Important: Make sure you have wildcard DNS configured:${NC}"
        echo -e "${YELLOW}  *.${BASE_DOMAIN} → Your server IP${NC}\n"
        read -p "Is your DNS configured? (yes/no): " DNS_CONFIRM
        if [[ "$DNS_CONFIRM" =~ ^[Yy]([Ee][Ss])?$ ]]; then
            break
        else
            echo -e "${YELLOW}Please configure DNS first, then restart the installer.${NC}"
            exit 0
        fi
    else
        echo -e "${RED}Invalid domain format.${NC}"
    fi
done

echo -e "\n${CYAN}Optional: You can assign a domain to the MSP Appliance itself.${NC}"
echo -e "${CYAN}This will create an NPM proxy host with Let's Encrypt SSL.${NC}"
echo -e "${CYAN}Example: msp.${BASE_DOMAIN}${NC}\n"

read -p "MSP Appliance Domain (leave empty to skip): " MSP_DOMAIN
if [ -n "$MSP_DOMAIN" ]; then
    echo -e "${GREEN}✓ MSP Appliance will be accessible at https://${MSP_DOMAIN}${NC}"
fi

echo -e "${GREEN}✓ Domain configuration saved${NC}"
sleep 1
clear

# ============================================================================
# STEP 5: CONFIGURATION - NGINX PROXY MANAGER
# ============================================================================
echo -e "${BLUE}${BOLD}[Step 5/10]${NC} ${BLUE}Nginx Proxy Manager Configuration${NC}\n"

echo -e "${CYAN}NetBird MSP needs to integrate with Nginx Proxy Manager (NPM).${NC}\n"

# NPM API URL
echo -e "${YELLOW}NPM uses JWT authentication (email + password login).${NC}"
echo -e "${YELLOW}There are no static API keys — the system logs in automatically.${NC}\n"

while true; do
    read -p "NPM API URL [http://nginx-proxy-manager:81/api]: " NPM_API_URL
    NPM_API_URL=${NPM_API_URL:-http://nginx-proxy-manager:81/api}
    if [[ "$NPM_API_URL" =~ ^https?:// ]]; then
        break
    else
        echo -e "${RED}Invalid URL format. Must start with http:// or https://${NC}"
    fi
done

# NPM Login Email
echo ""
while true; do
    read -p "NPM Login Email (your NPM admin email): " NPM_EMAIL
    if [[ "$NPM_EMAIL" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
        break
    else
        echo -e "${RED}Invalid email address.${NC}"
    fi
done

# NPM Login Password
while true; do
    read -sp "NPM Login Password: " NPM_PASSWORD
    echo ""
    if [ ${#NPM_PASSWORD} -ge 1 ]; then
        break
    else
        echo -e "${RED}Password cannot be empty.${NC}"
    fi
done

echo -e "${GREEN}✓ NPM configuration saved${NC}"
sleep 1
clear

# ============================================================================
# STEP 6: CONFIGURATION - DIRECTORIES
# ============================================================================
echo -e "${BLUE}${BOLD}[Step 6/10]${NC} ${BLUE}Directory Configuration${NC}\n"

echo -e "${CYAN}Where should customer NetBird instances be stored?${NC}\n"

read -p "Data Directory [/opt/netbird-instances]: " DATA_DIR
DATA_DIR=${DATA_DIR:-/opt/netbird-instances}

echo -e "\n${YELLOW}The following directories will be created:${NC}"
echo -e "  - ${DATA_DIR} (customer instances)"
echo -e "  - ${INSTALL_DIR} (application)"
echo -e "  - ${INSTALL_DIR}/data (database)"
echo -e "  - ${INSTALL_DIR}/logs (logs)"
echo -e "  - ${INSTALL_DIR}/backups (backups)\n"

echo -e "${GREEN}✓ Directory configuration saved${NC}"
sleep 1
clear

# ============================================================================
# STEP 7: CONFIGURATION - DOCKER IMAGES (OPTIONAL)
# ============================================================================
echo -e "${BLUE}${BOLD}[Step 7/10]${NC} ${BLUE}NetBird Docker Images${NC}\n"

echo -e "${CYAN}You can customize the NetBird Docker images or use defaults.${NC}\n"

read -p "Customize Docker images? (yes/no) [no]: " CUSTOMIZE_IMAGES
CUSTOMIZE_IMAGES=${CUSTOMIZE_IMAGES:-no}

if [[ "$CUSTOMIZE_IMAGES" =~ ^[Yy]([Ee][Ss])?$ ]]; then
    read -p "Management Image [netbirdio/management:latest]: " NETBIRD_MANAGEMENT_IMAGE
    NETBIRD_MANAGEMENT_IMAGE=${NETBIRD_MANAGEMENT_IMAGE:-netbirdio/management:latest}

    read -p "Signal Image [netbirdio/signal:latest]: " NETBIRD_SIGNAL_IMAGE
    NETBIRD_SIGNAL_IMAGE=${NETBIRD_SIGNAL_IMAGE:-netbirdio/signal:latest}

    read -p "Relay Image [netbirdio/relay:latest]: " NETBIRD_RELAY_IMAGE
    NETBIRD_RELAY_IMAGE=${NETBIRD_RELAY_IMAGE:-netbirdio/relay:latest}

    read -p "Dashboard Image [netbirdio/dashboard:latest]: " NETBIRD_DASHBOARD_IMAGE
    NETBIRD_DASHBOARD_IMAGE=${NETBIRD_DASHBOARD_IMAGE:-netbirdio/dashboard:latest}
else
    NETBIRD_MANAGEMENT_IMAGE="netbirdio/management:latest"
    NETBIRD_SIGNAL_IMAGE="netbirdio/signal:latest"
    NETBIRD_RELAY_IMAGE="netbirdio/relay:latest"
    NETBIRD_DASHBOARD_IMAGE="netbirdio/dashboard:latest"
fi

echo -e "${GREEN}✓ Docker image configuration saved${NC}"
sleep 1
clear

# ============================================================================
# STEP 8: INSTALLATION (stores config in DATABASE, not .env)
# ============================================================================
echo -e "${BLUE}${BOLD}[Step 8/10]${NC} ${BLUE}Installation${NC}\n"

echo -e "${CYAN}Ready to install with the following configuration:${NC}\n"
echo -e "  Admin Username:  ${GREEN}$ADMIN_USERNAME${NC}"
echo -e "  Admin Email:     ${GREEN}$ADMIN_EMAIL${NC}"
echo -e "  Base Domain:     ${GREEN}$BASE_DOMAIN${NC}"
if [ -n "$MSP_DOMAIN" ]; then
    echo -e "  MSP Domain:      ${GREEN}$MSP_DOMAIN${NC}"
fi
echo -n ""
echo -e "  NPM API URL:     ${GREEN}$NPM_API_URL${NC}"
echo -e "  NPM Login:       ${GREEN}$NPM_EMAIL${NC}"
echo -e "  Data Directory:  ${GREEN}$DATA_DIR${NC}"
echo -e "  Install Dir:     ${GREEN}$INSTALL_DIR${NC}\n"

read -p "Proceed with installation? (yes/no): " PROCEED
if [[ ! "$PROCEED" =~ ^[Yy]([Ee][Ss])?$ ]]; then
    echo -e "${YELLOW}Installation cancelled.${NC}"
    exit 0
fi

echo -e "\n${GREEN}Starting installation...${NC}\n"

# Create directories
echo "Creating directories..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$DATA_DIR"
mkdir -p "$INSTALL_DIR/data"
mkdir -p "$INSTALL_DIR/logs"
mkdir -p "$INSTALL_DIR/backups"
echo -e "${GREEN}✓ Directories created${NC}"

# Create Docker network
echo "Setting up Docker network..."
if docker network inspect $DOCKER_NETWORK &> /dev/null; then
    echo -e "${GREEN}✓ Docker network '$DOCKER_NETWORK' already exists${NC}"
else
    docker network create $DOCKER_NETWORK
    echo -e "${GREEN}✓ Docker network '$DOCKER_NETWORK' created${NC}"
fi

# Generate secret key for encryption (only env-level secret)
echo "Generating encryption keys..."
SECRET_KEY=$(openssl rand -base64 32)
echo -e "${GREEN}✓ Encryption keys generated${NC}"

# Create MINIMAL .env — only container-level vars needed by docker-compose.yml
# All application config goes into the DATABASE, not here!
echo "Creating minimal container environment..."
cat > "$INSTALL_DIR/.env" << ENVEOF
# Container-level environment only (NOT application config!)
# All settings are stored in the database and editable via Web UI.
SECRET_KEY=$SECRET_KEY
DATABASE_PATH=/app/data/netbird_msp.db
DATA_DIR=$DATA_DIR
DOCKER_NETWORK=$DOCKER_NETWORK
LOG_LEVEL=INFO
WEB_UI_PORT=8000
ENVEOF

chmod 600 "$INSTALL_DIR/.env"
echo -e "${GREEN}✓ Container environment created${NC}"

# Copy application files (including .git for updates via git pull)
echo "Copying application files..."
cp -a . "$INSTALL_DIR/" 2>/dev/null || true
cd "$INSTALL_DIR"
echo -e "${GREEN}✓ Files copied to $INSTALL_DIR${NC}"

# Build and start containers
echo "Building and starting Docker containers..."
docker compose up -d --build

# Wait for container to be ready
echo "Waiting for application to start..."
sleep 15

if docker ps | grep -q $CONTAINER_NAME; then
    echo -e "${GREEN}✓ Container started successfully${NC}"
else
    echo -e "${RED}Error: Container failed to start${NC}"
    echo "Check logs with: docker logs $CONTAINER_NAME"
    exit 1
fi

# Initialize database tables
echo "Initializing database..."
docker exec $CONTAINER_NAME python -m app.database init || true
echo -e "${GREEN}✓ Database tables created${NC}"

# Seed all configuration into the database (system_config + users table)
echo "Seeding configuration into database..."
docker exec $CONTAINER_NAME python -c "
import os
os.environ['SECRET_KEY'] = '$SECRET_KEY'

from app.database import SessionLocal, init_db
from app.models import SystemConfig, User
from app.utils.security import hash_password, encrypt_value

init_db()
db = SessionLocal()

# Create admin user
existing_user = db.query(User).filter(User.username == '$ADMIN_USERNAME').first()
if not existing_user:
    user = User(
        username='$ADMIN_USERNAME',
        password_hash=hash_password('$ADMIN_PASSWORD'),
        email='$ADMIN_EMAIL',
    )
    db.add(user)
    print('Admin user created.')
else:
    print('Admin user already exists.')

# Create system config (singleton row)
existing_config = db.query(SystemConfig).filter(SystemConfig.id == 1).first()
if not existing_config:
    config = SystemConfig(
        id=1,
        base_domain='$BASE_DOMAIN',
        admin_email='$ADMIN_EMAIL',
        npm_api_url='$NPM_API_URL',
        npm_api_email_encrypted=encrypt_value('$NPM_EMAIL'),
        npm_api_password_encrypted=encrypt_value('$NPM_PASSWORD'),
        netbird_management_image='$NETBIRD_MANAGEMENT_IMAGE',
        netbird_signal_image='$NETBIRD_SIGNAL_IMAGE',
        netbird_relay_image='$NETBIRD_RELAY_IMAGE',
        netbird_dashboard_image='$NETBIRD_DASHBOARD_IMAGE',
        data_dir='$DATA_DIR',
        docker_network='$DOCKER_NETWORK',
        relay_base_port=3478,
    )
    db.add(config)
    print('System configuration saved to database.')
else:
    print('System configuration already exists.')

db.commit()
db.close()
print('Database seeding complete.')
"
echo -e "${GREEN}✓ Configuration stored in database${NC}"

# Create NPM proxy host for MSP Appliance (if domain was specified)
if [ -n "$MSP_DOMAIN" ]; then
    echo ""
    echo -e "${CYAN}Creating NPM proxy host for MSP Appliance (${MSP_DOMAIN})...${NC}"

    # Determine forward host from NPM API URL
    NPM_HOST=$(echo "$NPM_API_URL" | sed -E 's|https?://([^:/]+).*|\1|')

    # If host looks like a container name (no dots), use Docker gateway
    if ! echo "$NPM_HOST" | grep -q '\.'; then
        FORWARD_HOST="172.17.0.1"
    else
        FORWARD_HOST="$NPM_HOST"
    fi

    # Step 1: Login to NPM
    NPM_TOKEN=$(curl -s -X POST "${NPM_API_URL}/tokens" \
        -H "Content-Type: application/json" \
        -d "{\"identity\": \"${NPM_EMAIL}\", \"secret\": \"${NPM_PASSWORD}\"}" \
        2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))" 2>/dev/null || echo "")

    if [ -n "$NPM_TOKEN" ] && [ "$NPM_TOKEN" != "None" ]; then
        # Step 2: Create proxy host
        PROXY_RESULT=$(curl -s -X POST "${NPM_API_URL}/nginx/proxy-hosts" \
            -H "Authorization: Bearer ${NPM_TOKEN}" \
            -H "Content-Type: application/json" \
            -d "{
                \"domain_names\": [\"${MSP_DOMAIN}\"],
                \"forward_scheme\": \"http\",
                \"forward_host\": \"${FORWARD_HOST}\",
                \"forward_port\": 8000,
                \"certificate_id\": 0,
                \"ssl_forced\": true,
                \"hsts_enabled\": true,
                \"hsts_subdomains\": false,
                \"http2_support\": true,
                \"block_exploits\": true,
                \"allow_websocket_upgrade\": true,
                \"access_list_id\": 0,
                \"advanced_config\": \"\",
                \"meta\": {
                    \"letsencrypt_agree\": true,
                    \"letsencrypt_email\": \"${ADMIN_EMAIL}\",
                    \"dns_challenge\": false
                }
            }" 2>/dev/null)

        PROXY_ID=$(echo "$PROXY_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")

        if [ -n "$PROXY_ID" ] && [ "$PROXY_ID" != "None" ] && [ "$PROXY_ID" != "" ]; then
            echo -e "${GREEN}✓ NPM proxy host created (ID: ${PROXY_ID})${NC}"

            # Step 3: Request Let's Encrypt certificate
            CERT_RESULT=$(curl -s -X POST "${NPM_API_URL}/nginx/certificates" \
                -H "Authorization: Bearer ${NPM_TOKEN}" \
                -H "Content-Type: application/json" \
                -d "{
                    \"domain_names\": [\"${MSP_DOMAIN}\"],
                    \"provider\": \"letsencrypt\",
                    \"nice_name\": \"${MSP_DOMAIN}\",
                    \"meta\": {
                        \"letsencrypt_agree\": true,
                        \"letsencrypt_email\": \"${ADMIN_EMAIL}\",
                        \"dns_challenge\": false
                    }
                }" 2>/dev/null)

            CERT_ID=$(echo "$CERT_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")

            if [ -n "$CERT_ID" ] && [ "$CERT_ID" != "None" ] && [ "$CERT_ID" != "" ]; then
                # Step 4: Assign certificate to proxy host
                curl -s -X PUT "${NPM_API_URL}/nginx/proxy-hosts/${PROXY_ID}" \
                    -H "Authorization: Bearer ${NPM_TOKEN}" \
                    -H "Content-Type: application/json" \
                    -d "{\"certificate_id\": ${CERT_ID}}" > /dev/null 2>&1

                echo -e "${GREEN}✓ Let's Encrypt SSL certificate created and assigned${NC}"
            else
                echo -e "${YELLOW}⚠ SSL certificate request failed. You can add it manually in NPM.${NC}"
            fi
        else
            echo -e "${YELLOW}⚠ NPM proxy host creation failed. You can create it manually in NPM.${NC}"
            echo -e "${YELLOW}  Forward ${MSP_DOMAIN} → ${FORWARD_HOST}:8000${NC}"
        fi
    else
        echo -e "${YELLOW}⚠ NPM login failed. You can create the proxy host manually in NPM.${NC}"
        echo -e "${YELLOW}  Forward ${MSP_DOMAIN} → ${FORWARD_HOST}:8000${NC}"
    fi
fi

clear

# ============================================================================
# STEP 9: FIREWALL CONFIGURATION
# ============================================================================
echo -e "${BLUE}${BOLD}[Step 9/10]${NC} ${BLUE}Firewall Configuration${NC}\n"

echo -e "${CYAN}The following firewall ports need to be opened:${NC}\n"
echo -e "  ${YELLOW}TCP 8000${NC}           - MSP Appliance Web UI"
echo -e "  ${YELLOW}TCP 9001-9100${NC}      - NetBird Web Management (one per customer, increments by 1)"
echo -e "  ${YELLOW}UDP 3478-3577${NC}      - NetBird Relay/STUN (one per customer, increments by 1)\n"
echo -e "  ${CYAN}Example: Customer 1 = TCP 9001 + UDP 3478${NC}"
echo -e "  ${CYAN}         Customer 2 = TCP 9002 + UDP 3479${NC}"
echo -e "  ${CYAN}         ...${NC}\n"

if command -v ufw &> /dev/null; then
    read -p "Configure firewall automatically with ufw? (yes/no): " CONFIG_FW
    if [[ "$CONFIG_FW" =~ ^[Yy]([Ee][Ss])?$ ]]; then
        ufw allow 8000/tcp comment "NetBird MSP Web UI"
        ufw allow 9001:9100/tcp comment "NetBird Dashboard Ports"
        ufw allow 3478:3577/udp comment "NetBird Relay Ports"
        echo -e "${GREEN}✓ Firewall configured${NC}"
    else
        echo -e "${YELLOW}Please configure firewall manually:${NC}"
        echo "  sudo ufw allow 8000/tcp"
        echo "  sudo ufw allow 9001:9100/tcp"
        echo "  sudo ufw allow 3478:3577/udp"
    fi
else
    echo -e "${YELLOW}UFW not found. Please configure firewall manually:${NC}"
    echo "  - Allow TCP port 8000"
    echo "  - Allow TCP ports 9001-9100 (dashboard, +1 per customer)"
    echo "  - Allow UDP ports 3478-3577 (relay, +1 per customer)"
fi

echo ""
read -p "Press ENTER to continue..."
clear

# ============================================================================
# STEP 10: COMPLETION
# ============================================================================
echo -e "${GREEN}${BOLD}"
cat << 'SUCCESS'
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║        ✓✓✓ Installation Completed Successfully! ✓✓✓      ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
SUCCESS
echo -e "${NC}"

SERVER_IP=$(hostname -I | awk '{print $1}')

echo -e "${BLUE}${BOLD}Access Your NetBird MSP Appliance:${NC}\n"
if [ -n "$MSP_DOMAIN" ]; then
    echo -e "  Web Interface: ${GREEN}https://${MSP_DOMAIN}${NC}"
    echo -e "  Direct Access: ${CYAN}http://${SERVER_IP}:8000${NC}"
else
    echo -e "  Web Interface: ${GREEN}http://${SERVER_IP}:8000${NC}"
fi
echo -e "  Username:      ${GREEN}${ADMIN_USERNAME}${NC}"
echo -e "  Password:      ${CYAN}<the password you entered>${NC}\n"

echo -e "${BLUE}${BOLD}Configuration:${NC}\n"
echo -e "  ${YELLOW}All settings are stored in the database${NC}"
echo -e "  ${YELLOW}Edit them anytime via Web UI > Settings${NC}"
echo -e "  ${YELLOW}NO .env file editing needed!${NC}\n"

echo -e "${BLUE}${BOLD}Next Steps:${NC}\n"
echo -e "  1. ${CYAN}Access the web interface${NC}"
echo -e "  2. ${CYAN}Review system settings${NC} (all editable via Web UI)"
echo -e "  3. ${CYAN}Deploy your first customer${NC} (click 'New Customer')"
echo -e "  4. ${CYAN}Share setup URL${NC} with your customer\n"

echo -e "${BLUE}${BOLD}Useful Commands:${NC}\n"
echo -e "  View logs:    ${CYAN}docker logs -f $CONTAINER_NAME${NC}"
echo -e "  Stop:         ${CYAN}docker compose -f $INSTALL_DIR/docker-compose.yml stop${NC}"
echo -e "  Start:        ${CYAN}docker compose -f $INSTALL_DIR/docker-compose.yml start${NC}"
echo -e "  Restart:      ${CYAN}docker compose -f $INSTALL_DIR/docker-compose.yml restart${NC}\n"

echo -e "${BLUE}${BOLD}Important Notes:${NC}\n"
echo -e "  ${YELLOW}•${NC} All settings can be changed via the Web UI"
echo -e "  ${YELLOW}•${NC} Installation directory: ${INSTALL_DIR}"
echo -e "  ${YELLOW}•${NC} Customer data directory: ${DATA_DIR}"
echo -e "  ${YELLOW}•${NC} Database: ${INSTALL_DIR}/data/netbird_msp.db"
echo -e "  ${YELLOW}•${NC} Backup your database regularly\n"

# Save installation summary (no secrets!)
cat > "$INSTALL_DIR/INSTALLATION_SUMMARY.txt" << SUMMARY
NetBird MSP Appliance - Installation Summary
=============================================

Installation Date: $(date)

Configuration:
--------------
Admin Username:  $ADMIN_USERNAME
Admin Email:     $ADMIN_EMAIL
Base Domain:     $BASE_DOMAIN
NPM API URL:     $NPM_API_URL
NPM Login:       $NPM_EMAIL
Data Directory:  $DATA_DIR

NOTE: All settings are stored in the database and editable via Web UI.
      No manual config file editing needed!

Access:
-------
Web UI: http://${SERVER_IP}:8000$(if [ -n "$MSP_DOMAIN" ]; then echo "
HTTPS:  https://${MSP_DOMAIN}"; fi)

Directories:
------------
Installation: $INSTALL_DIR
Data:         $DATA_DIR
Database:     $INSTALL_DIR/data/netbird_msp.db
Logs:         $INSTALL_DIR/logs
Backups:      $INSTALL_DIR/backups

Docker:
-------
Container Name: $CONTAINER_NAME
Network:        $DOCKER_NETWORK

Ports:
------
Web UI:      TCP 8000
Dashboard:   TCP 9001-9100 (base 9000 + customer ID, one per customer)
Relay:       UDP 3478-3577 (one per customer)

Images:
-------
Management: $NETBIRD_MANAGEMENT_IMAGE
Signal:     $NETBIRD_SIGNAL_IMAGE
Relay:      $NETBIRD_RELAY_IMAGE
Dashboard:  $NETBIRD_DASHBOARD_IMAGE
SUMMARY

echo -e "${CYAN}Installation summary saved to: ${INSTALL_DIR}/INSTALLATION_SUMMARY.txt${NC}\n"
