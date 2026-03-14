#!/bin/sh
set -eu

DB_NAME="${ODOO_DB_NAME:-odoo_prod}"
ADMIN_PASSWORD="${ODOO_ADMIN_PASSWORD:-change-me-admin}"
DB_HOST="${HOST:-${ODOO_DB_HOST:-db}}"
DB_PORT="${PORT:-${ODOO_DB_PORT:-5432}}"
DB_USER="${USER:-${ODOO_DB_USER:-odoo}}"
DB_PASSWORD="${PASSWORD:-${ODOO_DB_PASSWORD:-odoo}}"

exec odoo \
  -d "$DB_NAME" \
  -i base \
  --without-demo=all \
  --stop-after-init \
  --proxy-mode \
  --admin-passwd "$ADMIN_PASSWORD" \
  --db_host "$DB_HOST" \
  --db_port "$DB_PORT" \
  --db_user "$DB_USER" \
  --db_password "$DB_PASSWORD" \
  --addons-path /mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons,/var/lib/odoo/addons/19.0
