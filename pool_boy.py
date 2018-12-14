#!/usr/bin/env python3

"""
Clean up leaves and corpses from the pools.
"""

import glob
import logging
import os
import os.path
import re
import shutil
from datetime import datetime, timedelta, timezone

import click
import dateutil.parser
import requests
from vendor.brigit.brigit import Git

CONCOURSE_BASE_URL = os.environ.get('CONCOURSE_BASE_URL')
CLAIM_COMMIT_RE = re.compile(
    r'[0-9a-f]+\s+'
    r'(?P<team>.*)/(?P<pipeline>.*)/(?P<job>.*)\s+build\s+(?P<build>.*)\s+'
    r'claiming:\s+.*'
)

logging.basicConfig(format='%(message)s')
log = logging.getLogger('pool-boy')

DIRTY_POOLS_WORK_DIR = 'dirty-pools'
conf = {}


def refresh_local_repo(conf):
    os.makedirs(DIRTY_POOLS_WORK_DIR, exist_ok=True)

    os.chdir(DIRTY_POOLS_WORK_DIR)
    log.debug('Working directory %s', os.path.abspath('.'))

    local_repo = os.path.abspath(conf['local-repo'])
    if os.path.exists(local_repo):
        log.debug('Found working repo %s. Removing it', local_repo)
        shutil.rmtree(local_repo)
    else:
        log.debug('No working repo found')
    log.info('Cloning %s', conf['remote-repo'])
    # Doing a shallow clone sometimes takes even more than a full clone, so we keep things simple.
    git = Git(local_repo, conf['remote-repo'])

    log.debug('Setting committer info for the repo')
    git.config('user.name', 'Pool Boy')
    git.config('user.email', '<pool-boy@localhost>')

    return git


class BearerAuth(requests.auth.AuthBase):
    def __init__(self, token):
        self.token = token

    def __call__(self, request):
        request.headers['Authorization'] = 'Bearer ' + self.token
        return request


def get_concourse_auth():
    """Exchange the username and password for a token

    See: https://www.oauth.com/oauth2-servers/access-tokens/password-grant/
    """
    if CONCOURSE_BASE_URL is None:
        return None
    url = CONCOURSE_BASE_URL + '/sky/token'
    username = os.environ['CONCOURSE_USERNAME']
    password = os.environ['CONCOURSE_PASSWORD']
    reply = requests.post(
        url,
        auth=('fly', 'Zmx5'),  # See: https://github.com/concourse/concourse/blob/3792bda9c3705ce3a10f03d18b2768b9954fc51d/skymarshal/skyserver/skyserver.go#L298
        data=dict(username=username,
                  password=password,
                  grant_type='password',
                  scope='openid profile email federated:id groups')
    )
    if reply.ok:
        return BearerAuth(reply.json()['access_token'])
    log.error(f'Failed to authenticate as {username!r} at {url}')
    return None


def get_build_status(auth, team, pipeline, job, build):
    """Check with Concourse if a build is still alive

    The returned value is either:
    - None: If a meaningful reply from Concourse could not be obtained
            either due to networking issue or simply because the pipeline
            got destroyed.
    - The build status as reported by Concourse. Live builds are 'started'.
    """
    if not auth:
        return None

    reply = requests.get(
        CONCOURSE_BASE_URL + f'/api/v1/teams/{team}/pipelines/{pipeline}/jobs/{job}/builds/{build}',
        auth=auth
    )
    if not reply.ok:
        return None
    return reply.json()['status']


def clean_pool(git, pool, stale_timeout, dry_run):
    changes = 0
    log.info('\n====== Looking for claimed locks in pool %s (stale timeout %s) ======',
             pool, stale_timeout)
    assert os.path.isdir(pool), "Pool dir %s doesn't exist" % os.path.abspath(pool)
    claimed_dir = os.path.join(pool, 'claimed')
    unclaimed_dir = os.path.join(pool, 'unclaimed')

    def clear_lock(taken_lock):
        if not dry_run:
            free_lock = os.path.join(unclaimed_dir, os.path.basename(taken_lock))
            log.info(f"Moving {taken_lock} to {free_lock}")
            git.mv(taken_lock, free_lock)

    locks = glob.glob(os.path.join(claimed_dir, '*'))
    if not locks:
        log.info('No claimed locks')
        return changes
    now_ts = datetime.now(timezone.utc)
    auth = get_concourse_auth()
    for taken_lock in locks:
        log.info('---')
        lock_acquire_msg = git.log('--pretty=oneline', '--max-count=1', taken_lock).rstrip()
        log.info('lock: %s (%s)', taken_lock, lock_acquire_msg)
        match = CLAIM_COMMIT_RE.match(lock_acquire_msg)
        build_status = get_build_status(auth=auth, **match.groupdict()) if match else None
        # Format is ISO-8601: 2018-10-04T12:39:47+00:00
        claim_str = git.log('--format=%cI', '--max-count=1', taken_lock)
        claim_ts = dateutil.parser.parse(claim_str)
        log.debug('time now        %s', now_ts)
        log.debug('claim timestamp %s', claim_ts)
        lifetime = now_ts - claim_ts
        if build_status == 'started':
            log.info(f"Owning build is still alive after {lifetime}. Leaving lock as is.")
            continue
        elif build_status is not None:
            log.info(
                f"Owning build is terminated with status {build_status!r} (lifetime: {lifetime}).")
            changes += 1
            clear_lock(taken_lock)
        elif lifetime > stale_timeout:
            log.info(f"Couldn't check the build status and lock is stale (lifetime: {lifetime}).")
            changes += 1
            clear_lock(taken_lock)
        else:
            log.info(f"Couldn't check the build status "
                     f"but lock is not stale yet (lifetime: {lifetime}).")
    return changes


@click.group()
@click.option('--verbose', default=False, is_flag=True,
              help='Turn on verbose logging')
@click.option('--repo', required=True,
              help='URL of the Concourse lock pool repo')
@click.option('--pools', required=True,
              help='Comma-separated list of pool name and timeout pairs. '
                   'The pair items must be separated by ":", '
                   'for example: worker_pool:60,tester_pool:30. '
                   'The timeout parameter defines the number of minutes after which '
                   'the lock is considered stale.')
def cli(verbose, repo, pools):
    if verbose:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.INFO)
    local_repo = repo.split('/')[-1].split('.')[0]
    assert '/' not in local_repo
    conf['remote-repo'] = repo
    conf['local-repo'] = local_repo
    conf['pools'] = list(_parse_pools(pools))
    log.debug('Configuration: %s', conf)


def _parse_pools(pools):
    for part in pools.split(','):
        name_timeout = part.split(':', 1)
        assert len(name_timeout) == 2
        yield (name_timeout[0], timedelta(minutes=int(name_timeout[1])))


def clean_pools(git, pools, dry_run):
    return sum(clean_pool(git, name, timeout, dry_run) for (name, timeout) in pools)


@cli.command()
def status():
    """Reports the status of the pool."""
    git = refresh_local_repo(conf)
    os.chdir(conf['local-repo'])
    changes = clean_pools(git, conf['pools'], dry_run=True)
    log.info('\nSummary: detected %d changes', changes)


@cli.command()
def clean():
    """Cleans the pool."""
    git = refresh_local_repo(conf)
    os.chdir(conf['local-repo'])
    changes = clean_pools(git, conf['pools'], dry_run=False)
    if changes:
        log.info('\nChanges to commit:')
        log.info(git.status('--short'))
        log.info('Committing')
        git.commit('--all',
                   '--message=Freshening up the pool with %s changes' % changes)
        log.info('Pushing to %s', git.remote('get-url', '--push', 'origin'))
        git.push('origin', 'master')
    else:
        log.info('\nNo changes to push')


if __name__ == '__main__':
    cli()  # pylint: disable=no-value-for-parameter
    log.info('Done')
