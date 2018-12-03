#! /bin/sh

set -e
set -x

PRIVATE_KEY=/root/.ssh/id_rsa

echo
echo "Adding git SSH private key"

if [ -e $PRIVATE_KEY ]
then
    echo "ERROR Private key $PRIVATE_KEY already existing."
    echo "You should run this script only from a run-once Docker container for Concourse"
    exit 1
fi

set +x
echo "${POOL_REPO_SSH_PRIVATE_KEY}" > /root/.ssh/id_rsa
set -x
chmod 400 /root/.ssh/id_rsa

echo
echo "Running the pool boy"
pool_boy.py --repo "${POOL_REPO}" --pools "${POOLS}" clean
