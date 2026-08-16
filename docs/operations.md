# Operations status

Implemented local and deployment-time checks:

- Terraform format and schema validation without apply;
- Ansible syntax/lint and post-deployment runtime verification;
- Compose schema validation when Docker is available;
- container health through the loopback Hermes `/health` endpoint;
- profile existence through `hermes profile show`;
- bounded Docker log rotation and persistent `/opt/hermes/data` state.

Not implemented in Minimal: automated backup/restore, monitoring/alerting,
image upgrade automation, DNS, TLS, public dashboard/API access, or disaster
recovery. These remain later-level work and must not be inferred from this
repository.

For an authorized deployment, preserve the Terraform plan and validation
output under `.generated/` until review. After the first successful run, rerun
the same Ansible playbook and require zero semantic changes before calling the
host configuration idempotent. Back up `/opt/hermes/data` before any image pin
change; an upgrade procedure has not yet been implemented or tested.
