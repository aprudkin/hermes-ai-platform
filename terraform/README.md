# Hetzner Terraform

This root module creates one Ubuntu 24.04 server and one ingress firewall. It
looks up an existing Hetzner Cloud SSH key by exact name and refuses to plan if
its registered public key differs from the controller-local public key. It does
not create duplicate keys, a private network, volume, DNS, load balancer,
database, or cache because Minimal does not need them.

`location` has no default and accepts `fsn1`, `nbg1`, or `hel1`; the selected
Minimal target is `hel1`. `server_type` also has no default. Every plan looks up
that type through the provider and rejects it unless Hetzner currently reports
the type as cost-optimized, available, recommended, and not deprecated in the
selected location. `ssh_source_cidrs` has no default: every plan must name at
least one administrative network. The provider reads its token from
`HCLOUD_TOKEN`; no token belongs in a tfvars file. Use the root installer so
input checks, planning, inventory generation, and the external mutation gate
stay consistent.

Provider contract: [hcloud_server_type data source](https://registry.terraform.io/providers/hetznercloud/hcloud/latest/docs/data-sources/server_type).
