locals {
  ssh_public_key = trimspace(file(pathexpand(var.ssh_public_key_path)))
}

data "hcloud_ssh_key" "hermes" {
  name = var.hcloud_ssh_key_name
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
  server_type  = var.server_type
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
      condition     = trimspace(data.hcloud_ssh_key.hermes.public_key) == local.ssh_public_key
      error_message = "The registered Hetzner SSH key does not match ssh_public_key_path."
    }
  }
}
