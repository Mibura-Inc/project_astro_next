#!/bin/bash
set -e

JOB_ID=$1
JOB_FILE=$2
JOB_DIR="/work/configServer/http/jobs/$JOB_ID"
BUILD_DIR="/work/ipxe-builder"

echo "Building ISO for Job: $JOB_ID"

# 1. Dynamic Compose (Injects JSON into iPXE)
python3 $BUILD_DIR/compose.py -t $BUILD_DIR/template2.ipxe -o $BUILD_DIR/boot.ipxe --context "$JOB_FILE"

# 2. Build iPXE Binary
cd $BUILD_DIR/ipxe/src
sed -i 's/\/\/#define PING_CMD/#define PING_CMD/' config/general.h
sed -i 's/\/\/#define IMAGE_TRUST_CMD/#define IMAGE_TRUST_CMD/' config/general.h
make bin-x86_64-efi/ipxe.efi EMBED=$BUILD_DIR/boot.ipxe -j$(nproc)

# 3. Assemble ISO Structure
mkdir -p $BUILD_DIR/iso_temp/EFI/BOOT
cp bin-x86_64-efi/ipxe.efi $BUILD_DIR/iso_temp/EFI/BOOT/BOOTX64.EFI

# 4. Create EFI Boot Image
cd /work
dd if=/dev/zero of=$BUILD_DIR/efiboot.img bs=1k count=2048
mkfs.vfat $BUILD_DIR/efiboot.img
mmd -i $BUILD_DIR/efiboot.img ::/EFI
mmd -i $BUILD_DIR/efiboot.img ::/EFI/BOOT
mcopy -i $BUILD_DIR/efiboot.img $BUILD_DIR/iso_temp/EFI/BOOT/BOOTX64.EFI ::/EFI/BOOT/BOOTX64.EFI

# 5. Generate Final ISO into the Job Directory
mkdir -p "$JOB_DIR"
# xorriso -as mkisofs \
#     -v -J -R \
#     -append_partition 2 0xef $BUILD_DIR/efiboot.img \
#     -e --interval:appended_partition_2:all:: \
#     -no-emul-boot \
#     -o "$JOB_DIR/custom-$JOB_ID.iso" \
#     $BUILD_DIR/iso_temp

cp $BUILD_DIR/efiboot.img $BUILD_DIR/iso_temp/efiboot.img

# supermicro specific, but works with others
xorriso -as mkisofs \
    -v -J -R \
    -c boot.cat \
    -eltorito-alt-boot \
    -e efiboot.img \
    -no-emul-boot \
    -o "$JOB_DIR/custom-$JOB_ID.iso" \
    $BUILD_DIR/iso_temp

echo "Successfully generated: $JOB_DIR/custom-$JOB_ID.iso"