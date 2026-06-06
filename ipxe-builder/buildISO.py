import argparse
import subprocess
import os
from datetime import datetime

def run_cmd(cmd, cwd=None):
    print(f"Executing: {cmd}")
    subprocess.run(cmd, shell=True, check=True, cwd=cwd)

parser = argparse.ArgumentParser()
parser.add_argument("-t", "--template", required=True)
parser.add_argument("-n", "--name", default="astro-x64")
parser.add_argument("-o", "--outdir", default="/work/ipxe-builder/out")
args = parser.parse_args()

# 1. Setup Dynamic Paths
timestamp = datetime.now().strftime("%Y%m%d-%H%M")
final_iso_path = os.path.join(args.outdir, f"{args.name}-{timestamp}.iso")
work_dir = "/work/ipxe-builder"
iso_temp = f"{work_dir}/iso_temp"

# 2. Run your existing compose logic
run_cmd(f"python3 {work_dir}/compose.py -t {args.template} -o {work_dir}/boot.ipxe")

# 3. Compile iPXE
ipxe_src = "/work/ipxe-builder/ipxe/src"
run_cmd("sed -i 's/\\/\\/#define PING_CMD/#define PING_CMD/' config/general.h", cwd=ipxe_src)
run_cmd(f"make bin-x86_64-efi/ipxe.efi EMBED={work_dir}/boot.ipxe -j$(nproc)", cwd=ipxe_src)

# 4. Stage and Create Image
run_cmd(f"mkdir -p {iso_temp}/EFI/BOOT")
run_cmd(f"cp {ipxe_src}/bin-x86_64-efi/ipxe.efi {iso_temp}/EFI/BOOT/BOOTX64.EFI")

# 5. Dynamic XORRISO Call
xorriso_cmd = (
    f"xorriso -as mkisofs -v -J -R "
    f"-append_partition 2 0xef {work_dir}/efiboot.img "
    f"-e --interval:appended_partition_2:all:: "
    f"-no-emul-boot -o {final_iso_path} {iso_temp}"
)
run_cmd(xorriso_cmd)

print(f"Successfully built: {final_iso_path}")