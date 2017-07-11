#!/bin/sh
set -e
source $(dirname $0)/tools.sh
ensure_lddcopy

TARGET=/tmp/cockroachdb
VERSION=1.0.3
echo $1

if [ "$1" != "" ]; then
    VERSION="$1"
fi

url="https://binaries.cockroachdb.com/cockroach-v${VERSION}.linux-amd64.tgz"

rm -rf $TARGET
mkdir -p $TARGET
wget "$url" -O "${TARGET}/cockroachdb.tar.gz"
tar xf $TARGET/cockroachdb.tar.gz -C $TARGET cockroach-v${VERSION}.linux-amd64/cockroach
# restructure
pushd $TARGET
rm -rf root
mkdir -p root/bin
mv cockroach-v${VERSION}.linux-amd64/cockroach root/bin
popd
lddcopy "${TARGET}/root/bin/cockroach" "${TARGET}/root"
mkdir -p /tmp/archives/
tar czf /tmp/archives/cockroachdb.tar.gz -C $TARGET/root .
