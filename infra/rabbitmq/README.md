# RabbitMQ Service for Genji Parkour

This repository contains the custom RabbitMQ image and deployment configuration used across the Genji Parkour infrastructure. It includes predefined queues, an initialization script, and automated GitHub deployments for both development and production environments.

---
## Repository Structure
### `Dockerfile`
Builds a custom RabbitMQ image from `rabbitmq:4-management`.
Includes:
* Enables plugins:
  * `rabbitmq_shovel`
  * `rabbitmq_shovel_management`
* Copies:
  * `definitions.json` → `/etc/rabbitmq/definitions.json`
  * `rabbit-init.sh` → `/usr/local/bin/rabbit-init.sh`
* Makes `rabbit-init.sh` executable
### `definitions.json`
Contains all queues and DLQs used by the Genji Parkour ecosystem, loaded at startup.
Examples included:
* `api.completion.submission`
* `api.playtest.create`
* `api.xp.grant`
* Corresponding `.dlq` queues
### `rabbit-init.sh`
Initialization script run at container start.
It:
* Waits for RabbitMQ to fully start
* Creates/updates the admin user
* Assigns permissions to the configured vhost
* Uses:
  * `RABBITMQ_USER`
  * `RABBITMQ_PASS`
  * `RABBITMQ_VHOST` (default `/`)
### `docker-compose.dev.yml` / `docker-compose.prod.yml`
Located in this repo.
They define:
* How the RabbitMQ container is run in each environment
* Required environment variables
* The command that starts RabbitMQ alongside the init script
* Persistence volumes
* Network configuration
You don’t need to replicate these here — just know they exist and are used by the workflows.
---
## Environment Variables
| Variable                      | Purpose                                                 | Secret Location      |
| ----------------------------- | ------------------------------------------------------- | -------------------- |
| `SERVER_HOST_SSH_PRIVATE_KEY` | SSH key used by GitHub Actions to connect to the server | Repository           |
| `SERVER_HOST_IP`              | Server hostname/IP                                      | Repository           |
| `SERVER_HOST_USER`            | SSH username                                            | Repository           |
| `RABBITMQ_USER`       | RabbitMQ admin username                                 |production/development|
| `RABBITMQ_PASS`       | RabbitMQ admin password                                 |production/development|
| `RABBITMQ_ERLANG_COOKIE`      | Required identity token for RabbitMQ node               |production/development|
---
## Deployment Workflows
### Development Deployment
Development deployments can happen in two ways:
1. **Manually** using *Run Workflow* in GitHub — you can choose a branch, tag, or SHA.
2. **Inside a Pull Request** by commenting `.deploy`, which deploys that PR’s commit to the development server.
### Production Deployment
Production deployment occurs:
* Automatically on **pushes to the `main` branch**
* Or manually via workflow dispatch
Both workflows:
* SSH into the correct server
* Switch to a remote Docker context
* Run the appropriate compose file (`docker-compose.dev.yml` or `docker-compose.prod.yml`) to rebuild and restart the service
---
## Local Development Setup
### 1. Create a `.env` file
```env
RABBITMQ_USER=admin
RABBITMQ_PASS=admin
RABBITMQ_ERLANG_COOKIE=secret_cookie
RABBITMQ_VHOST=/
```
### 2. Start the RabbitMQ service
```sh
docker compose -f docker-compose.dev.yml up --build
```
### 3. Access the management dashboard
```
http://localhost:15672
```
Login using the credentials from your `.env` file.
