#!/bin/sh
# Runs ON SATURN. Copy to titan: ssh saturn 'podman save localhost/sdcpp:sm86' | ssh titan 'podman load'
set -eu; B=$HOME/build/sdcpp; cd $B
nice -n 10 podman build -t localhost/sdcpp:sm86 .
podman image inspect localhost/sdcpp:sm86 --format '{{.Id}}' | tee $B/image-id.txt
