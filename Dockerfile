FROM python:3-bullseye
SHELL ["/bin/bash", "-c"]

# Add Tini
ENV TINI_VERSION v0.19.0
ADD https://github.com/krallin/tini/releases/download/${TINI_VERSION}/tini /tini
RUN chmod +x /tini

RUN pip install --index https://python.spgill.me python-spgill-backup

# Install tools
RUN apt update && \
    apt -y install --no-install-recommends wget && \
    rm -rf /var/lib/apt/lists/* && \
    apt clean

# Install Restic
WORKDIR /tmp
RUN wget https://github.com/restic/restic/releases/download/v0.15.1/restic_0.15.1_linux_amd64.bz2 && \
    bzip2 -d ./restic* && \
    mv ./restic* /usr/local/bin/restic && \
    chmod +x /usr/local/bin/restic

CMD /tini -v -- python -m spgill.backup --config /opt/config.yaml daemon
