# ipxe-builder/Dockerfile
# Builds iPXE artifacts using ./build.sh inside ipxe-builder/
# Expects index.json, seeds/, src/ (or will fallback to /opt/ipxe)

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Build toolchain + utilities used by iPXE and util/genfsimg
# + ISO extraction tools: libarchive-tools (bsdtar), p7zip-full (7z), file
# + initramfs-tools for unmkinitramfs (proper multi-layer initrd extraction)
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    build-essential \
    wget \
    git \
    python3 \
    ca-certificates \
    curl \
    mtools \
    xorriso \
    genisoimage \
    dosfstools \
    cpio \
    pkg-config \
    liblzma-dev \
    uuid-runtime \
    gcc-aarch64-linux-gnu \
    binutils-aarch64-linux-gnu \
    gettext-base \
    isolinux \
    syslinux-common \
    syslinux-utils \
    libarchive-tools \
    p7zip-full \
    file \
    squashfs-tools \
    lz4 \
    zstd \
    initramfs-tools \
    rsync \
    python3-pip \
 && rm -rf /var/lib/apt/lists/*

# Optional fallback iPXE source if host doesn't mount ./ipxe
# RUN git clone --depth=1 https://github.com/ipxe/ipxe.git /opt/ipxe

# Default runtime env; can be overridden at docker run
ENV SRC_DIR=/work/ipxe/src \
    OUTPUT_ROOT=/work/nginx/html/automation \
    ISO_BASE_URL=http://test.com \
    SEED_SRC=/work/seeds \
    SEED_ENABLE_SUBST=1 \
    HOSTNAME_DEFAULT= \
    SKIP_ISO_DOWNLOAD=0 \
    FORCE_INITRD_REPACK=0 \
    SKIP_DRIVER_INJECTION=0 \
    FORCE_ISO_DOWNLOAD=0 \
    IGNORE_REPACK=0

WORKDIR /work

RUN pip install ansible ansible-runner --break-system-packages

# Entrypoint: ensure build.sh is executable and run it
# RUN printf '%s\n' \
# '#!/usr/bin/env bash' \
# 'set -euo pipefail' \
# '' \
# 'cd /work' \
# '' \
# '# Ensure build.sh is executable' \
# 'if [[ ! -x "./build.sh" ]]; then' \
# '  if [[ -f "./build.sh" ]]; then' \
# '    chmod +x ./build.sh' \
# '  else' \
# '    echo "[entrypoint] ERROR: ./build.sh not found in /work" >&2' \
# '    exit 1' \
# '  fi' \
# 'fi' \
# '' \
# 'echo "[entrypoint] Running build.sh $*"' \
# 'exec ./build.sh "$@"' \
# > /entrypoint.sh && chmod +x /entrypoint.sh

# ENTRYPOINT ["/entrypoint.sh"]
