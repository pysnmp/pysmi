#!/usr/bin/env bash

set -eE
set -v
echo pypy user=${PYPI_USERNAME}
poetry config pypi-token.pypi ${PYPI_TOKEN}
yes | poetry publish --build
