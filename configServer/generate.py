import yaml
import crypt
import os

node = {
    "hostname": "...",
    "username": "...",
    "password": "...",
    "jobid": "12345",

    "ipv4": {
        "address": "10.1.10.142/24",
        "gateway": "10.1.10.1"
    },

    "ipv6": {
        "address": "",
        "gateway": ""
    },

    "dns": [
        "8.8.8.8",
        "1.1.1.1",
        "2001:4860:4860::8888"
    ],
    "BOOTIF": "01-A1-B2-C3-D4-E5-F6",
}

def mask_to_cidr(mask):
    return sum(bin(int(x)).count("1") for x in mask.split("."))

def hash_password(pw: str):
    return crypt.crypt(pw, crypt.mksalt(crypt.METHOD_SHA512))

def bootif_to_mac(bootif: str) -> str:
    if not bootif:
        return ""

    bootif = bootif.strip().lower()

    # remove PXE type prefix
    if bootif.startswith("01-"):
        bootif = bootif[3:]

    return bootif.replace("-", ":")

def build_cloud_init(node: dict):
    hostname = node.get("hostname", "node")
    username = node.get("username", "ubuntu")
    password_raw = node.get("password", "ubuntu")
    password = hash_password(password_raw)

    ipv4 = node.get("ipv4", {})
    ipv6 = node.get("ipv6", {})
    dns = node.get("dns", [])

    disks = node.get("disks", [])
    target_disk = disks[0]["dev"] if disks else "sda"

    # -------------------------
    # NETWORK (netplan format)
    # -------------------------
    mac = bootif_to_mac(node.get("BOOTIF", ""))

    ethernets = {
        "eth0": {}
    }

    if mac:
        ethernets["eth0"]["match"] = {"macaddress": mac}
        ethernets["eth0"]["set-name"] = "eth0"

    if ipv4.get("address") and ipv4.get("gateway", "").strip():
        ethernets["eth0"]["addresses"] = [ipv4["address"]]
        ethernets["eth0"]["gateway4"] = ipv4["gateway"]

    if ipv6.get("address") and ipv6["address"].strip():
        ethernets["eth0"].setdefault("addresses", []).append(ipv6["address"])
        ethernets["eth0"]["gateway6"] = ipv6.get("gateway")

    if dns:
        ethernets["eth0"]["nameservers"] = {
            "addresses": dns
        }

    network = {
        "version": 2,
        "renderer": "networkd",
        "ethernets": ethernets
    }

    safe_node = dict(node)
    safe_node["password"] = "***REDACTED***"

    # -------------------------
    # CLOUD INIT
    # -------------------------
    user_data = {
        "version": 2,
        "hostname": hostname,
        "users": [
            {
                "name": username,
                "hashed_passwd": password,
                "lock_passwd": False,
                "sudo": "ALL=(ALL) NOPASSWD:ALL",
                "shell": "/bin/bash"
            }
        ],

        "ssh_pwauth": True,

        "write_files": [
            {
                "path": "/etc/bootstrap-info.json",
                "content": yaml.safe_dump(safe_node),
                "permissions": "0644"
            },
            {
                "path": "/etc/netplan/99-custom.yaml",
                "content": yaml.safe_dump(network),
                "permissions": "0644"
            }
        ],

        "runcmd": [
            f"echo 'hostname={hostname}' > /etc/hostname-set",
            f"echo 'disk={target_disk}' > /etc/target-disk",
            "echo 'bootstrap complete'"
        ],

    }



    return "#cloud-config\n" + yaml.safe_dump(user_data, sort_keys=False)

def write_cloud_init(node: dict):
    jobid = node.get("jobid", "unknown")

    # build cloud-init config
    config = build_cloud_init(node)

    # output directory
    base_dir = os.path.join(".", "http", jobid)
    os.makedirs(base_dir, exist_ok=True)

    # file path (standard cloud-init naming)
    file_path = os.path.join(base_dir, "user-data")

    with open(file_path, "w") as f:
        f.write(config)

    print(f"[OK] Wrote cloud-init to {file_path}")


write_cloud_init(node)