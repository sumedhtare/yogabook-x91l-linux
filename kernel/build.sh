#!/bin/bash
# Build the Yoga Book YB1-X91L kernel (.deb packages) from kernel.org sources
# plus the patches in kernel/patches and the config in kernel/.
#
# Usage: kernel/build.sh [workdir]        (default workdir: ~/yb-kernel)
# Output: <workdir>/linux-image-*.deb, linux-headers-*.deb
#
# Build dependencies: if the usual ones are installed system-wide
# (sudo apt install build-essential flex bison bc libssl-dev libelf-dev
#  dwarves debhelper rsync zstd), they are used. Otherwise they are
# downloaded with `apt-get download` and unpacked into <workdir>/tools, which
# needs no root.
set -euo pipefail

VERSION=7.2.8
PKGVERSION=${PKGVERSION:-7.2.8-yogabook-cam3}
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=${1:-$HOME/yb-kernel}
SRC=$WORK/linux-$VERSION
mkdir -p "$WORK"

# --- build dependencies -----------------------------------------------------
missing=()
for t in gcc make flex bison bc perl dpkg-buildpackage; do
  command -v "$t" >/dev/null || missing+=("$t")
done
[[ -e /usr/include/libelf.h ]] || missing+=(libelf-dev)
[[ -e /usr/include/openssl/ssl.h ]] || missing+=(libssl-dev)
command -v dh_listpackages >/dev/null || missing+=(debhelper)

if ((${#missing[@]})); then
  echo "Missing system build deps (${missing[*]}); using local copies in $WORK/tools"
  T=$WORK/tools
  if [[ ! -x $T/root/usr/bin/bison ]]; then
    mkdir -p "$T/debs" && (cd "$T/debs" && apt-get download flex bison m4 libfl2 \
      libfl-dev libelf-dev libssl-dev zlib1g-dev libzstd-dev debhelper libdebhelper-perl)
    for d in "$T"/debs/*.deb; do dpkg -x "$d" "$T/root"; done
    # -dev symlinks point at runtime libs that are already installed system-wide
    for l in "$T"/root/usr/lib/x86_64-linux-gnu/*.so; do
      t=$(readlink "$l"); [[ -e $(dirname "$l")/$t ]] || ln -sf "/usr/lib/x86_64-linux-gnu/$t" "$l"
    done
  fi
  R=$T/root
  export PATH=$R/usr/bin:$PATH
  export C_INCLUDE_PATH=$R/usr/include:$R/usr/include/x86_64-linux-gnu
  export LIBRARY_PATH=$R/usr/lib/x86_64-linux-gnu LD_LIBRARY_PATH=$R/usr/lib/x86_64-linux-gnu
  export BISON_PKGDATADIR=$R/usr/share/bison M4=$R/usr/bin/m4 PERL5LIB=$R/usr/share/perl5
fi

# --- sources ------------------------------------------------------------------
cd "$WORK"
if [[ ! -d $SRC ]]; then
  wget -q "https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-$VERSION.tar.xz"
  wget -q -O sha256sums.asc https://cdn.kernel.org/pub/linux/kernel/v7.x/sha256sums.asc
  grep " linux-$VERSION.tar.xz\$" sha256sums.asc | sha256sum -c -
  tar xf "linux-$VERSION.tar.xz"
  cd "$SRC"
  git init -q && git add -A && git -c user.name=build -c user.email=build@local \
    commit -qm "Linux $VERSION"
  git -c user.name=build -c user.email=build@local am -q "$HERE"/patches/*.patch
fi

# --- build --------------------------------------------------------------------
cd "$SRC"
cp "$HERE/config-$VERSION-yogabook" .config
make -s olddefconfig
make -j"$(nproc)" bindeb-pkg KDEB_PKGVERSION="$PKGVERSION" DPKG_FLAGS=-d
ls -1 "$WORK"/linux-image-*"$PKGVERSION"*.deb "$WORK"/linux-headers-*"$PKGVERSION"*.deb
