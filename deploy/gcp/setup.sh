#!/usr/bin/env bash
# Run this ON the GCP VM via SSH (not on your own machine) as a user
# with sudo access. Installs PulseQueue's worker and runs it as a
# systemd service pointed at your Supabase/Upstash URLs.
#
# See docs/deployment.md's "Worker on a free Google Cloud VM" section
# for the full walkthrough this script is one step of. Written and
# reviewed, not run against a real GCP VM from the session that wrote
# it (no access to create cloud accounts) - read it before running it,
# same as you would any setup script from the internet.
set -euo pipefail

REPO_URL="https://github.com/ayrus15/PulseQueue.git"
INSTALL_DIR="/opt/pulsequeue"

sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv git

sudo mkdir -p "$INSTALL_DIR"
sudo chown "$USER":"$USER" "$INSTALL_DIR"
if [ -d "$INSTALL_DIR/.git" ]; then
  git -C "$INSTALL_DIR" pull
else
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -e . -q

if [ ! -f .env ]; then
  cat > .env <<'EOF'
DATABASE_URL=postgresql+asyncpg://postgres:CHANGE_ME@db.CHANGE_ME.supabase.co:5432/postgres
REDIS_URL=rediss://default:CHANGE_ME@CHANGE_ME.upstash.io:6379
PULSEQUEUE_LOG_LEVEL=INFO
EOF
  echo
  echo "Created $INSTALL_DIR/.env with placeholder values."
  echo "Edit it now with your real Supabase/Upstash connection strings"
  echo "(nano $INSTALL_DIR/.env), then run this script again."
  exit 0
fi

if ! id pulsequeue &>/dev/null; then
  sudo useradd --system --no-create-home --shell /usr/sbin/nologin pulsequeue
fi
sudo chown -R pulsequeue:pulsequeue "$INSTALL_DIR"

sudo cp "$INSTALL_DIR/deploy/gcp/pulsequeue-worker.service" /etc/systemd/system/pulsequeue-worker.service
sudo systemctl daemon-reload
sudo systemctl enable --now pulsequeue-worker

echo
echo "Done. Useful commands:"
echo "  sudo systemctl status pulsequeue-worker    # is it running?"
echo "  sudo journalctl -u pulsequeue-worker -f    # live logs"
echo "  sudo systemctl restart pulsequeue-worker   # after editing .env or pulling new code"
