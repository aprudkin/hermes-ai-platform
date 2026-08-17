mock_provider "hcloud" {
  override_during = plan
}

override_data {
  target = data.hcloud_ssh_key.hermes
  values = {
    id         = 123
    public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestFixtureOnly"
  }
}

override_data {
  target = data.hcloud_server_type.selected
  values = {
    name         = "cpx22"
    category     = "regular_purpose"
    architecture = "x86"
    locations = {
      id                    = 3
      name                  = "hel1"
      available             = true
      recommended           = true
      is_deprecated         = false
      deprecation_announced = ""
      unavailable_after     = ""
    }
  }
}

run "recommended_regular_performance_is_planable" {
  command = plan

  variables {
    location            = "hel1"
    server_type         = "cpx22"
    hcloud_ssh_key_name = "Luk"
    ssh_public_key_path = "tests/luk.pub"
    ssh_source_cidrs    = ["192.0.2.10/32"]
  }

}
