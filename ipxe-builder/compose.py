import os
import argparse
import json 


def build_ipxe_context(job_data):
    """
    Maps raw API JSON fields to the uppercase __VAR__ format 
    expected by iPXE templates.
    """
    os_ver = job_data.get("os_version", "24.04")
    major_ver = ".".join(os_ver.split('.')[:2]) 
    raw_ip = job_data.get("custom_os_url").replace("http://", "").replace("https://", "").split("/")[0]

    return {
        "JOB_ID": job_data.get("hostname", "unknown-job"),
        "OS_VER": f"{os_ver}",
        "ARCH": job_data.get("arch", "amd64"),
        "IPV4": job_data.get("ipv4_address"),
        "MASK": job_data.get("ipv4_netmask"),
        "GW": job_data.get("ipv4_gateway"),
        "CUSTOM_OS_URL": job_data.get("custom_os_url"), 
        "KERNEL_URL": job_data.get("kernel_url"),
        "INITRD_URL": job_data.get("initrd_url"),
        "DNS_PRIMARY": job_data.get("dns_servers", "8.8.8.8").split(",")[0].strip(),
        "DNS_LIST": job_data.get("dns_servers", "8.8.8.8").replace(",", ":"),
        "BASE": f"http://releases.ubuntu.com/{major_ver}",
        "HOSTNAME": job_data.get("hostname"),
        "SERVER_IP": raw_ip, 
    }

def compose_ipxe(template_path, output_path, context):
    """
    Reads a template and replaces __VAR__ placeholders with context values.
    """
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Template not found at {template_path}")

    with open(template_path, 'r') as f:
        content = f.read()

    # Perform the replacements
    for key, value in context.items():
        placeholder = f"__{key}__"
        content = content.replace(placeholder, str(value))

    # Ensure the iPXE shebang is present at the very top
    if not content.startswith("#!ipxe"):
        content = "#!ipxe\n" + content

    with open(output_path, 'w') as f:
        f.write(content)
    
    print(f"Successfully hydrated {output_path}")

# Example Usage
DEFAULT_CONTEXT = {
    "JOB_ID": "12345",
    "OS_VER": "Ubuntu-24.04",
    "ARCH": "x86_64",
    "IPV4": "10.1.10.142",
    "MASK": "255.255.255.0",
    "GW": "10.1.10.1",
    "DNS_PRIMARY": "8.8.8.8",
    "SEED_URL": "http://cfg.local/seed",
    "BASE": "http://releases.ubuntu.com/24.04",
    "DNS_LIST": "8.8.8.8:8.8.4.4:1.1.1.1"
}

def main():
    parser = argparse.ArgumentParser(description="Hydrate iPXE templates with job context.")
    
    # Define arguments
    parser.add_argument("-t", "--template", required=True, help="Path to the .ipxe template file")
    parser.add_argument("-o", "--output", required=True, help="Full path for the output file (including filename)")
    parser.add_argument("--context", required=False, help="Path to JSON context file")
    
    args = parser.parse_args()

    # Hardcoded context (or you could load this from a JSON file)
    if args.context: 
        with open(args.context, 'r') as f:
            raw_job_data = json.load(f)

            # Transform the data
            job_context = build_ipxe_context(raw_job_data)
    else:
        # job_context = DEFAULT_CONTEXT
        # If no context is provided, we should raise an error instead of using defaults
        raise Exception("No job context provided. Use --context job.json")

    try:
        compose_ipxe(args.template, args.output, job_context)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()