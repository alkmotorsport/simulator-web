#!/bin/sh
# Instala el servicio telemetria en la Pi y lo activa al arrancar.
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
# wifi propia con portal si no hay red conocida (solo con NetworkManager: Bookworm)
if command -v nmcli >/dev/null 2>&1; then
    sed -e "s|@DIR@|$DIR|g" -e "s|@PYTHON@|/usr/bin/python3|g" \
        "$DIR/systemd/telemetria-wifi.service" > /etc/systemd/system/telemetria-wifi.service
fi
systemctl daemon-reload
systemctl enable telemetria
command -v nmcli >/dev/null 2>&1 && systemctl enable telemetria-wifi

echo "Instalado $DEST ($PYTHON, $DIR)"
echo "Arranca solo al encender. Ahora:  sudo systemctl restart telemetria"
echo "Ver lo que hace:  journalctl -u telemetria -f"
