<!-- chmod -R 777 /work/customOS/myInitRD/
find /work/customOS/myInitRD/ -print0 | cpio --null -ov --format=newc | gzip -9 > /work/configServer/http/customOS/initramfs.cpio.gz -->

<!-- the above is not working -->
chmod -R 777 /work/customOS/myInitRD/
cd /work/customOS/myInitRD/
find . -print0 | cpio --null -ov --format=newc | gzip -9 > /work/configServer/http/customOS/initramfs.cpio.gz

# 1. Check network
ip link show

# 2. Set Static IP
ip link set eth0 up
ip addr add 10.1.10.142/24 dev eth0
ip route add default via 10.1.10.1
mkdir -p /etc && echo "nameserver 8.8.8.8" > /etc/resolv.conf

# 3. Download Installer Files
wget http://releases.ubuntu.com/24.04/netboot/amd64/linux
wget http://releases.ubuntu.com/24.04/netboot/amd64/initrd

# 4. Load the Jump (MAC address version)
/bin/kexec-amd64 -l /linux \
  --initrd=/initrd \
  --append="ip=10.1.10.142::10.1.10.1:255.255.255.0:ubuntu-srv:bc:24:11:b5:0e:76:none:8.8.8.8 url=http://releases.ubuntu.com/24.04/ubuntu-24.04.3-live-server-amd64.iso"

# 5. The Jump
/bin/kexec-amd64 -e