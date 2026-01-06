FROM rabbitmq:4-management
COPY definitions.json /etc/rabbitmq/definitions.json
COPY rabbit-init.sh /usr/local/bin/rabbit-init.sh
COPY 20-oauth2.conf /etc/rabbitmq/conf.d/20-oauth2.conf

RUN chmod +x /usr/local/bin/rabbit-init.sh

# Enable required plugins
RUN rabbitmq-plugins enable --offline \
    rabbitmq_shovel \
    rabbitmq_shovel_management \
    rabbitmq_auth_backend_oauth2 \
    rabbitmq_management

# Optional: Add ca-certificates if using self-signed certs
# RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*