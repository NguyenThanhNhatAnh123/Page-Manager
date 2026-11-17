#!/usr/bin/env bash
# Official Docker Ubuntu repository; run explicitly inside the server VM.
set -euo pipefail
[[ "$EUID" -eq 0 ]] || { echo 'Run with sudo inside the Ubuntu VM.' >&2; exit 1; }
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]] || { echo 'This installer targets Ubuntu Server 24.04 LTS.' >&2; exit 1; }
for package in docker.io docker-compose docker-compose-v2 podman-docker containerd runc; do
    if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -qx 'install ok installed'; then
        echo "Conflicting package present: $package. Review Docker's official migration instructions first." >&2
        exit 1
    fi
done
apt-get update
apt-get install -y ca-certificates curl git python3
install -d -m 0755 /etc/apt/keyrings
curl --fail --show-error --silent --location https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod 0644 /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker info --format '{{.OSType}}'
docker compose version
echo 'Docker Engine and Compose are ready. Continue with manager.py init/install.'
