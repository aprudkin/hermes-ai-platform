locals {
  ssh_public_key_fields   = regexall("[^[:space:]]+", trimspace(file(pathexpand(var.ssh_public_key_path))))
  ssh_public_key_identity = join(" ", slice(local.ssh_public_key_fields, 0, 2))

  registered_ssh_public_key_fields = regexall("[^[:space:]]+", trimspace(data.hcloud_ssh_key.hermes.public_key))
  registered_ssh_public_key_identity = join(
    " ",
    slice(local.registered_ssh_public_key_fields, 0, 2)
  )
}

data "hcloud_ssh_key" "hermes" {
  name = var.hcloud_ssh_key_name
}

data "hcloud_server_type" "selected" {
  name = var.server_type
}

resource "hcloud_firewall" "hermes" {
  name = "${var.server_name}-ingress"

  rule {
    direction   = "in"
    protocol    = "tcp"
    port        = "22"
    source_ips  = var.ssh_source_cidrs
    description = "SSH provisioning and administration"
  }

  rule {
    direction   = "in"
    protocol    = "icmp"
    source_ips  = var.ssh_source_cidrs
    description = "Operational ICMP from administrative networks"
  }
}

resource "hcloud_server" "hermes" {
  name         = var.server_name
  image        = var.image
  server_type  = data.hcloud_server_type.selected.name
  location     = var.location
  ssh_keys     = [data.hcloud_ssh_key.hermes.id]
  firewall_ids = [hcloud_firewall.hermes.id]

  public_net {
    ipv4_enabled = true
    ipv6_enabled = true
  }

  labels = {
    project          = "hermes"
    deployment_level = "minimal"
    managed_by       = "terraform"
  }

  lifecycle {
    precondition {
      condition     = local.registered_ssh_public_key_identity == local.ssh_public_key_identity
      error_message = "The registered Hetzner SSH key does not match ssh_public_key_path."
    }

    precondition {
      condition     = data.hcloud_server_type.selected.category == "cost_optimized"
      error_message = "The selected server_type must be in Hetzner's cost_optimized category."
    }

    precondition {
      condition = anytrue([
        for candidate in data.hcloud_server_type.selected.locations :
        candidate.name == var.location && candidate.available && candidate.recommended && !candidate.is_deprecated
      ])
      error_message = "The selected server_type must be available, recommended, and not deprecated in the selected location at plan time."
    }
  }
}
