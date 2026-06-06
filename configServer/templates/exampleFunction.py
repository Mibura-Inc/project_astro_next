import os
import secrets
import shutil
import ipaddress
import crypt
from pathlib import Path
from typing import Optional
import subprocess


def _generate_seed_files(
        self,
        custom_id: str,
        os_type: str,
        os_version: str,
        arch: str,
        variant: str,
        hostname: str,
        username: str,
        password: str,
        ipv4_address: str,
        ipv4_gateway: str,
        ipv4_netmask: str,
        ipv6_address: Optional[str],
        ipv6_gateway: Optional[str],
        ipv6_cidr: Optional[str],
        dns_servers: str,
    ) -> None:
        """
        Generate custom seed files (user-data, meta-data) from templates.
        
        Template path:
        - {IPXE_SEEDS_PATH}/{os_type}-{os_version}/{arch}/{variant}/user-data.template
        
        Output paths:
        - Temporary work dir: {IPXE_BUILD_DIR}/seeds/{custom_id}/
        - Final nginx dir:    {IPXE_OUTPUT_ROOT}/{custom_id}/
        """
        template_dir = (
            Path(IPXE_SEEDS_PATH)
            / f"{os_type}-{os_version}"
            / arch
            / variant
        )
        template_file = template_dir / "user-data.template"
        
        if not template_file.exists():
            raise UnprocessableEntityError(f"Template not found: {template_file}")
        
        with open(template_file, "r", encoding="utf-8") as f:
            template_content = f.read()
        
        # Calculate CIDR prefix from netmask
        ipv4_cidr = str(
            ipaddress.IPv4Network(
                f"{ipv4_address}/{ipv4_netmask}", strict=False
            ).prefixlen
        )
        
        # Hash password for user creation
        hashed_password = crypt.crypt(password, crypt.mksalt(crypt.METHOD_SHA512))
        
        substitutions = {
            "{{HOSTNAME}}": hostname,
            "{{USERNAME}}": username,
            "{{USER_PASSWORD}}": password,
            "{{REMOVE_USER}}": "" if username == "ubuntu" else "ubuntu",
            "{{IPV4_ADDRESS}}": ipv4_address,
            "{{IPV4_CIDR}}": ipv4_cidr,
            "{{IPV4_GATEWAY}}": ipv4_gateway,
            "{{IPV6_ADDRESS}}": ipv6_address or "",
            "{{IPV6_CIDR}}": ipv6_cidr or "",
            "{{IPV6_GATEWAY}}": ipv6_gateway or "",
            "{{NAME_SERVERS}}": dns_servers.replace(",", ", "),
            "{{JOB_ID}}": custom_id,
        }
        
        user_data_content = template_content
        for placeholder, value in substitutions.items():
            user_data_content = user_data_content.replace(placeholder, value)
        
        # Temporary working directory for this custom ID's seeds
        tmp_seed_dir = Path(IPXE_BUILD_DIR) / "seeds" / custom_id
        tmp_seed_dir.mkdir(parents=True, exist_ok=True)
        
        tmp_user_data = tmp_seed_dir / "user-data"
        tmp_meta_data = tmp_seed_dir / "meta-data"
        
        with open(tmp_user_data, "w", encoding="utf-8") as f:
            f.write(user_data_content)
        
        with open(tmp_meta_data, "w", encoding="utf-8") as f:
            f.write(f"instance-id: {custom_id}\n")
            f.write(f"local-hostname: {hostname}\n")
        
        # Final nginx directory (shared with iPXE builder & web server)
        nginx_seed_dir = Path(IPXE_OUTPUT_ROOT) / custom_id
        nginx_seed_dir.mkdir(parents=True, exist_ok=True)
        
        shutil.copy2(tmp_user_data, nginx_seed_dir / "user-data")
        shutil.copy2(tmp_meta_data, nginx_seed_dir / "meta-data")
        
        Logger.log.info(f"Generated seed files for custom ID {custom_id}: {nginx_seed_dir}")