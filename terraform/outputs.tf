output "server_ipv4" {
  description = "Public IPv4 address for the generated Ansible inventory."
  value       = hcloud_server.hermes.ipv4_address
}

output "server_ipv6" {
  description = "Public IPv6 address assigned by Hetzner Cloud."
  value       = hcloud_server.hermes.ipv6_address
}

output "ansible_host" {
  description = "Structured, non-secret connection data for Ansible."
  value = {
    host = hcloud_server.hermes.ipv4_address
    user = "root"
  }
}
