#!/bin/sh
# Prépare /data puis abandonne les privilèges root.
#
# Sans cela, un volume monté depuis l'hôte (« ./data:/data ») appartient à root
# et l'application, qui ne tourne pas en root, ne peut pas y écrire. PUID/PGID
# permettent d'aligner le propriétaire sur le compte utilisé par le NAS
# (typiquement 1000:1000, ou 1026:100 chez Synology).
set -e

PUID="${PUID:-10001}"
PGID="${PGID:-10001}"
DATA_DIR="${DATA_DIR:-/data}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    if ! chown -R "$PUID:$PGID" "$DATA_DIR" 2>/dev/null; then
        echo "Attention : impossible de changer le propriétaire de $DATA_DIR." >&2
        echo "Si l'application ne démarre pas, exécutez sur l'hôte :" >&2
        echo "  chown -R $PUID:$PGID ./data" >&2
    fi
    exec setpriv --reuid "$PUID" --regid "$PGID" --init-groups "$@"
fi

# Conteneur déjà lancé sous un utilisateur non privilégié (docker run --user …).
exec "$@"
