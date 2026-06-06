sudo docker build -t ipxe-builder:local ipxe-builder

Don't use this one:
docker run --rm   -e BASE_URL="http://astro.internal.mibura.com/automation"   -e OUTPUT_ROOT="/work/nginx/html/automation"   -e VERBOSE="1"   -v "$PWD/ipxe-builder:/work"   -v "$PWD/nginx/html:/work/nginx/html"   ipxe-builder:local

use this one:
sudo docker run -it --rm \
  -v "$(pwd)"/:/work \
  --entrypoint /bin/bash \
  -p 8000:8000 \
  ipxe-builder:local

NOW:

sudo docker compose build
sudo sync; echo 3 | sudo tee /proc/sys/vm/drop_caches ; sudo docker compose run --rm --service-ports ipxe-builder

# Auto compile customOS and put into config server

sudo docker run -it --rm \
  -v "$(pwd)"/:/work \
  --entrypoint /bin/bash \
  ipxe-builder:local \
  -c "chmod -R 777 /work/customOS/myInitRD/ && \
      find /work/customOS/myInitRD/ -print0 | cpio --null -ov --format=newc | gzip -9 > /work/configServer/http/customOS/initramfs.cpio.gz"

# auto compile ipxe WIP example:
docker run --rm -v $(pwd)/out:/work/ipxe-builder/out my-ipxe-builder \
    python3 build_iso.py -t templates/custom.ipxe -n "enterprise-node"

---

cd /work
# Download and extract if you haven't yet
wget https://kernel.org/pub/linux/utils/kernel/kexec/kexec-tools-2.0.28.tar.xz
tar -xf kexec-tools-2.0.28.tar.xz
cd kexec-tools-2.0.28

# Build x86_64
make clean

# Re-configure without purgatory
LDFLAGS=-static ./configure \
  --prefix=$(pwd)/dist-x64 \
  --host=x86_64-linux-gnu \

echo "" > purgatory/arch/i386/entry32-16.S
echo "" > purgatory/arch/i386/entry32-16-debug.S
make ARCH=x86_64 -j$(nproc)

make install
make clean

# Configure for ARM64 using your installed cross-compiler
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

mount -o remount,size=90% /tmp

