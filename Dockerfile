FROM alpine

# This installs also pip3
RUN apk update \
    && apk --no-cache add \
    python3 openssh-client git \
    cmd:pip3

# Add the SSH public keys of git hosting providers
RUN mkdir /root/.ssh
COPY docker/ssh_known_hosts.txt /root/.ssh/known_hosts

COPY requirements.txt /tmp
RUN pip3 --disable-pip-version-check install --requirement /tmp/requirements.txt \
    && rm -r /root/.cache /tmp/*

COPY vendor /usr/local/bin/vendor
COPY pool_boy.py /usr/local/bin/
COPY pool_boy.sh /usr/local/bin/

CMD /bin/sh
