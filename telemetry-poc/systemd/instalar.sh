#!/bin/sh
# Instala el servicio telemetria en la Pi, SIN activarlo al arrancar.
#   sudo sh systemd/instalar.sh                  # con /usr/bin/python3
#   sudo PYTHON=~/telemetria-venv/bin/python sh systemd/instalar.sh
set -e

DIR=$(cd "$(dirname "$0")/.." && pwd)
PYTHON=${PYTHON:-/usr/bin/python3}
DEST=/etc/systemd/system/telemetria.service

[ "$(id -u)" = 0 ] || { echo "ejecutalo con sudo"; exit 1; }
[ -x "$PYTHON" ] || { echo "no existe $PYTHON"; exit 1; }

sed -e "s|@DIR@|$DIR|g" -e "s|@PYTHON@|$PYTHON|g" \
    "$DIR/systemd/telemetria.service" > "$DEST"
systemctl daemon-reload
# por si estaba activado de antes: que no arranque solo con el sistema
systemctl disable telemetria 2>/dev/null || true

echo "Instalado $DEST ($PYTHON, $DIR)"
echo "  sudo systemctl start telemetria   |   journalctl -u telemetria -f"
