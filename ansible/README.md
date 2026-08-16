# Ansible deployment

`site.yml` supports Ubuntu 24.04 or newer. It installs baseline SSH/UFW/fail2ban
hardening, Docker Engine from Docker's official apt repository, one Hermes
container, and four Hermes profiles inside that container. The profiles clone
the default profile's supported config and skills, then receive synchronized
mode-0600 credentials, distinct `SOUL.md` identities, and independent
memory/session stores.

The play requires `hermes_env_source`, a controller-local mode-0600 file based
on `configs/hermes.env.example`, plus explicit `hermes_model_provider` and
`hermes_model` values. The private SSH key remains on the controller.
Use the root installer to generate a local ignored inventory and enforce the
external-mutation confirmation gate.
