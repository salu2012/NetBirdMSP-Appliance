# NetBird MSP Appliance - Claude Code Specification

## Project Overview
Build a complete, production-ready multi-tenant NetBird management platform that runs entirely in Docker containers. This is an MSP (Managed Service Provider) tool to manage 100+ isolated NetBird instances from a single web interface.

## Technology Stack
- **Backend**: Python 3.11+ with FastAPI
- **Frontend**: HTML5 + Bootstrap 5 + Vanilla JavaScript (no frameworks)
- **Database**: SQLite
- **Containerization**: Docker + Docker Compose
- **Templating**: Jinja2 for Docker Compose generation
- **Integration**: Docker Python SDK, Nginx Proxy Manager API

## Project Structure

```
netbird-msp-appliance/
├── README.md                          # Main documentation
├── QUICKSTART.md                      # Quick start guide
├── ARCHITECTURE.md                    # Architecture documentation
├── LICENSE                            # MIT License
├── .gitignore                         # Git ignore file
├── .env.example                       # Environment variables template
├── install.sh                         # One-click installation script
├── docker-compose.yml                 # Main application container
├── Dockerfile                         # Application container definition
├── requirements.txt                   # Python dependencies
│
├── app/                               # Python application
│   ├── __init__.py
│   ├── main.py                        # FastAPI entry point
│   ├── models.py                      # SQLAlchemy models
│   ├── database.py                    # Database setup
│   ├── dependencies.py                # FastAPI dependencies
│   │
│   ├── routers/                       # API endpoints
│   │   ├── __init__.py
│   │   ├── auth.py                    # Authentication endpoints
│   │   ├── customers.py               # Customer CRUD
│   │   ├── deployments.py             # Deployment management
│   │   ├── monitoring.py              # Status & health checks
│   │   └── settings.py                # System configuration
│   │
│   ├── services/                      # Business logic
│   │   ├── __init__.py
│   │   ├── docker_service.py          # Docker container management
│   │   ├── npm_service.py             # NPM API integration
│   │   ├── netbird_service.py         # NetBird deployment orchestration
│   │   └── port_manager.py            # UDP port allocation
│   │
│   └── utils/                         # Utilities
│       ├── __init__.py
│       ├── config.py                  # Configuration management
│       ├── security.py                # Encryption, hashing
│       └── validators.py              # Input validation
│
├── templates/                         # Jinja2 templates
│   ├── docker-compose.yml.j2          # Per-customer Docker Compose
│   ├── management.json.j2             # NetBird management config
│   └── relay.env.j2                   # Relay environment variables
│
├── static/                            # Frontend files
│   ├── index.html                     # Main dashboard
│   ├── css/
│   │   └── styles.css                 # Custom styles
│   └── js/
│       └── app.js                     # Frontend JavaScript
│
├── tests/                             # Unit & integration tests
│   ├── __init__.py
│   ├── test_customer_api.py
│   ├── test_deployment.py
│   └── test_docker_service.py
│
└── docs/                              # Additional documentation
    ├── API.md                         # API documentation
    ├── DEPLOYMENT.md                  # Deployment guide
    └── TROUBLESHOOTING.md             # Common issues
```

## Key Features to Implement

### 1. Customer Management
- **Create Customer**: Web form → API → Deploy NetBird instance
- **List Customers**: Paginated table with search/filter
- **Customer Details**: Status, logs, setup URL, actions
- **Delete Customer**: Remove all containers, NPM entries, data

### 2. Automated Deployment
**Workflow when creating customer:**
1. Validate inputs (subdomain unique, email valid)
2. Allocate ports (Management internal, Relay UDP public)
3. Generate configs from Jinja2 templates
4. Create instance directory: `/opt/netbird-instances/kunde{id}/`
5. Write `docker-compose.yml`, `management.json`, `relay.env`
6. Start Docker containers via Docker SDK
7. Wait for health checks (max 60s)
8. Create NPM proxy hosts via API (with SSL)
9. Update database with deployment info
10. Return setup URL to user

### 3. Web-Based Configuration
**All settings in database, editable via UI:**
- Base Domain
- Admin Email  
- NPM API URL & Token
- NetBird Docker Images
- Port Ranges
- Data Directories

No manual config file editing required!

### 4. Nginx Proxy Manager Integration
**Per customer, create proxy host:**
- Domain: `{subdomain}.{base_domain}`
- Forward to: `netbird-kunde{id}-dashboard:80`
- SSL: Automatic Let's Encrypt
- Advanced config: Route `/api/*` to management, `/signalexchange.*` to signal, `/relay` to relay

### 5. Port Management
**UDP Ports for STUN/Relay (publicly accessible):**
- Customer 1: 3478
- Customer 2: 3479
- ...
- Customer 100: 3577

**Algorithm:**
- Find next available port starting from 3478
- Check if port not in use (via `netstat` or database)
- Assign to customer
- Store in database

### 6. Monitoring & Health Checks
- Container status (running/stopped/failed)
- Health check endpoints (HTTP checks to management service)
- Resource usage (via Docker stats API)
- Relay connectivity test

## Database Schema

### Table: customers
```sql
CREATE TABLE customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    company TEXT,
    subdomain TEXT UNIQUE NOT NULL,
    email TEXT NOT NULL,
    max_devices INTEGER DEFAULT 20,
    notes TEXT,
    status TEXT DEFAULT 'active' CHECK(status IN ('active', 'inactive', 'deploying', 'error')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Table: deployments
```sql
CREATE TABLE deployments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL UNIQUE,
    container_prefix TEXT NOT NULL,
    relay_udp_port INTEGER UNIQUE NOT NULL,
    npm_proxy_id INTEGER,
    relay_secret TEXT NOT NULL,
    setup_url TEXT,
    deployment_status TEXT DEFAULT 'pending' CHECK(deployment_status IN ('pending', 'running', 'stopped', 'failed')),
    deployed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_health_check TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
);
```

### Table: system_config
```sql
CREATE TABLE system_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    base_domain TEXT NOT NULL,
    admin_email TEXT NOT NULL,
    npm_api_url TEXT NOT NULL,
    npm_api_token_encrypted TEXT NOT NULL,
    netbird_management_image TEXT DEFAULT 'netbirdio/management:latest',
    netbird_signal_image TEXT DEFAULT 'netbirdio/signal:latest',
    netbird_relay_image TEXT DEFAULT 'netbirdio/relay:latest',
    netbird_dashboard_image TEXT DEFAULT 'netbirdio/dashboard:latest',
    data_dir TEXT DEFAULT '/opt/netbird-instances',
    docker_network TEXT DEFAULT 'npm-network',
    relay_base_port INTEGER DEFAULT 3478,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Table: deployment_logs
```sql
CREATE TABLE deployment_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('success', 'error', 'info')),
    message TEXT,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
);
```

### Table: users (simple auth)
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## API Endpoints to Implement

### Authentication
```
POST   /api/auth/login          # Login and get token
POST   /api/auth/logout         # Logout
GET    /api/auth/me             # Get current user
POST   /api/auth/change-password
```

### Customers
```
POST   /api/customers           # Create + auto-deploy
GET    /api/customers           # List all (pagination, search, filter)
GET    /api/customers/{id}      # Get details
PUT    /api/customers/{id}      # Update
DELETE /api/customers/{id}      # Delete + cleanup
```

### Deployments
```
POST   /api/customers/{id}/deploy     # Manual deploy
POST   /api/customers/{id}/start      # Start containers
POST   /api/customers/{id}/stop       # Stop containers
POST   /api/customers/{id}/restart    # Restart containers
GET    /api/customers/{id}/logs       # Get container logs
GET    /api/customers/{id}/health     # Health check
```

### Monitoring
```
GET    /api/monitoring/status          # System overview
GET    /api/monitoring/customers       # All customers status
GET    /api/monitoring/resources       # Host resource usage
```

### Settings
```
GET    /api/settings/system            # Get system config
PUT    /api/settings/system            # Update system config
GET    /api/settings/test-npm          # Test NPM connectivity
```

## Docker Compose Template (Per Customer)

```yaml
version: '3.8'

networks:
  npm-network:
    external: true

services:
  netbird-management:
    image: {{ netbird_management_image }}
    container_name: netbird-kunde{{ customer_id }}-management
    restart: unless-stopped
    networks:
      - npm-network
    volumes:
      - {{ instance_dir }}/data/management:/var/lib/netbird
      - {{ instance_dir }}/management.json:/etc/netbird/management.json
    command: ["--port", "80", "--log-file", "console", "--log-level", "info",
              "--single-account-mode-domain={{ subdomain }}.{{ base_domain }}",
              "--dns-domain={{ subdomain }}.{{ base_domain }}"]

  netbird-signal:
    image: {{ netbird_signal_image }}
    container_name: netbird-kunde{{ customer_id }}-signal
    restart: unless-stopped
    networks:
      - npm-network
    volumes:
      - {{ instance_dir }}/data/signal:/var/lib/netbird

  netbird-relay:
    image: {{ netbird_relay_image }}
    container_name: netbird-kunde{{ customer_id }}-relay
    restart: unless-stopped
    networks:
      - npm-network
    ports:
      - "{{ relay_udp_port }}:3478/udp"
    env_file:
      - {{ instance_dir }}/relay.env
    environment:
      - NB_ENABLE_STUN=true
      - NB_STUN_PORTS=3478
      - NB_LISTEN_ADDRESS=:80
      - NB_EXPOSED_ADDRESS=rels://{{ subdomain }}.{{ base_domain }}:443
      - NB_AUTH_SECRET={{ relay_secret }}

  netbird-dashboard:
    image: {{ netbird_dashboard_image }}
    container_name: netbird-kunde{{ customer_id }}-dashboard
    restart: unless-stopped
    networks:
      - npm-network
    environment:
      - NETBIRD_MGMT_API_ENDPOINT=https://{{ subdomain }}.{{ base_domain }}
      - NETBIRD_MGMT_GRPC_API_ENDPOINT=https://{{ subdomain }}.{{ base_domain }}
```

## Frontend Requirements

### Main Dashboard (index.html)
**Layout:**
- Navbar: Logo, "New Customer" button, User menu (settings, logout)
- Stats Cards: Total customers, Active, Inactive, Errors
- Customer Table: Name, Subdomain, Status, Devices, Actions
- Pagination: 25 customers per page
- Search bar: Filter by name, subdomain, email
- Status filter dropdown: All, Active, Inactive, Error

**Customer Table Actions:**
- View Details (→ customer detail page)
- Start/Stop/Restart (inline buttons)
- Delete (with confirmation modal)

### Customer Detail Page
**Tabs:**
1. **Info**: All customer details, edit button
2. **Deployment**: Status, Setup URL (copy button), Container status
3. **Logs**: Real-time logs from all containers (auto-refresh)
4. **Health**: Health check results, relay connectivity test

### Settings Page
**Tabs:**
1. **System Configuration**: All system settings, save button
2. **NPM Integration**: API URL, Token, Test button
3. **Images**: NetBird Docker image tags
4. **Security**: Change admin password

### Modal Dialogs
- New/Edit Customer Form
- Delete Confirmation
- Deployment Progress (with spinner)
- Error Display

## Security Requirements

1. **Password Hashing**: Use bcrypt for admin password
2. **Secret Encryption**: Encrypt NPM token and relay secrets with Fernet
3. **Input Validation**: Pydantic models for all API inputs
4. **SQL Injection Prevention**: Use SQLAlchemy ORM (no raw queries)
5. **CSRF Protection**: Token-based authentication
6. **Rate Limiting**: Prevent brute force on login endpoint

## Error Handling

All operations should have comprehensive error handling:

```python
try:
    # Deploy customer
    result = deploy_customer(customer_id)
except DockerException as e:
    # Rollback: Stop containers
    # Log error
    # Update status to 'failed'
    # Return error to user
except NPMException as e:
    # Rollback: Remove containers
    # Log error
    # Update status to 'failed'
except Exception as e:
    # Generic rollback
    # Log error
    # Alert admin
```

## Testing Requirements

1. **Unit Tests**: All services (docker_service, npm_service, etc.)
2. **Integration Tests**: Full deployment workflow
3. **API Tests**: All endpoints with different scenarios
4. **Mock External Dependencies**: Docker API, NPM API

## Deployment Process

1. Clone repository
2. Run `./install.sh`
3. Access `http://server-ip:8000`
4. Complete setup wizard
5. Deploy first customer

## System Requirements Documentation

**Include in README.md:**

### For 100 Customers:
- **CPU**: 16 cores (minimum 8)
- **RAM**: 64 GB (minimum) - 128 GB (recommended)
  - Formula: `(100 customers × 600 MB) + 8 GB overhead = 68 GB`
- **Disk**: 500 GB SSD (minimum) - 1 TB recommended
- **Network**: 1 Gbps dedicated connection
- **OS**: Ubuntu 22.04 LTS or 24.04 LTS

### Port Requirements:
- **TCP 8000**: Web UI
- **UDP 3478-3577**: Relay/STUN (100 ports for 100 customers)

## Success Criteria

✅ One-command installation via `install.sh`
✅ Web-based configuration (no manual file editing)
✅ Customer deployment < 2 minutes
✅ All settings in database
✅ Automatic NPM integration
✅ Comprehensive error handling
✅ Clean, professional UI
✅ Full API documentation (auto-generated)
✅ Health monitoring
✅ Easy to deploy on fresh Ubuntu VM

## Special Notes for Claude Code

- **Use type hints** throughout Python code
- **Document all functions** with docstrings
- **Follow PEP 8** style guidelines
- **Create modular code**: Each service should be independently testable
- **Use async/await** where appropriate (FastAPI endpoints)
- **Provide comprehensive comments** for complex logic
- **Include error messages** that help users troubleshoot

## File Priorities

Create in this order:
1. Basic structure (directories, requirements.txt, Dockerfile, docker-compose.yml)
2. Database models and setup (models.py, database.py)
3. Core services (docker_service.py, port_manager.py)
4. API routers (start with customers.py)
5. NPM integration (npm_service.py)
6. Templates (Jinja2 files)
7. Frontend (HTML, CSS, JS)
8. Installation script
9. Documentation
10. Tests

This specification provides everything needed to build a production-ready NetBird MSP Appliance!
