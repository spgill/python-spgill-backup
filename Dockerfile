FROM python:3.11-alpine
SHELL ["/bin/sh", "-c"]

# Install the backup package
COPY . /tmp
RUN pip install /tmp && rm -rf /tmp

# Install tools from apk
RUN apk add --no-cache wget bzip2 tini

# Install Restic from github (apk version is slightly behind)
ENV RESTIC_VERSION 0.16.5
RUN wget https://github.com/restic/restic/releases/download/v${RESTIC_VERSION}/restic_${RESTIC_VERSION}_linux_amd64.bz2 && \
    bzip2 -d ./restic* && \
    mv ./restic* /usr/local/bin/restic && \
    chmod +x /usr/local/bin/restic

CMD tini -v -- python -m spgill.backup --config /opt/config.yaml daemon
