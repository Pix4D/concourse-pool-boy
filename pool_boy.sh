#! /bin/sh

set -e
set -x

echo
echo "Adding git SSH private key"
set +x
echo "${POOL_REPO_SSH_PRIVATE_KEY}" > /root/.ssh/id_rsa
set -x
chmod 400 /root/.ssh/id_rsa

echo
echo "Running the pool boy"
pool_boy.py --repo "${POOL_REPO}" --pools "${POOLS}" --stale-timeout "${STALE_TIMEOUT}" clean
