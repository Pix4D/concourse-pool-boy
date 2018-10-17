#!/usr/bin/env python3

"""
Clean up leaves and corpses from the pools.
"""

import glob
import logging
import os
import os.path
import shutil
import textwrap
from datetime import datetime, timedelta, timezone

import click
import dateutil.parser
from vendor.brigit.brigit import Git

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


def clean_pool(git, pool, dry_run):
    changes = 0
    log.info('\n====== Looking for claimed locks in pool %s (stale timeout %s) ======',
             pool, conf['stale-timeout'])
    assert os.path.isdir(pool), "Pool dir %s doesn't exist" % os.path.abspath(pool)
    claimed_dir = os.path.join(pool, 'claimed')
    unclaimed_dir = os.path.join(pool, 'unclaimed')
    locks = glob.glob(os.path.join(claimed_dir, '*'))
    if not locks:
        log.info('No claimed locks')
        return changes
    now_ts = datetime.now(timezone.utc)
    for taken_lock in locks:
        log.info('---')
        lock_acquire_msg = git.log('--pretty=oneline', '--max-count=1', taken_lock).rstrip()
        log.info('lock: %s (%s)', taken_lock, lock_acquire_msg)
        # Format is ISO-8601: 2018-10-04T12:39:47+00:00
        claim_str = git.log('--format=%cI', '--max-count=1', taken_lock)
        claim_ts = dateutil.parser.parse(claim_str)
        log.debug('time now        %s', now_ts)
        log.debug('claim timestamp %s', claim_ts)
        lifetime = now_ts - claim_ts
        if lifetime > conf['stale-timeout']:
            log.info('Lock is stale (lifetime: %s)', lifetime)
            changes += 1
            if not dry_run:
                free_lock = os.path.join(unclaimed_dir, os.path.basename(taken_lock))
                log.info('Moving %s to %s' % (taken_lock, free_lock))
                git.mv(taken_lock, free_lock)
        else:
            log.info('Lock is not stale (lifetime: %s)', lifetime)
    return changes


@click.group()
@click.option('--verbose', default=False, is_flag=True,
              help='Turn on verbose logging')
@click.option('--repo', required=True,
              help='URL of the Concourse lock pool repo')
@click.option('--pools', required=True,
              help='Comma-separated list of pools to inspect inside the repo')
@click.option('--stale-timeout', default=60, show_default=True,
              help='Staleness timeout in minutes')
def cli(verbose, repo, pools, stale_timeout):
    if verbose:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.INFO)
    local_repo = repo.split('/')[-1].split('.')[0]
    assert '/' not in local_repo
    conf['remote-repo'] = repo
    conf['local-repo'] = local_repo
    conf['pools'] = pools.split(',')
    conf['stale-timeout'] = timedelta(minutes=stale_timeout)
    log.debug('Configuration: %s', conf)


def clean_pools(git, pools, dry_run):
    return sum(clean_pool(git, p, dry_run) for p in pools)


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
