#!/usr/bin/env bash

set -eE
set -v
uv publish --username "${PYPI_USERNAME}" --password "${PYPI_TOKEN}"
