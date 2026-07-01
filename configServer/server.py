import http.server
import json
import os
import sys
import uuid
import subprocess
import ipaddress
import re
import yaml
import ansible_runner
from pathlib import Path
from pydantic import BaseModel, Field, field_validator, ValidationInfo, ValidationError
from typing import Optional, List

def validate_ipv4(v: str) -> str:
    try:
        ipaddress.IPv4Address(v)
    except ValueError:
        raise ValueError(f"Invalid IPv4 address format: {v}")
    return v

def validate_ipv6(v: str) -> str:
    try:
        ipaddress.IPv6Address(v)
    except ValueError:
        raise ValueError(f"Invalid IPv6 address format: {v}")
    return v

class ProvisionCustomISORequest(BaseModel):
    hostname: str = Field(..., min_length=1)
    ipv4_address: str
    ipv4_gateway: str
    ipv4_netmask: str
    os_version: str = "24.04.4"
    username: str = "ubuntu"
    password: str = "ubuntu"
    dns_servers: str = "8.8.8.8"
    raid: bool = False
    disable_updates: bool = True
    ipv6_address: Optional[str] = None
    ipv6_gateway: Optional[str] = None
    ipv6_cidr: str = "64"

    @field_validator("ipv4_address", "ipv4_gateway", "ipv4_netmask")
    @classmethod
    def validate_ipv4_fields(cls, v: str) -> str:
        return validate_ipv4(v)

    @field_validator("ipv6_address")
    @classmethod
    def validate_ipv6_addr(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return validate_ipv6(v)
        return v

    @field_validator("ipv6_gateway")
    @classmethod
    def validate_ipv6_gw(cls, v: Optional[str], info: ValidationInfo) -> Optional[str]:
        ipv6_addr = info.data.get("ipv6_address")
        if ipv6_addr:
            if not v:
                raise ValueError("IPv6 address provided but 'ipv6_gateway' is missing")
            return validate_ipv6(v)
        return v

class AnsibleProvisionRequest(BaseModel):
    bmc_address: str = Field(..., min_length=1)
    bmc_username: str = Field(..., min_length=1)
    bmc_password: str = Field(..., min_length=1)
    os_type: str = Field(..., min_length=1)
    os_version: str = Field(..., min_length=1)
    arch: str = Field(..., min_length=1)
    variant: str = Field(..., min_length=1)
    hostname: str = Field(..., min_length=1)
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    ipv4_address: str
    ipv4_gateway: str
    ipv4_netmask: str
    ipv6_address: Optional[str] = None
    ipv6_gateway: Optional[str] = None
    ipv6_cidr: Optional[str] = "64"
    dns_servers: str = "8.8.8.8"
    raid: bool = False
    disable_updates: bool = True
    is_wtr: bool = False

    @field_validator("ipv4_address", "ipv4_gateway", "ipv4_netmask")
    @classmethod
    def validate_ipv4_fields(cls, v: str) -> str:
        return validate_ipv4(v)

    @field_validator("ipv6_address")
    @classmethod
    def validate_ipv6_addr(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return validate_ipv6(v)
        return v

    @field_validator("ipv6_gateway")
    @classmethod
    def validate_ipv6_gw(cls, v: Optional[str], info: ValidationInfo) -> Optional[str]:
        ipv6_addr = info.data.get("ipv6_address")
        if ipv6_addr:
            if not v:
                raise ValueError("IPv6 address provided but 'ipv6_gateway' is missing")
            return validate_ipv6(v)
        return v

class DiskInfo(BaseModel):
    dev: str = Field(..., min_length=1)
    id: str = Field(..., min_length=1)
    size_mb: int = Field(..., gt=0)

class PhoneHomeRequest(BaseModel):
    job_id: str = Field(..., min_length=1)
    machine_serial: str = Field(..., min_length=1)
    bootif: str = Field(..., min_length=1)
    uuids: List[DiskInfo]

JOBS_DIR = "/work/configServer/http/jobs"
TEMPLATE_DIR = "/work/configServer/templates/ubuntu"
ANSIBLE_DIR = "/work/configServer/ansible"
RELEASE_MAP_FILE = f"{TEMPLATE_DIR}/release-map.yml"

# State trackers
JOB_TRACKER = {}       # Keeps pointers to background Ansible runners
PROGRESS_TRACKER = {}  # Holds real-time lifecycle states for the provision pipelines

def load_release_map(host_ip=None):
    with open(RELEASE_MAP_FILE, "r") as f:
        content = f.read()
    if host_ip:
        content = content.replace("{{API_HOST}}", host_ip)
    else:
        server_ip = os.getenv("SERVER_IP", "localhost")
        content = content.replace("{{API_HOST}}", server_ip)
    return yaml.safe_load(content)

def render_template(template_path, output_path, substitutions):
    with open(template_path, "r") as f:
        content = f.read()

    for key, value in substitutions.items():
        content = content.replace(key, str(value))

    with open(output_path, "w") as f:
        f.write(content)


# Pass host_ip dynamically into the inventory configuration generator
def buildAnsibleInventory(sourceDict, host_ip, is_WTR):
    bmc_address = sourceDict.get('bmc_address')
    bmc_username = sourceDict.get('bmc_username')
    bmc_password = sourceDict.get('bmc_password')
    os_type = sourceDict.get('os_type')
    os_version = sourceDict.get('os_version')
    os_arch = sourceDict.get('arch')
    os_variant = sourceDict.get('variant')
    os_hostname = sourceDict.get('hostname')
    os_username = sourceDict.get('username')
    os_password = sourceDict.get('password')
    os_ipv4_address = sourceDict.get('ipv4_address')
    os_ipv4_gateway = sourceDict.get('ipv4_gateway')
    os_ipv4_netmask = sourceDict.get('ipv4_netmask')
    os_ipv6_address = sourceDict.get('ipv6_address')
    os_ipv6_gateway = sourceDict.get('ipv6_gateway')
    os_ipv6_cidr = sourceDict.get('ipv6_cidr')
    os_dns_servers = sourceDict.get('dns_servers')
    os_raid = sourceDict.get('raid')

    ansibleHostName = "testXR11"
    if is_WTR:
        ansibleHostName = "testWTR"

    ansible_inventory = {
            "all": {
                "vars": {
                    "validate_certs": False,
                    # Dynamically populated using the incoming interface parameter
                    "api_base_url": f"https://{host_ip}"
                },
                "hosts": {
                    ansibleHostName: {
                        "bmc_address": bmc_address,
                        "bmc_user": bmc_username,
                        "bmc_password": bmc_password,
                        
                        # Mapped dynamic fields from source dict
                        "os_arch": os_arch,
                        "os_type": os_type,
                        "os_version": os_version,
                        "os_variant": os_variant,
                        "os_hostname": os_hostname,
                        "os_username": os_username,
                        "os_password": os_password,
                        "os_ipv4_address": os_ipv4_address,
                        "os_ipv4_gateway": os_ipv4_gateway,
                        "os_ipv4_netmask": os_ipv4_netmask,
                        "os_ipv6_address": os_ipv6_address,
                        "os_ipv6_gateway": os_ipv6_gateway,
                        "os_ipv6_cidr": os_ipv6_cidr,
                        "os_dns_servers": os_dns_servers,
                        "os_raid": os_raid,

                        # Static Ansible connection variables
                        "ansible_host": "{{ os_ipv4_address }}",
                        "ansible_user": "{{ os_username }}",
                        "ansible_password": "{{ os_password }}",
                        "ansible_python_interpreter": "/usr/bin/python3",
                        "ansible_ssh_common_args": "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null",
                        "ansible_become_password": "{{ os_password }}"
                    }
                }
            }
        }
        
    return ansible_inventory


class Handler(http.server.BaseHTTPRequestHandler):
    # protocol_version = "HTTP/1.1"
    def get_server_host(self):
        """Helper to dynamically extract incoming host details from HTTP headers"""
        return self.headers.get('Host', 'localhost')

    def do_HEAD(self):
        if self.path.startswith("/automation"):
            try:
                parts = self.path.split('/')
                if len(parts) >= 4:
                    job_id = parts[2]
                    filename = parts[3]
                    file_path = os.path.join(JOBS_DIR, job_id, filename)

                    if os.path.exists(file_path):
                        self.send_response(200)

                        self.send_header("Server", "Python/3.x ThreadedHTTPServer")
                        self.send_header("Date", self.date_time_string())

                        if filename.endswith(".sh"):
                            self.send_header("Content-Type", "text/x-shellscript")
                        elif filename.endswith(".iso"):
                            self.send_header("Content-Type", "application/x-iso9660-image")
                        else:
                            self.send_header("Content-Type", "text/plain")
                        self.send_header("Content-Length", str(os.path.getsize(file_path)))
                        self.send_header("Accept-Ranges", "bytes")
                        self.send_header("Connection", "keep-alive")  # Keeps HTTP/1.0 sockets from snapping shut
                        self.end_headers()
                        return
            except Exception as e:
                print(f"HEAD automation Error: {e}")
            self.send_response(404)
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()

    def do_GET(self):
        host_ip = self.get_server_host()

        if "/api/v1/jobs/status" in self.path or self.path.startswith('/status'):
            try:
                # Parse job_id from the query parameter...
                query_string = self.path.split('?')[-1]
                job_id = query_string.split('=')[-1].strip('/')                
                # Check current live pipeline metrics
                progress = PROGRESS_TRACKER.get(job_id, {"stage": "UNKNOWN", "detail": "No active tasks recorded."})
                runner = JOB_TRACKER.get(job_id)

                # Sync early stage metrics with Ansible status checks
                if runner and progress["stage"] == "STAGING":
                    if runner.status == "failed":
                        progress["stage"] = "STAGING_FAILED"
                        progress["detail"] = "The Ansible out-of-band initialization pipeline failed."

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()

                # Check status dynamically via the runner object
                status_response = {
                    "job_id": job_id,
                    "lifecycle_stage": progress["stage"],
                    "stage_description": progress["detail"],
                    "ansible_staging": {
                        "status": runner.status if runner else "none",
                        "rc": runner.rc if runner else None
                    }
                }
                self.wfile.write(json.dumps(status_response).encode('utf-8'))
                return
            except Exception as e:
                print(f"GET automation Error: {e}")


        if "/installer-launch.sh" in self.path:
            try:
                # Dynamically extract the job_id from path segments safely
                # e.g., /automation/test/installer-launch.sh -> "test"
                segments = [s for s in self.path.split('/') if s]
                if len(segments) >= 2:
                    extracted_job_id = segments[1]
                    PROGRESS_TRACKER[extracted_job_id] = {
                        "stage": "INSTALLING",
                        "detail": "Target bare-metal server successfully downloaded the installer-launch.sh script and has initiated the kexec OS stream."
                    }
                    print(f"[PROGRESS-INTERCEPT] Set job '{extracted_job_id}' state to INSTALLING via dynamic file download trigger.")
            except Exception as e:
                print(f"Error updating progress on download: {e}")

        if self.path.startswith("/customOS/"):
            try:
                base_dir = "/work/configServer/http"
                file_path = os.path.join(base_dir, self.path.lstrip("/"))

                if os.path.exists(file_path):
                    file_size = os.path.getsize(file_path)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(file_size))
                    self.send_header('Connection', 'keep-alive')
                    self.end_headers()
                    with open(file_path, "rb") as f:
                        self.wfile.write(f.read())
                        self.wfile.flush()
                    return
            except Exception as e:
                print(f"GET customOS Error: {e}")

        if self.path.startswith("/automation/"):
            try:
                parts = self.path.split('/')
                if len(parts) >= 4:
                    job_id = parts[2]
                    filename = parts[3]
                    file_path = os.path.join(JOBS_DIR, job_id, filename)

                    if os.path.exists(file_path):

                        file_size = os.path.getsize(file_path)
                        #---- Handle Ranged Content-----

                        # Determine Content-Type
                        if filename.endswith(".sh"):
                            content_type = "text/x-shellscript"
                        elif filename.endswith(".iso"):
                            content_type = "application/x-iso9660-image"
                        else:
                            content_type = "text/plain"

                        # Check if the client requested a specific Range
                        range_header = self.headers.get('Range')
                        
                        if range_header and range_header.startswith("bytes="):
                            # Parse the range header (e.g., "bytes=0-499" or "bytes=5000-")
                            match = re.search(r'bytes=(\d+)-(\d*)', range_header)
                            if match:
                                start = int(match.group(1))
                                end = match.group(2)
                                end = int(end) if end else file_size - 1
                                
                                # Sanity check range bounds
                                if start >= file_size:
                                    self.send_response(416) # Range Not Satisfiable
                                    self.send_header("Content-Range", f"bytes */{file_size}")
                                    self.end_headers()
                                    return

                                chunk_size = end - start + 1
                                
                                # Send 206 Partial Content
                                self.send_response(206)
                                self.send_header("Content-Type", content_type)
                                self.send_header("Accept-Ranges", "bytes")
                                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                                self.send_header("Content-Length", str(chunk_size))
                                self.end_headers()

                                # Open and seek to the requested chunk
                                with open(file_path, "rb") as f:
                                    f.seek(start)
                                    self.wfile.write(f.read(chunk_size))
                                return

                        #-------------------------------

                        self.send_response(200)
                        if filename.endswith(".sh"):
                            self.send_header("Content-Type", "text/x-shellscript")
                        elif filename.endswith(".iso"):
                            self.send_header("Content-Type", "application/x-iso9660-image")
                        else:
                            self.send_header("Content-Type", "text/plain")
                        self.end_headers()

                        with open(file_path, "rb") as f:
                            self.wfile.write(f.read())
                        return

            

            except Exception as e:
                print(f"GET automation Error: {e}")
        
        # Check if the request is trying to proxy/redirect to an external site
        if self.path.startswith('/web/'):
            # Strip '/web/' from the path (e.g., 'web/releases.ubuntu.com/ubuntu/...')
            target_path = self.path[5:]
            
            # Construct the redirect URL using Canonical's stable IP address
            # This ensures that even after the redirect, the installer uses an IP, not DNS
            redirect_url = f"http://{target_path}"
            
            print(f"[REDIRECT] Intercepted: {self.path} -> Redirecting to: {redirect_url}", file=sys.stderr)
            
            # Send the HTTP 302 redirect response
            self.send_response(302)
            self.send_header('Location', redirect_url)
            self.end_headers()
            return

        self.send_response(404)
        self.end_headers()


    def do_POST(self):
        host_ip = self.get_server_host()
        base_url = f"http://{host_ip}/automation"

        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)
        
        # Inbound tracking hooks executed directly by target nodes during installations
        if self.path == "/api/v1/jobs/progress":
            try:
                hook_data = json.loads(body.decode())
                job_id = hook_data.get("job_id")
                new_stage = hook_data.get("stage")
                detail_msg = hook_data.get("detail", "")

                if job_id:
                    PROGRESS_TRACKER[job_id] = {
                        "stage": str(new_stage).upper(),
                        "detail": detail_msg
                    }
                    print(f"[PROGRESS-HOOK] Job '{job_id}' updated state to: {new_stage} ({detail_msg})")
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"Progress state successfully processed.")
                    return
            except Exception as e:
                print(f"POST progress hook Error: {e}")
            self.send_response(400)
            self.end_headers()
            return

        if self.path == "/api/v1/servers/provision/custom-iso":
            try:
                payload = json.loads(body.decode())
                validated_data = ProvisionCustomISORequest(**payload)
                raw_data = validated_data.model_dump()
            except ValidationError as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                formatted_errors = [{"loc": err["loc"], "msg": err["msg"], "type": err["type"]} for err in e.errors()]
                self.wfile.write(json.dumps({"success": False, "errors": formatted_errors}).encode())
                return
            except Exception as e:
                print(f"[PROVISION] JSON parse error: {e}")
                self.send_response(400)
                self.end_headers()
                return

            try:

                os_ver = raw_data.get("os_version", "24.04.4")
                release_map = load_release_map(host_ip)
                release_info = release_map[os_ver]
                if os_ver not in release_map:
                    raise Exception(f"Version {os_ver} not found in release-map.yml")

                release_info = release_map[os_ver]
                
                # Add these to the data dictionary so compose.py can see them
                raw_data["kernel_url"] = release_info["kernel"]
                raw_data["initrd_url"] = release_info["initrd"]
                raw_data["base_url"] = f"http://releases.ubuntu.com/{os_ver.split('.')[0]}.{os_ver.split('.')[1]}"
                raw_data["custom_os_url"] = f"http://{host_ip}" 
                job_id = raw_data.get("hostname", str(uuid.uuid4()))
                print(f"\n[PROVISION] Starting new job: {job_id}")
                
                # Initialize tracking status matrix 
                PROGRESS_TRACKER[job_id] = {
                    "stage": "BOOTING",
                    "detail": "ISO/iPXE compilation sequence complete. Waiting for system boot."
                }

                job_dir = os.path.join(JOBS_DIR, job_id)
                os.makedirs(job_dir, exist_ok=True)

                with open(os.path.join(job_dir, "job.json"), "w") as f:
                    json.dump(raw_data, f, indent=4)

                print(f"[PROVISION] Saved job.json")

                result = subprocess.run([
                    "/bin/bash",
                    "/work/ipxe-builder/pipeline.sh",
                    job_id,
                    os.path.join(job_dir, "job.json")
                ], capture_output=True, text=True)

                if result.returncode == 0:
                    response_body = {
                        "success": True,
                        "body": {
                            "custom_id": f"custom-{job_id}",
                            "iso_url": f"{base_url}/{job_id}/custom-{job_id}.iso",
                            "user_data_url": f"{base_url}/{job_id}/user-data",
                            "meta_data_url": f"{base_url}/{job_id}/meta-data",
                            "seed_directory_url": f"{base_url}/{job_id}/"
                        }
                    }
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(response_body).encode())
                else:
                    print(result.stderr)
                    self.send_response(500)
                    self.end_headers()

            except Exception as e:
                print(f"[PROVISION] ERROR: {e}")
                self.send_response(500)
                self.end_headers()

            return

        if self.path == "/api/v1/servers/phone-home":
            try:
                payload = json.loads(body.decode())
                validated_data = PhoneHomeRequest(**payload)
                data = validated_data.model_dump()
            except ValidationError as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                formatted_errors = [{"loc": err["loc"], "msg": err["msg"], "type": err["type"]} for err in e.errors()]
                self.wfile.write(json.dumps({"success": False, "errors": formatted_errors}).encode())
                return
            except Exception as e:
                print(f"[PHONE-HOME] JSON parse error: {e}")
                self.send_response(400)
                self.end_headers()
                return

            try:

                # print("[PHONE-HOME] PARSED JSON")
                # print(json.dumps(data, indent=4))
                # print("=======================================\n")

                job_id = data.get("job_id")
                hw_info = data.get("uuids", [])
                # print(f"\n[PHONE-HOME] Request received for: {job_id}")
                job_dir = os.path.join(JOBS_DIR, job_id)

                with open(os.path.join(job_dir, "job.json"), "r") as jf:
                    job_data = json.load(jf)

                # Advance lifecycle tracker to PHONED_HOME
                PROGRESS_TRACKER[job_id] = {
                    "stage": "PHONED_HOME",
                    "detail": f"Server successfully mapped hardware identities: Serial {data.get('machine_serial')}."
                }

                for disk in hw_info:
                    if "id" in disk and isinstance(disk["id"], str):
                        disk["id"] = disk["id"].replace(" ", "")
                        
                # Filter out CD-ROMs (sr*) and tiny loop devices
                # We only want real hard disks (usually > 1GB)
                # NVMe Multi-path Controllers ("c")
                valid_disks = [
                    d for d in hw_info 
                    if "sr" not in d.get("dev", "") 
                    and "md" not in d.get("dev", "")  # Exclude existing RAID
                    and "dm" not in d.get("dev", "")  # Exclude LVM/Mapper
                    and "c" not in d.get("dev", "")  
                    and d.get("size_mb", 0) > 1024
                ]
                
                bootif_raw = data.get("bootif", "")
                sorted_hw = sorted(valid_disks, key=lambda x: x.get('size_mb', 0))
                is_raid = job_data.get("raid", False)               

                if len(sorted_hw) >= 2 and is_raid:
                    d0_serial = sorted_hw[0].get("id") 
                    d1_serial = sorted_hw[1].get("id")
                    d0_dev = sorted_hw[0].get("dev")    
                    d1_dev = sorted_hw[1].get("dev")   
                    template_name = "user-data-raid.template"                    
                elif len(sorted_hw) >= 1:
                    # Fallback if no disks found or use the user-data.template
                    d0_serial = sorted_hw[0].get("id") if sorted_hw else "sda"
                    d1_serial = d0_serial
                    d0_dev = sorted_hw[0].get("dev")    
                    d1_dev = d0_dev

                    template_name = "user-data.template"
                else: 
                    # complete fallback if no real disks found
                    d0_serial = "sda"
                    d1_serial = "sdb"
                    template_name = "user-data.template"

                netmask = job_data.get("ipv4_netmask", "255.255.255.0")
                ipv4_address = job_data.get("ipv4_address", "")
                ipv4_netmask = job_data.get("ipv4_netmask", "255.255.255.0")
                ipv4_cidr = ""
                if ipv4_address:
                    try:
                        ipv4_cidr = str(ipaddress.IPv4Network(f"0.0.0.0/{ipv4_netmask}").prefixlen)
                    except:
                        ipv4_cidr = "24" # Safe fallback?

                # IPv6 Logic: Only pass CIDR if the address actually exists
                ipv6_address = job_data.get("ipv6_address", "")
                ipv6_cidr = ""
                ipv6_gateway = ""
                if ipv6_address:
                    ipv6_cidr = job_data.get("ipv6_cidr", "64")
                    ipv6_gateway = job_data.get("ipv6_gateway", "")

                password = job_data.get("password", "ubuntu")
                hashed_pw = subprocess.check_output(
                    ["openssl", "passwd", "-6", password],
                    text=True
                ).strip()                
                os_ver = job_data.get("os_version", "24.04.4")

                # dynamic update resolution 
                disable_updates = job_data.get("disable_updates", True)
                
                if disable_updates:
                    apt_suites_value = "[security]"
                else:
                    apt_suites_value = "[]"

                release_map = load_release_map(host_ip)

                if os_ver not in release_map:
                    raise Exception(f"Unsupported version: {os_ver}")

                release = release_map[os_ver]
                dns_first = job_data.get("dns_servers", "8.8.8.8").split(',')[0]

                # Resolve ISO URL: use local if configured in YAML, otherwise use official URL
                if "iso" in release:
                    iso_url = release["iso"]
                else:
                    major_ver = ".".join(os_ver.split('.')[:2])
                    iso_url = f"http://releases.ubuntu.com/{major_ver}/ubuntu-{os_ver}-live-server-amd64.iso"

                ipv6_full = f"{ipv6_address}/{ipv6_cidr}" if ipv6_address and ipv6_cidr else ""

                substitutions = {
                    "{{JOB_ID}}": job_id,
                    "{{API_HOST}}": host_ip, 
                    "{{HOSTNAME}}": job_data.get("hostname", job_id),
                    "{{USERNAME}}": job_data.get("username", "ubuntu"),
                    "{{USER_PASSWORD}}": hashed_pw, 
                    "{{IPV4_ADDRESS}}": ipv4_address,
                    "{{IPV4_CIDR}}": ipv4_cidr,
                    "{{IPV4_GATEWAY}}": job_data.get("ipv4_gateway"),
                    "{{IPV6_FULL}}": ipv6_full,
                    "{{IPV6_GATEWAY}}": ipv6_gateway,
                    "{{NAME_SERVERS}}": job_data.get("dns_servers", "8.8.8.8"),
                    "{{INTERFACE}}": job_data.get("ifn") or "",
                    "{{DISK_SERIAL_0}}": d0_serial,
                    "{{DISK_DEV_0}}": d0_dev,
                    "{{DISK_SERIAL_1}}": d1_serial,
                    "{{DISK_DEV_1}}": d1_dev,
                    "{{ADD_USERS}}": job_data.get("add_users", ""),
                    "{{RM_USER}}": job_data.get("rm_user", ""),
                    "{{SSH_USER_LINE}}": job_data.get("ssh_user_line", ""),
                    # "{{DISABLE_INSTALLER_UPDATE}}": installer_update_value,
                    "{{APT_DISABLE_SUITES}}": apt_suites_value
                }

                # Select template based on a raid flag in job.json        
                render_template(
                    f"{TEMPLATE_DIR}/{template_name}",
                    os.path.join(job_dir, "user-data"),
                    substitutions
                )

                with open(os.path.join(job_dir, "meta-data"), "w") as f:
                    f.write(
                        f"instance-id: {job_id}\n"
                        f"local-hostname: {substitutions['{{HOSTNAME}}']}\n"
                    )

                with open(os.path.join(job_dir, "vendor-data"), "w") as f:
                    f.write("#cloud-config\n")

                launch_subs = {
                    "__DNS_PRIMARY__": dns_first,
                    "__KERNEL_URL__": release["kernel"],
                    "__INITRD_URL__": release["initrd"],
                    "__ISO_URL__": iso_url,
                    "__SEED_URL__": f"{base_url}/{job_id}",
                    "__IPV4_ADDRESS__": job_data["ipv4_address"],
                    "__IPV4_GATEWAY__": job_data["ipv4_gateway"],
                    "__IPV4_NETMASK__": job_data["ipv4_netmask"],
                    "__HOSTNAME__": job_data.get("hostname", "ubuntu-installer"),
                    "__INTERFACE__": job_data.get("ifn") or "",
                    "__BOOTIF_RAW__": bootif_raw 
                }


                render_template(
                    f"{TEMPLATE_DIR}/installer-launch.sh.template",
                    os.path.join(job_dir, "installer-launch.sh"),
                    launch_subs
                )

                os.chmod(os.path.join(job_dir, "installer-launch.sh"),0o755)

                print(f"[PHONE-HOME] SUCCESS")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Phone home successful.")

            except Exception as e:
                print(f"[PHONE-HOME] ERROR: {e}")
                self.send_response(500)
                self.end_headers()

            return

        if self.path == "/api/v1/provision":
            try:
                payload = json.loads(body.decode())
                validated_data = AnsibleProvisionRequest(**payload)
                raw_data = validated_data.model_dump()
            except ValidationError as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                formatted_errors = [{"loc": err["loc"], "msg": err["msg"], "type": err["type"]} for err in e.errors()]
                self.wfile.write(json.dumps({"success": False, "errors": formatted_errors}).encode())
                return
            except Exception as e:
                print(f"[Ansible Provision] JSON parse error: {e}")
                self.send_response(400)
                self.end_headers()
                return

            try:
                is_WTR = raw_data.get("is_wtr")
                # Pass the dynamically extracted host_ip straight into the generator
                inventory = buildAnsibleInventory(raw_data, host_ip,is_WTR)
                job_id = raw_data.get("hostname")
                
                
                # Flag lifecycle tracker as STAGING right before spawning thread
                PROGRESS_TRACKER[job_id] = {
                    "stage": "STAGING",
                    "detail": "Ansible playbook running out-of-band initialization calls via BMC/iDRAC."
                }

                if is_WTR:
                        threadObject, runnerObject = ansible_runner.run_async(
                        private_data_dir=ANSIBLE_DIR,
                        playbook='playbookSupermicro.yml',
                        inventory=inventory,
                        ident=job_id
                    )
                else:
                    threadObject, runnerObject = ansible_runner.run_async(
                        private_data_dir=ANSIBLE_DIR,
                        playbook='playbookDell.yml',
                        inventory=inventory,
                        ident=job_id
                    )

                # 3. Store the runner object using its unique execution ID
                JOB_TRACKER[job_id] = runnerObject

                # 4. Instantly reply to the client
                self.send_response(202)  # 202 = Accepted (Processing in background)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                
                response = {
                    "status": "started",
                    "job_id": job_id,
                    "message": "Ansible playbook initiated in the background."
                }
                self.wfile.write(json.dumps(response).encode('utf-8'))
            
            except Exception as e:
                print(f"[Ansible Provision] ERROR: {e}")
                self.send_response(500)
                self.end_headers()

        # Handle native Ubuntu Autoinstall telemeif self.path == "/api/v1/jobs/telemetry":
        if self.path == "/api/v1/jobs/telemetry":
            try:
                # ---- Parse JSON safely ----
                try:
                    telemetry_data = json.loads(body.decode())
                except Exception:
                    raise ValueError("Invalid JSON payload")

                client_ip = self.client_address[0]

                # ---- Extract fields with defaults ----
                event_name = telemetry_data.get("name", "")
                event_type = telemetry_data.get("event_type", "")
                event_result = telemetry_data.get("result", "")
                description = telemetry_data.get("description", "") or ""
                origin = telemetry_data.get("origin", "")

                # ---- Normalize status EARLY (fixes your crash) ----
                native_status = (
                    event_result
                    or event_type
                    or telemetry_data.get("state")
                    or telemetry_data.get("status")
                    or "UNKNOWN"
                )

                # ---- Build log message once ----
                log_message = f"[{native_status}] {event_name} ({description})"

                # ---- Match job ID ----
                matched_job_id = None

                for job_id in PROGRESS_TRACKER.keys():
                    if job_id in event_name or job_id in description:
                        matched_job_id = job_id
                        break

                # Fallback: if exactly one job is INSTALLING
                if not matched_job_id:
                    installing_jobs = [
                        job_id
                        for job_id, progress in PROGRESS_TRACKER.items()
                        if progress.get("stage") == "INSTALLING"
                    ]
                    if len(installing_jobs) == 1:
                        matched_job_id = installing_jobs[0]

                # ---- Update progress ----
                if matched_job_id:
                    current = PROGRESS_TRACKER.get(matched_job_id, {})
                    current_stage = current.get("stage", "INSTALLING")

                    # Default: stay in current stage
                    calculated_stage = current_stage

                    if current_stage not in ["COMPLETED", "INSTALL_FAILED"]:
                        if event_result in ["FAIL", "ERROR"]:
                            calculated_stage = "INSTALL_FAILED"

                        elif (
                            event_name == "subiquity/Shutdown/shutdown"
                            and event_type == "finish"
                        ):
                            calculated_stage = "COMPLETED"

                        elif "reboot" in description.lower():
                            calculated_stage = "COMPLETED"

                        else:
                            calculated_stage = "INSTALLING"

                    PROGRESS_TRACKER[matched_job_id] = {
                        "stage": calculated_stage,
                        "detail": f"Ubuntu Installer: {log_message}",
                    }

                    # ---- Write log safely ----
                    job_dir = os.path.join(JOBS_DIR, matched_job_id)
                    log_file_path = os.path.join(job_dir, "install.log")

                    try:
                        os.makedirs(job_dir, exist_ok=True)  # ensures dir exists
                        with open(log_file_path, "a") as f:
                            f.write(log_message + "\n")
                    except Exception as file_err:
                        print(f"[FILE ERROR] {file_err}")

                # ---- Console logging ----
                print(
                    f"[TELEMETRY] "
                    f"job={matched_job_id or 'Unknown'} "
                    f"event={event_name} "
                    f"type={event_type} "
                    f"result={event_result}"
                )

                # ---- Response ----
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Telemetry processed successfully.")
                return

            except Exception as e:
                print(f"[TELEMETRY ERROR] {e}")

                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"Telemetry processing failed.")
                return
                
if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("0.0.0.0", 8000), Handler)
    print("API Server running on port 8000...")
    server.serve_forever()