FROM odoo:19

USER root
COPY addons/cb_redis/requirements.txt /tmp/cb_redis-requirements.txt
RUN python3 -m pip install --no-cache-dir -r /tmp/cb_redis-requirements.txt --break-system-packages \
    && mkdir -p /mnt/addons/custom /var/log/odoo /mnt/extra-addons /etc/odoo /var/lib/odoo \
    && chown -R odoo:odoo /mnt/addons/custom /var/log/odoo /mnt/extra-addons /etc/odoo /var/lib/odoo

COPY docker-entrypoint-dokploy.sh /usr/local/bin/cb-redis-dokploy-entrypoint
COPY docker-init-odoo-db.sh /usr/local/bin/cb-redis-init-db
RUN chmod +x /usr/local/bin/cb-redis-dokploy-entrypoint /usr/local/bin/cb-redis-init-db

USER odoo
COPY --chown=odoo:odoo addons/cb_redis /mnt/addons/custom/cb_redis
COPY --chown=odoo:odoo addons/cb_redis /mnt/extra-addons/cb_redis
