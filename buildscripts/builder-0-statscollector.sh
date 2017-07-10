#!/bin/bash
set -e
source $(dirname $0)/tools.sh
ensure_go

branch="master"
echo $1

if [ "$1" != "" ]; then
    branch="$1"
fi

NAME=0-statscollector
STATS=github.com/zero-os/$NAME

go get -v -d -u $STATS

cd $GOPATH/src/$STATS

git fetch origin "${branch}:${branch}" || true
git checkout "${branch}" || true

mkdir -p build/bin
CGO_ENABLED=0 GOOS=linux go build -a -ldflags '-extldflags "-static" -s -w' -o build/bin/$NAME .

mkdir -p /tmp/archives/
tar -czf "/tmp/archives/${NAME}-${branch}.tar.gz" -C $GOPATH/src/$STATS/build .
