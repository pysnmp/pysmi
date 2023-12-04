#!/usr/bin/env bash

set -eE
set -v
echo pypy user=${PYPI_USERNAME}
poetry publish -vvv -n --username=${PYPI_USERNAME} --password=${PYPI_TOKEN}
