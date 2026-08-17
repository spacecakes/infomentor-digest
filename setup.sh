#!/bin/sh
# Set up the digest from the checkout as it stands, and restart it. Run it with
# sudo to also install the service that keeps it reporting.
set -eu

cd "$(dirname "$0")"
root=$([ "$(id -u)" = 0 ] && echo yes || echo no)
fresh=$([ -f .env ] && echo no || echo yes)

python="${PYTHON:-python3}"
"$python" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null || {
    echo "Need Python 3.12 or later. Install it, or set PYTHON to one." >&2
    exit 1
}

[ -d .venv ] || "$python" -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
# Editable, so a pull needs no reinstall.
.venv/bin/pip install --quiet --editable .

# --with-deps adds the system libraries Chromium needs, and wants root.
if [ "$(uname)" = Linux ] && [ "$root" = yes ]; then
    .venv/bin/python -m playwright install --with-deps chromium
else
    .venv/bin/python -m playwright install chromium
fi

.venv/bin/infomentor-digest setup
if [ "$fresh" = yes ]; then
    .venv/bin/infomentor-digest test-notify || true
fi

echo
if [ "$root" = yes ] && command -v systemctl >/dev/null; then
    # The digest reads .env and data/ beside itself, so the service needs the
    # checkout as its working directory.
    cat >/etc/systemd/system/infomentor-digest.service <<UNIT
[Unit]
Description=InfoMentor digest
After=network-online.target

[Service]
# The journal reads a pipe, which Python would buffer until the digest is done.
Environment=PYTHONUNBUFFERED=1
WorkingDirectory=$PWD
ExecStart=$PWD/.venv/bin/infomentor-digest schedule
Restart=always
RestartSec=60

[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload
    systemctl enable infomentor-digest
    systemctl restart infomentor-digest
    echo "Reporting as a service. Read the log with:"
    echo "  journalctl -u infomentor-digest -f"
else
    echo "Report once:     .venv/bin/infomentor-digest run"
    echo "Keep reporting:  .venv/bin/infomentor-digest schedule"
    echo "As a service:    sudo ./setup.sh"
fi
