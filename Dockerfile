# Stage 1 runs on the build host and only turns uv.lock into a pinned
# requirements file, so the target image never needs a uv binary. That keeps
# the linux/386 and linux/arm/v7 images building.
FROM --platform=$BUILDPLATFORM ghcr.io/astral-sh/uv:0.13.6-python3.14-alpine AS lock

WORKDIR     /app
COPY        pyproject.toml uv.lock ./
RUN         uv export --frozen --no-dev --no-emit-project --no-hashes -o /requirements.txt

FROM python:3.14.10-alpine@sha256:eb2c62658b8d51bff0acc408504b76521d02030de56a8a3c1e830083e89b89d2

# renovate: datasource=repology depName=alpine_3_24/gettext versioning=loose
ARG         GETTEXT_VERSION="1.0-r0"

WORKDIR     /app

COPY        --from=lock /requirements.txt .

RUN         --mount=type=cache,sharing=locked,target=/root/.cache,id=home-cache-$TARGETPLATFORM \
            apk add --no-cache \
              gettext=${GETTEXT_VERSION} \
            && \
            pip install -r requirements.txt && \
            mkdir -p /app/data && \
            chown -R nobody:nogroup /app

COPY        --chown=nobody:nogroup . .

USER        nobody

RUN         cd locales && \
            find . -maxdepth 2 -type d -name 'LC_MESSAGES' -exec ash -c 'msgfmt {}/unobot.po -o {}/unobot.mo' \;

VOLUME      /app/data
ENV         UNO_DB=/app/data/uno.sqlite3

ENTRYPOINT  [ "python", "bot.py" ]
