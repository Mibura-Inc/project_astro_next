# Astro Provisioning System

Astro is an automated, UEFI-compliant, dynamic bare-metal provisioning system for Ubuntu Server (for now). It orchestrates the entire deployment flow from initial machine booting to final OS installation by combining dynamic iPXE UEFI boot images with a 2-stage micro-initramfs environment and `kexec` handoffs.

---

## 1. Architecture & Lifecycle

Astro use a staged execution pattern to keep the initial boot media lightweight and ensure all configuration changes are dynamically computed at run-time:

WIP

### Component Breakdown
1. Config server & API (`configServer/server.py`): 
   A multi-threaded Python server that acts as the control plane. It tracks provisioning state machines, serves static files, maps Ubuntu versions to netboot resources, and dynamically generates `user-data` cloud-init autoinstall profiles (selecting RAID configs automatically if multiple disks are present) based on real-time hardware reports.
2. iPXE Builder (`ipxe-builder/`):
   Contains iPXE source code templates. Consolidates the boot media compilation process (`pipeline.sh`, `compose.py`) which builds hydrated UEFI-compliant ISO boot images.
3. Custom OS (`customOS/`):
   A micro-initramfs image loaded during Stage 1. It is designed to be minimal—it sets up target node networking, queries local disk inventory and machine serials, registers them with the control plane, downloads the Stage 2 launcher script (`installer-launch.sh`), and issues a `kexec` execution.

---

## 2. Dynamic IP & Hostname Resolution

A key design feature of Astro is complete IP and domain adaptability. 

The configuration server utilizes the HTTP `Host` header (via `get_server_host()`) from incoming client requests to build redirection, seed, and file URLs. 
* Zero hardcoding: You do not need to configure static API server IPs in configuration files. 
* Adaptable: You can run the server on `localhost` for testing, bind it to a local private subnet IP, or run it behind a public domain name. The API will dynamically adjust its response payloads.
* probed boot variables: During the ISO build step, `compose.py` extracts the server hostname from the request context and embeds it as `serverip` in the iPXE kernel command line. This allows the booting Node to know exactly where to phone home.

---

## 3. How to Run the Project

The project includes all compilers, boot creation tools, and Ansible playbooks in a unified Docker environment.

### Step 1: Build & Launch the Docker Container
Run the following commands in the project root to spin up the build environment:
```bash
# Build the Docker image containing necessary build tools and packages
sudo docker compose build

# Launch the container, exposing the API port (8000) and opening interactive terminal
sudo docker compose run --rm --service-ports ipxe-builder
```

### Step 2: Start the Config Server (Inside Docker Container)
Once inside the container shell, run the HTTP control plane server:
```bash
python3 configServer/server.py
```
*The server will start listening on port `8000`.*

### Step 3 (Optional): Configure Nginx on the Host
If you want to front the server on standard HTTP port `80`, configure Nginx on the host machine as a reverse proxy:
```nginx
# Nginx Configuration File (e.g. /etc/nginx/sites-enabled/ipxe-builder)
server {
    listen 80;
    server_name _;
    client_max_body_size 100M;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

---

## 4. API Endpoints

### 1. Provision Custom ISO
Initiates the compilation of a dynamic, UEFI-bootable ISO tailored to the target node's network parameters.
* URL: `POST /api/v1/servers/provision/custom-iso`
* Request Body:
  ```json
  {
      "os_type": "ubuntu",
      "os_version": "24.04.2",
      "arch": "amd64",
      "hostname": "node-db-01",
      "username": "admin",
      "password": "mySecurePassword",
      "ipv4_address": "10.1.10.143",
      "ipv4_gateway": "10.1.10.1",
      "ipv4_netmask": "255.255.255.0",
      "dns_servers": "1.1.1.1,8.8.8.8"
  }
  ```
* Response:
  ```json
  {
      "success": true,
      "body": {
          "custom_id": "custom-node-db-01",
          "iso_url": "http://<server-ip>:8000/automation/node-db-01/custom-node-db-01.iso",
          "user_data_url": "http://<server-ip>:8000/automation/node-db-01/user-data",
          "meta_data_url": "http://<server-ip>:8000/automation/node-db-01/meta-data",
          "seed_directory_url": "http://<server-ip>:8000/automation/node-db-01/"
      }
  }
  ```

### 2. Phone Home
Called by the micro-initramfs of the booted target node to report hardware attributes.
* URL: `POST /api/v1/servers/phone-home`
* Request Body:
  ```json
  {
      "job_id": "node-db-01",
      "machine_serial": "SM-ABCD12345",
      "bootif": "01-11-22-33-44-55-66",
      "uuids": [
          {"dev": "sda", "id": "SAMSUNG_SSD_123", "size_mb": 512000},
          {"dev": "sdb", "id": "SAMSUNG_SSD_456", "size_mb": 512000}
      ]
  }
  ```

### 3. Server file automation & media retrieval
Serves the dynamic cloud-init templates, ISO images, and launcher scripts.
* URL: `GET /automation/<job_id>/<file>`
* Features: Supports HTTP 206 Range (Partial Content) headers. This is critical for streaming chunks of larger installation files/ISOs without memory issues on target bare-metal environments.

### 4. Telemetry logging
Subiquity forwards installation stage logs back to the server.
* URL: `POST /api/v1/jobs/telemetry`
* Result: Appends reports to `/work/configServer/http/jobs/<job_id>/install.log`.

### 5. Check lifecycle status
Retrieve the exact step of the bare-metal node installation.
* URL: `GET /status?job_id=<job_id>` or `GET /api/v1/jobs/status?job_id=<job_id>`
* Response Stages: `BOOTING` $\rightarrow$ `STAGING` $\rightarrow$ `PHONED_HOME` $\rightarrow$ `INSTALLING` $\rightarrow$ `COMPLETED` / `INSTALL_FAILED`.

### 6. Ansible Provision Staging (iDRAC BMC)
Launches Ansible playbook `playbookDell.yml` in the background to configure BMC settings.
* URL: `POST /api/v1/provision`

---

## 5. Advanced Build Operations

### Recompiling the Custom OS initramfs
This compilation step must be run the first time you set up the project (to generate the initial RAMDISK image) as well as any time you modify the stage 1 bootstrap scripts under `customOS/myInitRD/` (such as `init`). 

Rebuild and compress the initramfs using the compiled toolchain inside the Docker container:
```bash
# Inside the Docker container (/work):
chmod -R 777 /work/customOS/myInitRD/
cd /work/customOS/myInitRD/
mkdir -p /work/configServer/http/customOS/
find . -print0 | cpio --null -ov --format=newc | gzip -9 > /work/configServer/http/customOS/initramfs.cpio.gz
```

### Compiling static `kexec-tools`
To compile a static, dependency-free `kexec` binary capable of running on target machines:

```bash
cd /work
# Download and extract kexec-tools source
wget https://kernel.org/pub/linux/utils/kernel/kexec/kexec-tools-2.0.28.tar.xz
tar -xf kexec-tools-2.0.28.tar.xz
cd kexec-tools-2.0.28

# Clean workspace
make clean

# Build static version for x86_64
LDFLAGS=-static ./configure \
  --prefix=$(pwd)/dist-x64 \
  --host=x86_64-linux-gnu

# Clear purgatory files that break static linking
echo "" > purgatory/arch/i386/entry32-16.S
echo "" > purgatory/arch/i386/entry32-16-debug.S
make ARCH=x86_64 -j$(nproc)
make install

# Build static version for ARM64 (cross-compiler)
make clean
gcc -O2 -Wall -o bin/bin-to-hex util/bin-to-hex.c
LDFLAGS="-static" ./configure \
  --host=aarch64-linux-gnu \
  --without-zlib

make ARCH=arm64 \
     CC=aarch64-linux-gnu-gcc \
     LD=aarch64-linux-gnu-ld \
     AR=aarch64-linux-gnu-ar \
     AS=aarch64-linux-gnu-as \
     BUILD_CC=gcc \
     -j$(nproc)
make install
```

---

## 6. Troubleshooting & Remote Debugging

When deploying onto physical bare-metal hardware, use these tricks to diagnose failures:

* Target Shell Access: 
  The Custom OS image runs a listener wrapper. If the bootstrap network succeeds but the installation errors out, open a remote console on the node using:
  ```bash
  nc <node-ip-address> 2222
  ```
* Review Subiquity Installer Logs:
  While logged into the node via Netcat or local TTY, inspect Subiquity's live staging state:
  ```bash
  cat /var/log/installer/subiquity-server-debug.log
  tail -n 100 /var/log/syslog
  ```
