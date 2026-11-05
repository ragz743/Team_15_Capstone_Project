#!/bin/sh
set -eu
python -m scripts.migrate_conversations
exec "$@"
