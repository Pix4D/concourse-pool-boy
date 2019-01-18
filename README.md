# Concourse pool boy

Observes the pools used by the *Concourse pool resource* and resets to unclaimed any lock that it determines **stale**.

Can be used from the command-line or from a Concourse pipeline.

We strongly suggest to use our [forked version of the Concourse pool-resource], since this enables the Pool Boy to query the ATC and determine if a lock is stale based on correct liveliness information about the job which acquired it. To enable the Pool Boy to query the ATC, see section "Enabling ATC querying".

On the other hand, if paired with the original Concourse pool resource, the only criterion it can use for staleness is a timeout, so it is possible for the Pool Boy to steal a lock out of a perfectly fine job and cause mayhem when the job that owned the lock attempts to unclaim it.

## Why

There are situations when the release of a lock will fail, also if protected by an `ensure` step:

```YAML
- name: acquire-1
  plan:
    - put: acquire-pool
      params: {acquire: true}
    - task: BLAHBLAHBLAH
  ensure:
    put: acquire-pool
    params: {release: acquire-pool}
```

If the worker on which the release of the lock fails, then the build will fail and the lock will become stale: it will stay in acquired state forever, unusable, requiring manual intervention (perform a commit on the git repository that backs the locks).

Real-world situations when the worker will fail:

* Lock secrets (git SSH key) stored in a secret store, secret store lookup failing due to throttling
* Worker scheduled to run the pool resource crashing/disappearing for any reason


## Status

We have been using this software in production, periodically triggered by a Concourse pipeline, for a few months and it is stable to use.

We follow semver numbering. We suggest to pin to a specific commit and perform tests before upgrading.

See also the [CHANGELOG](CHANGELOG.md).

## Usage from the command-line

```text
Usage: pool_boy.py [OPTIONS] COMMAND [ARGS]...

Options:
  --verbose                Turn on verbose logging
  --repo TEXT              URL of the Concourse lock pool repo  [required]
  --pools TEXT             Comma-separated list of pool name and timeout pairs. The pair
                           items must be separated by ":", for example:
                           worker_pool:60,tester_pool:30. The timeout parameter defines
                           the number of minutes after which the lock is considered
                           stale.  [required]
  --help                   Show this message and exit.

Commands:
  clean   Cleans the pool.
  status  Reports the status of the pool.
```

## Usage from a Concourse pipeline

Something along the lines of

```YAML
resources:
  - name: schedule.time
    type: time
    source:
      interval: 10m <= adjust accordingly, more often doesn't make sense

jobs:
  - name: pool-boy
    build_logs_to_retain: 100
    max_in_flight: 1
    on_failure:
      put: NOTIFY_SOMEHOW
      params:
        message: "Splash! The pool boy fell into the pool. Rescue him!"
    plan:
      - get: schedule.time
        trigger: true
      - task: pool-boy
        config:
          platform: linux
          image_resource:
            type: docker-image
            source:
              repository: MYDOCKER/pool-boy
              tag: latest
          run:
            path: /usr/local/bin/pool_boy.sh
        params:
          CONCOURSE_BASE_URL: http://my-concourse.local
          CONCOURSE_USERNAME: ((THE_CONCOURSE_USER))
          CONCOURSE_PASSWORD: ((THE_USER_PASSWORD))
          POOL_REPO: MY_CONCOURSE_LOCKS_REPO
          POOL_REPO_SSH_PRIVATE_KEY: ((MY_GIT_SSH_PRIVATE_KEY))
          POOLS: POOL_1:STALE_TIMEOUT_1,POOL_2:STALE_TIMEOUT_2
```

## Enabling ATC querying

To enable the Pool Boy to query the ATC and determine if a lock is stale based on correct liveliness information about the job which acquired it:

1. Use our [forked version of the Concourse pool-resource].
2. Set `CONCOURSE_BASE_URL`, `CONCOURSE_USERNAME` and `CONCOURSE_PASSWORD` as follows.

`CONCOURSE_BASE_URL` is optional. It should be identical to the `--concourse-url` value passed to
`fly`. If present the `CONCOURSE_USERNAME` and `CONCOURSE_PASSWORD` are mandatory and they must be
valid Concourse credential with the appropriate rights to see the status of the builds that uses
the configured `POOL_REPO`.

## Caveats

Note that if you don't follow section "Enabling ATC querying", then the Pool Boy won't be able to validate if the build that last claimed a lock is still alive or not and will then rely solely on the staleness timeout configured.

This will typically result in a pipeline failure when the following sequence of events happen:

1. A job acquires lock `lock-1`.
2. Time passes by, the Pool Boy detects `lock-1` as stale and brings it back to the available pool.
3. The job of step 1 finishes running and attempts to release `lock-1`. The pool resource will fail (because the lock disappeared on git, moved by the Pool Boy) and the associated pipeline will fail!

So think twice before deciding the timeout values!

## Testing

The script works out-of-the box on macOS and Linux. You can optionally run it from a Docker container.

    docker build --tag MYORG/pool-boy:latest .

Make your private SSH key available to the Docker container:

This works if the host is Linux, but is broken if the host is Mac (https://github.com/docker/for-mac/issues/483)

    docker run \
        --volume $SSH_AUTH_SOCK:/ssh-agent \
        --env SSH_AUTH_SOCK=/ssh-agent \
        --interactive --tty --rm \
        MYORG/pool-boy:latest

Run the container and get a shell:

    docker run \
    --interactive --tty --rm MYORG/pool-boy:latest

Use local remote for quick feedback loop

One shot:

    git clone --bare MY_CONCOURSE_LOCKS_REPO concourse-pool-boy-test-local

Replace the repo URL with your own repo.

Then:

    pool_boy.py --repo (pwd)/concourse-pool-boy-test-local --pools testers status
    pool_boy.py --repo (pwd)/concourse-pool-boy-test-local --pools testers clean

## TODO

* Add Prometheus metrics via pushgateway.
* The final form should actually be a Concourse resource, instead than a script that is run as a pipeline task.

## License

Copyright 2018 Pix4D

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.

### Vendor dependencies

* brigit by Kozea, BSD Licence
* additional dependencies listed in requirements.txt

    git subtree add -m 'Import github.com/Kozea/brigit.git 4fae4e5 2016-06-20' --squash --prefix vendor/brigit git://github.com/Kozea/brigit.git 4fae4e516ed77929037ba5d95eba2eca69faffbf

Note: there is no built-in help for git subtree, on the other hand the very good help is at https://github.com/git/git/blob/master/contrib/subtree/git-subtree.txt


[forked version of the Concourse pool-resource]: https://github.com/Pix4D/pool-resource
