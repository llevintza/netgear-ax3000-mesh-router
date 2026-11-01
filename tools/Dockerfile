# REA firmware-analysis environment (Linux) for MR70/MS70 firmware.
# Build: docker build -t rea-fw tools/
FROM node:24-bookworm

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv pipx \
      build-essential pkg-config libssl-dev libfontconfig1-dev liblzma-dev libbz2-dev zlib1g-dev \
      curl ca-certificates git file procps util-linux \
      e2fsprogs erofs-utils lz4 lziprecover lzop p7zip-full unar xz-utils zstd \
      squashfs-tools mtd-utils android-sdk-libsparse-utils device-tree-compiler u-boot-tools \
      ripgrep jq \
    && rm -rf /var/lib/apt/lists/*

# Rust toolchain -> binwalk 3.1.0
RUN curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
ENV PATH="/root/.cargo/bin:${PATH}"
RUN cargo install binwalk --version 3.1.0 --locked

# unblob 26.6.4 + ubi_reader, in a venv
RUN python3 -m venv /opt/unblob && /opt/unblob/bin/pip install --no-cache-dir unblob==26.6.4 ubi_reader
ENV PATH="/opt/unblob/bin:${PATH}"

# sasquatch (vendor-patched squashfs) used by unblob, if a matching .deb exists for this arch
RUN arch=$(dpkg --print-architecture) && \
    curl -fsSL -o /tmp/sasquatch.deb "https://github.com/onekey-sec/sasquatch/releases/download/sasquatch-v4.5.1-5/sasquatch_1.0_${arch}.deb" && \
    dpkg -i /tmp/sasquatch.deb || echo "sasquatch not installed (optional)"; rm -f /tmp/sasquatch.deb

# REA
RUN npm install --global rea-agents@6.8.0

ENV REA_BINWALK_COMMAND=/root/.cargo/bin/binwalk \
    REA_UNBLOB_COMMAND=/opt/unblob/bin/unblob \
    REA_FIRMWARE_PRLIMIT_COMMAND=/usr/bin/prlimit

# JDK 21 (Eclipse Temurin) - required by Ghidra 12.x
RUN arch=$(dpkg --print-architecture | sed 's/amd64/x64/;s/arm64/aarch64/') && \
    mkdir -p /opt/jdk && \
    curl -fsSL "https://api.adoptium.net/v3/binary/latest/21/ga/linux/${arch}/jdk/hotspot/normal/eclipse" \
      | tar -xz -C /opt/jdk --strip-components=1
ENV JAVA_HOME=/opt/jdk PATH="/opt/jdk/bin:${PATH}"

# Ghidra 12.1.4 (version REA's Ghidra provider is verified against), SHA-256 from the release page
ARG GHIDRA_URL=https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/ghidra_12.1.4_PUBLIC_20260921.zip
ARG GHIDRA_SHA256=ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db
RUN apt-get update && apt-get install -y --no-install-recommends unzip bison flex && rm -rf /var/lib/apt/lists/* && \
    curl -fsSL -o /tmp/ghidra.zip "$GHIDRA_URL" && \
    echo "$GHIDRA_SHA256  /tmp/ghidra.zip" | sha256sum -c - && \
    unzip -q /tmp/ghidra.zip -d /opt && rm /tmp/ghidra.zip && \
    mv /opt/ghidra_12.1.4_PUBLIC /opt/ghidra
# Release zips ship only linux_x86_64/win_x86_64 natives; on arm64 build them from the bundled
# sources (Ghidra 12: support/gradle/gradlew buildNatives -> <module>/build/os/linux_arm_64/).
RUN if [ "$(uname -m)" = "aarch64" ] && [ ! -x /opt/ghidra/Ghidra/Features/Decompiler/os/linux_arm_64/decompile ]; then \
      cd /opt/ghidra/support/gradle && ./gradlew --no-daemon buildNatives && rm -rf /root/.gradle; \
    fi && ls -la /opt/ghidra/Ghidra/Features/Decompiler/build/os/*/ /opt/ghidra/Ghidra/Features/Decompiler/os/
ENV GHIDRA_INSTALL_DIR=/opt/ghidra \
    REA_GHIDRA_STARTUP_TIMEOUT_MS=300000

WORKDIR /work
CMD ["bash"]
