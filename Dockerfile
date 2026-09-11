FROM python:3.12-slim

WORKDIR /app

# Runtime display libraries; physical display access still requires host setup.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libsdl2-2.0-0 libsdl2-image-2.0-0 libsdl2-mixer-2.0-0 libsdl2-ttf-2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# This container uses a Pygame wheel; native boards may need their own SDL build.
RUN pip install --no-cache-dir --only-binary=pygame -r requirements.txt pygame==2.6.1

# Copy source only, keeping local photos, credentials, and tokens out of the image.
COPY client/*.py ./client/
COPY client/storage/*.py ./client/storage/
RUN mkdir -p client/cache client/secrets

CMD ["python", "-m", "client.main"]
