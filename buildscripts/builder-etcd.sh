#!/bin/bash
set -e
source $(dirname $0)/tools.sh
ensure_go

branch="master"
echo $1

if [ "$1" != "" ]; then
    branch="$1"
fi

go get -u -v -d github.com/coreos/etcd

ETCD=$GOPATH/src/github.com/coreos/etcd/

pushd $ETCD
git fetch origin
git checkout -B "${branch}" origin/${branch}
mkdir -p bin
rm -rf bin/*
./build
popd

mkdir -p /tmp/archives/
tar -czf "/tmp/archives/etcd-${branch}.tar.gz" -C $ETCD/ bin

