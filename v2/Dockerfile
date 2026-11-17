FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY v2/frontend/package*.json ./
RUN npm ci
COPY v2/frontend/ ./
COPY meta-page-manager/frontend/fonts.css ./public/fonts.css
COPY meta-page-manager/frontend/fonts/ ./public/fonts/
RUN npm run build

FROM rust:1.90-bookworm AS gateway
WORKDIR /build
COPY v2/gateway/ ./gateway/
COPY v2/migrations/ ./migrations/
RUN cargo build --locked --release --manifest-path gateway/Cargo.toml

FROM python:3.12-slim-bookworm
WORKDIR /app/v2
COPY meta-page-manager/requirements.txt /app/meta-page-manager/requirements.txt
COPY v2/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd -m -u 10001 pagemanager
COPY meta-page-manager/backend/ /app/meta-page-manager/backend/
COPY v2/worker/ ./worker/
COPY v2/scripts/*.py ./scripts/
COPY v2/migrations/ ./migrations/
COPY --from=frontend /build/dist/ ./frontend/dist/
COPY --from=gateway /build/gateway/target/release/pagemanager-gateway /usr/local/bin/pagemanager-gateway
RUN mkdir /data && chown pagemanager:pagemanager /data
ENV PM_DATA_DIR=/data PM_LISTEN=0.0.0.0:8020 PM_WORKER_URL=http://127.0.0.1:8021
USER pagemanager
EXPOSE 8020
CMD ["python", "-m", "scripts.container"]
