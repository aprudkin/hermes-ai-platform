# Minimal architecture

The installer has three boundaries: local validation, read-only planning, and
explicitly confirmed external deployment. Terraform owns only the optional new
Hetzner server and its cloud firewall. Ansible owns host security, Docker, the
Compose definition, Hermes state directories, and profile initialization.

One official Hermes image runs one container. The default gateway provides the
runtime and health endpoint. Manager, DevOps, Coding, and Research are upstream
Hermes profiles created with `hermes profile create --clone`; they share the
installed runtime but keep their own profile directories, SOUL, skills, memory,
sessions, and config. No second Hermes container or invented "Hermes Core" is
used.

The API server is enabled only on container/host loopback so its documented
health endpoint is probeable without publishing a public port. The host data
directory is the sole mutable state volume; the official image install tree is
immutable. Provider credentials live in that data directory's mode-0600 `.env`
and never in Compose, Terraform state, inventory, or Git. Ansible configures an
explicit provider/model through the supported Hermes CLI before profiles are
used.

Minimal deliberately has no database or Redis: upstream Hermes persists its
own state under `/opt/data`. It also has no private Hetzner network because one
server has no east-west traffic. The cloud firewall and UFW provide separate
ingress controls; no Docker port is published.
