FROM ubuntu:20.04
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    git \
    vim \
    net-tools \
    iputils-ping \
 && rm -rf /var/lib/apt/lists/*
CMD ["/bin/bash"]

