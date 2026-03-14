#!/bin/sh
set -eu

CONFIG_PATH="${ODOO_CONFIG_PATH:-/tmp/odoo-dokploy.conf}"

cat >"$CONFIG_PATH" <<EOF
[options]
admin_passwd = ${ODOO_ADMIN_PASSWORD:-change-me-admin}
db_host = ${ODOO_DB_HOST:-your-postgres-host}
db_port = ${ODOO_DB_PORT:-5432}
db_user = ${ODOO_DB_USER:-odoo}
db_password = ${ODOO_DB_PASSWORD:-change-me-db-password}
addons_path = /mnt/extra-addons,/mnt/addons/custom,/mnt/extra-addons/enterprise,/mnt/extra-addons/custom,/mnt/extra-addons/3rd-parties,/mnt/extra-addons/3rd-parties/base,/mnt/extra-addons/3rd-parties/OCA,/usr/lib/python3/dist-packages/odoo/addons,/var/lib/odoo/addons/19.0
data_dir = /var/lib/odoo
proxy_mode = ${ODOO_PROXY_MODE:-True}
list_db = ${ODOO_LIST_DB:-False}
EOF

if [ -f "/var/lib/odoo/requirements.txt" ]; then
    echo "Installing requirements from /var/lib/odoo/requirements.txt..."
    python3 -m pip install --user --break-system-packages --no-cache-dir -r /var/lib/odoo/requirements.txt
fi

exec "$@"
