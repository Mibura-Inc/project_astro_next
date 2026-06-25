# Astro Provisioning System

Astro is an automated, UEFI-compliant, dynamic bare-metal provisioning system for Ubuntu Server (for now). It orchestrates the entire deployment flow from initial machine booting to final OS installation by combining dynamic iPXE UEFI boot images with a 2-stage micro-initramfs environment and `kexec` handoffs.

---

## 1. Architecture & Lifecycle

Astro use a staged execution pattern to keep the initial boot media lightweight and ensure all configuration changes are dynamically computed at run-time:

For a comprehensive explanation of the architecture, sequence diagrams, and design details, please refer to the [docs](docs/) directory.

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

### Hosting Boot & Installation Assets Locally (Optional Self-Hosting)
By default, the system resolves and streams the official Ubuntu boot assets (kernel, initrd) and installation ISOs from Canonical's public servers (`releases.ubuntu.com`) or GitHub repositories.

If you prefer to host these assets locally within your own network (to speed up deployments or support offline installs):
1. Using Custom URLs: You can edit the `"kernel"`, `"initrd"`, and `"iso"` URL targets in [release-map.json](configServer/templates/ubuntu/release-map.json) to point directly to any internal fileserver or local repository IP of your choice (e.g., `http://10.10.0.10/assets/ubuntu/linux`, `http://10.10.0.10/assets/ubuntu/initrd`, and `http://10.10.0.10/assets/ubuntu/ubuntu-24.04.4-live-server-amd64.iso`).
2. Dynamic Overrides: You can also configure custom `base_url` or `generated_iso_url` parameters to point the playbooks and installer to your custom hosted URL targets.

---

## 3. How to Run the Project

The project includes all compilers, boot creation tools, and Ansible playbooks in a unified Docker environment.

### Step 1: Build the Docker Container
Run the following command in the project root to build the secure environment:
```bash
# Build the Docker images containing the necessary build tools and Nginx proxy
sudo docker compose build
```

### Step 2: Configure & Launch the Stack
To protect sensitive credentials (such as plain-text passwords and BMC credentials) sent over API calls, Astro includes a containerized Nginx sidecar proxy. It enforces HTTPS on port 443 for sensitive API calls, while allowing bare-metal node bootloader and check-in (phone-home) requests over HTTP on port 80.

#### 1. Configure the TLS Certificates & Server IP
By default, the containerized Nginx proxy will automatically generate a self-signed SSL certificate (`server.crt`) and private key (`server.key`) inside the `configServer/certs/` directory on the host if they do not exist. The certificate Common Name (CN) defaults to `localhost`. 

To configure the server's IP address or domain (e.g., `10.10.0.1`) across the Nginx proxy, Python API server, and Ansible playbooks, create a `.env` file in the root directory:
```env
SERVER_IP=10.10.0.1

This will automatically configure the SSL certificate's Common Name (CN) and populate configurations dynamically.

If you wish to provide your own custom TLS certificates instead:
1. Create the `configServer/certs/` folder:
   ```bash
   mkdir -p configServer/certs
   ```
2. Place your certificate and key files there:
   - `configServer/certs/server.crt`
   - `configServer/certs/server.key`

#### 2. Launch the Stack
To launch the entire secure stack (which starts both Nginx and the Python config server), run the following command in the project root:
```bash
# Clear host OS caches to maximize available memory (optional)
sudo sync; echo 3 | sudo tee /proc/sys/vm/drop_caches

# Start Nginx (ports 80/443) and the config server (port 8000)
sudo docker compose up
```

### Step 3: Interactive Shell & Rebuilding Custom OS
While the stack is running, you can run build/compilation tasks and compile the custom OS RAMDISK image.

#### 1. Shell into the Container
Open a new terminal window on your host machine and run:
```bash
sudo docker compose exec ipxe-builder /bin/bash
```

#### 2. Recompiling the Custom OS initramfs
This compilation step must be run the first time you set up the project (to generate the initial RAMDISK image) as well as any time you modify the stage 1 bootstrap scripts under `customOS/myInitRD/` (such as `init`).

Rebuild and compress the initramfs using the compiled toolchain inside the running Docker container (run these commands inside the container shell you opened in the previous step):
```bash
# Inside the Docker container (/work):
chmod -R 777 /work/customOS/myInitRD/
cd /work/customOS/myInitRD/
mkdir -p /work/configServer/http/customOS/
find . -print0 | cpio --null -ov --format=newc | gzip -9 > /work/configServer/http/customOS/initramfs.cpio.gz
cd /work
```

#### 3. Shutdown and Clean Up
* To stop the services, press `Ctrl + C` in the terminal where `sudo docker compose up` is running.
* To clean up all containers and networks completely, run:
  ```bash
  sudo docker compose down
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
      "dns_servers": "1.1.1.1,8.8.8.8", 
      "disable_updates": true, 
      "raid": false
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

### 2. Ansible Provision Staging (Dell iDRAC & Supermicro WTR)
Launches a background Ansible playbook to mount virtual media and boot the target bare-metal server.
* Dell iDRAC: Runs `playbookDell.yml` by default.
* Supermicro WTR: Automatically runs `playbookSupermicro.yml` when `"is_wtr": true` is specified in the request body.

* URL: `POST /api/v1/provision`
* Request Body:
  ```json
  {
      "bmc_address": "10.0.10.141",
      "bmc_username": "root",
      "bmc_password": "password",
      "os_type": "ubuntu",
      "os_version": "24.04.4",
      "arch": "amd64",
      "variant": "ipxe-uefi",
      "hostname": "test",
      "username": "default",
      "password": "default",
      "ipv4_address": "10.1.10.142",
      "ipv4_gateway": "10.1.10.1",
      "ipv4_netmask": "255.255.255.224",
      "ipv6_address": "1234:1234:1234:1234::1234",
      "ipv6_gateway": "fe80::1234:1234:1234:1234",
      "ipv6_cidr": "64",
      "dns_servers": "8.8.8.8,8.8.4.4,1.1.1.1,2001:4860:4860::8888",
      "raid": false,
      "is_wtr": true
  }
  ```
* Response:
  ```json
  {
      "success": true,
      "body": {
          "job_id": "test"
      }
  }
  ```
  *(Note: You can track the progress of the background Ansible provisioning staging using the **Check lifecycle status** job query)*

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
          {"dev": "sda", "id": "xyz_company_SSD_123", "size_mb": 512000},
          {"dev": "sdb", "id": "xyz_company_SSD_456", "size_mb": 512000}
      ]
  }
  ```

### 3. Server file automation & media retrieval
Serves the dynamic cloud-init templates, ISO images, and launcher scripts.
* URL: `GET /automation/<job_id>/<file>`
* Features: Supports HTTP 206 Range (Partial Content) headers. This is important for streaming chunks of larger installation files/ISOs without memory issues on target bare-metal environments.

### 4. Telemetry logging
Subiquity forwards installation stage logs back to the server.
* URL: `POST /api/v1/jobs/telemetry`
* Result: Appends reports to `/work/configServer/http/jobs/<job_id>/install.log`.

### 5. Check lifecycle status
Retrieve the exact step of the bare-metal node installation.
* URL: `GET /status?job_id=<job_id>` or `GET /api/v1/jobs/status?job_id=<job_id>`
* Response Stages: `BOOTING` $\rightarrow$ `STAGING` $\rightarrow$ `PHONED_HOME` $\rightarrow$ `INSTALLING` $\rightarrow$ `COMPLETED` / `INSTALL_FAILED`.
* Sample call:
  ```bash
  curl http://<server-ip>:8000/status?job_id=test-node-01
  ```
* Response example:
  ```json
  {
      "job_id": "test-node-01",
      "lifecycle_stage": "STAGING",
      "stage_description": "Ansible playbook running out-of-band initialization calls via BMC/iDRAC.",
      "ansible_staging": {
          "status": "running",
          "rc": null
      }
  }
  ```

---

## 6. Advanced Build Operations

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
