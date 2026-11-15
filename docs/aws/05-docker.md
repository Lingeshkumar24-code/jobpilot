# Docker — Local Development and EC2 Learning Path

**Status: local images and Docker Compose are defined; EC2 deployment is not.** Compose runs PostgreSQL/pgvector, API, frontend, browser worker, and n8n. Images are built from pinned Python/npm dependencies. The browser worker is isolated and exposes no browser debugging port.

Local commands: `docker compose config`, `docker compose up --build`, then `docker compose ps` and `docker compose logs <service>`. Keep `.env` untracked and use placeholder-only `.env.example`. On any future EC2 host, install Docker from the supported distribution repository, enable encrypted storage, restrict inbound access to HTTPS, use SSM instead of public SSH, and do not expose the Docker socket.

Container disk, host compute, network transfer, and log storage may incur AWS charges. Monitor disk usage with `docker system df`; remove only known-unused images/containers. Before stopping or deleting a host, identify named volumes and back up the database and resume files. Compose volume deletion is destructive.
