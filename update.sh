#!/bin/bash
# update.sh — SSH-based manual update for NetBird MSP Appliance
# Usage: bash update.sh [branch]
# Run from the host as root or the user that owns the install directory.
set -euo pipefail

INSTALL_DIR="/opt/netbird-msp"
BRANCH="${1:-main}"

cd "$INSTALL_DIR"

echo "=== NetBird MSP Appliance Update ==="
echo "Install dir : $INSTALL_DIR"
echo "Branch      : $BRANCH"
echo "Current     : $(git log --oneline -1 2>/dev/null || echo 'unknown')"
echo ""

# --- Backup database ---
BACKUP_DIR="$INSTALL_DIR/backups"
mkdir -p "$BACKUP_DIR"
DB_FILE="$INSTALL_DIR/data/netbird_msp.db"
if [ -f "$DB_FILE" ]; then
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="$BACKUP_DIR/netbird_msp_${TIMESTAMP}.db"
    cp "$DB_FILE" "$BACKUP_FILE"
    echo "✓ Database backed up to $BACKUP_FILE"
else
    echo "⚠ No database file found at $DB_FILE — skipping backup"
fi

# --- Pull latest code ---
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull origin "$BRANCH"
echo "✓ Code updated to: $(git log --oneline -1)"

# --- Export build args ---
export GIT_COMMIT=$(git rev-parse HEAD)
export GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
export GIT_COMMIT_DATE=$(git log -1 --format=%cI)

echo ""
echo "Building with:"
echo "  GIT_COMMIT      = $GIT_COMMIT"
echo "  GIT_BRANCH      = $GIT_BRANCH"
echo "  GIT_COMMIT_DATE = $GIT_COMMIT_DATE"
echo ""

# --- Rebuild and restart ---
docker compose up --build -d
echo "✓ Container rebuilt and restarted"

# --- Health check ---
echo "Waiting for app to start..."
for i in $(seq 1 12); do
    sleep 5
    if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
        echo ""
        echo "✓ App is healthy!"
        echo "=== Update complete ==="
        echo "New version: $(git log --oneline -1)"
        exit 0
    fi
    printf "  Waiting... (%ds)\n" "$((i * 5))"
done

echo ""
echo "⚠ Health check timed out after 60s."
echo "  Check logs with: docker logs netbird-msp-appliance"
exit 1
