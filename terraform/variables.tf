variable "location" {
  description = "Exact supported Hetzner Cloud location. Must be selected explicitly."
  type        = string

  validation {
    condition     = contains(["fsn1", "nbg1", "hel1"], var.location)
    error_message = "location must be exactly fsn1, nbg1, or hel1."
  }
}

variable "server_name" {
  description = "Hetzner server name."
  type        = string
  default     = "hermes-minimal"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$", var.server_name))
    error_message = "server_name must be a lowercase DNS label between 2 and 63 characters."
  }
}

variable "server_type" {
  description = "Explicit shared-resource Hetzner Cloud server type, checked for live availability and recommendation in the selected location during plan."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*$", var.server_type))
    error_message = "server_type must be a non-empty Hetzner Cloud server type name."
  }
}

variable "image" {
  description = "Supported Ubuntu image used by the Ansible playbook."
  type        = string
  default     = "ubuntu-24.04"

  validation {
    condition     = var.image == "ubuntu-24.04"
    error_message = "Minimal currently supports only ubuntu-24.04."
  }
}

variable "ssh_public_key_path" {
  description = "Controller-local path used to verify the selected registered public key. Private keys are never uploaded."
  type        = string
}

variable "hcloud_ssh_key_name" {
  description = "Exact name of an existing Hetzner Cloud SSH key."
  type        = string

  validation {
    condition     = length(trimspace(var.hcloud_ssh_key_name)) > 0
    error_message = "hcloud_ssh_key_name must not be empty."
  }
}

variable "ssh_source_cidrs" {
  description = "Explicit administrative CIDRs allowed to reach SSH."
  type        = list(string)

  validation {
    condition = length(var.ssh_source_cidrs) > 0 && alltrue([
      for cidr in var.ssh_source_cidrs : can(cidrhost(cidr, 0))
    ])
    error_message = "At least one valid administrative SSH source CIDR is required."
  }
}
