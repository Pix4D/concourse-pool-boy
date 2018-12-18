# Concourse pool boy

Like a an efficient pool boy, keep the pools of the [Concourse pool-resource] clean from debris.

For an even smarter pool boy, you can tell him to check if a floating body is still alive before
cleaning it by using our improved [Pix4D pool-resource] and setting the parameters
`CONCOURSE_BASE_URL`, `CONCOURSE_USERNAME` and `CONCOURSE_PASSWORD` (see below).

Can be used from the command-line or from a Concourse pipeline.

## Status

This software is currently beta, although we are already using it in production.

Following semver numbering, expect API breakages until it reaches major version 1.
We suggest to pin to a specific commit and perform tests before upgrading.

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

`CONCOURSE_BASE_URL` is optional. It should be identical to the `--concourse-url` value passed to
`fly`. If present the `CONCOURSE_USERNAME` and `CONCOURSE_PASSWORD` are mandatory and they must be
valid Concourse credential with the appropriate rights to see the status of the builds that uses
the configured `POOL_REPO`.

## Caveats

Note that if the `CONCOURSE_BASE_URL` is not specified, the pool boy won't be able to validate if
the build that last claimed a lock is still alive or not and will then rely solely on the staleness
timeout configured. This will typically result in a pipeline failure when the following sequence of
events happen:

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


[Concourse pool-resource]: https://github.com/concourse/pool-resource
[Pix4D pool-resource]: https://github.com/Pix4D/pool-resource
