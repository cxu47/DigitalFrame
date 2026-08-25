# DigitalFrame

A lightweight self-hosted digital photo frame application designed for Linux-based single-board computers such as Raspberry Pi and Banana Pi.

This branch contains the **DigitalFrame v1.x** implementation, which uses a self-hosted **FastAPI server** as the remote photo source.

## Overview

DigitalFrame consists of two components:

* **Server** — hosts photo files and exposes them to the client through a FastAPI application.
* **Client** — runs on the digital frame device, synchronizes photos from the server into a local cache, and displays them as a slideshow.

The project is intended to run on a Raspberry Pi, Banana Pi, or similar Linux device connected to a display.

## Features

### Client

* Connects to a configured FastAPI server.
* Retrieves the available photo list from the server.
* Downloads new photos into a local cache.
* Uses a temporary download extension until file transfers complete.
* Periodically checks the server for updates in the background.
* Monitors the local cache for changes.
* Displays cached photos as a digital slideshow.
* Continues displaying locally cached photos independently of the remote server.

### Server

* Self-hosted FastAPI application.
* Serves photos to the DigitalFrame client.
* Supports photo upload.
* Can be containerized using Docker.

## Architecture

```text
Remote / Local Host
┌──────────────────────┐
│   FastAPI Server     │
│                      │
│   Photo Storage      │
└──────────┬───────────┘
           │ HTTP
           ▼
┌──────────────────────┐
│ DigitalFrame Client  │
│                      │
│  Sync Service        │
│       ↓              │
│  Local Photo Cache   │
│       ↓              │
│  Slideshow           │
└──────────────────────┘
           │
           ▼
       Display
```

The client periodically compares the server's available photos with its local cache and downloads files that are not currently stored locally.

## Project Structure

The repository is organized around separate server and client components.

```text
DigitalFrame/
├── client/
│   ├── main.py
│   ├── sync.py
│   ├── slideshow.py
│   └── ...
├── server/
│   └── ...
├── Dockerfile
└── README.md
```

Exact contents may vary as the project develops.

## Requirements

### Client

* Linux
* Python 3
* Network connection to the FastAPI server
* Display connected to the client device

Target hardware includes Raspberry Pi, Banana Pi, and other Linux-capable single-board computers.

### Server

* Python 3
* FastAPI and the project's Python dependencies

Docker can also be used to run the server in a containerized environment.

## Running the Application

The FastAPI server must be running and reachable by the client before remote synchronization can occur.

Start the server using the configuration defined by the project, then run the client from the repository root:

```bash
python3 -m client.main
```

The client will synchronize available photos into its local cache and start the slideshow.

> Configuration details such as the server address should be defined by the application's configuration rather than hard-coded into individual modules.

## Current Behavior and Limitations

DigitalFrame v1.x is a functional proof-of-concept implementation and has several known limitations:

* Duplicate detection is based on filenames rather than file contents.
* A new server photo using an existing filename may replace the previously cached version.
* Server-side photo deletion is not yet fully synchronized to the client.
* Local cache deletion is detected by the slideshow.
* The client currently focuses primarily on downloading new files rather than full cache reconciliation.
* Authentication, encryption, and hardened production security are not yet implemented.

These limitations should be considered before exposing the FastAPI server directly to the public internet.

## Roadmap

Potential improvements for the v1.x architecture include:

* Full server-to-client deletion synchronization.
* File integrity and duplicate detection.
* Filename validation and normalization.
* Configurable slideshow interval.
* Randomized slideshow ordering.
* Configurable server URL.
* Cache validation during startup.
* Explicit overwrite policies.
* Authentication and authorization.
* Encrypted communication.
* Improved security controls.
* Collage display modes.

## Versioning

This repository follows semantic versioning for stable releases.

* **v1.x** — self-hosted FastAPI server architecture.
* **v2.x** — Google Drive-based photo synchronization architecture.

This branch is intended to preserve and, if necessary, maintain the FastAPI-based `v1.x` implementation.

For immutable release snapshots, use the corresponding Git tags and GitHub Releases rather than relying only on branch state.

## Development Status

The core v1 proof of concept includes:

* \[x] Server and client project structure
* \[x] Docker configuration
* \[x] Server-side photo upload
* \[x] Temporary file handling during downloads
* \[x] Local cache monitoring
* \[x] Periodic background server synchronization
* \[x] Photo slideshow
* \[ ] Full remote deletion synchronization
* \[ ] Authentication and hardened security
* \[ ] Configurable slideshow behavior
* \[ ] File integrity / duplicate detection

## Security

DigitalFrame v1.x was built as a proof of concept for a self-hosted environment.

Do not expose the FastAPI server directly to the public internet without adding appropriate authentication, encrypted transport, access controls, and deployment hardening.
