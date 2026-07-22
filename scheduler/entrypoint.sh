#!/bin/sh
case "$SCHEDULER_JOB" in
    standings)
        python standings_refresh.py
        ;;
    archive)
        python daily_archive.py
        ;;
    *)
        echo "Unknown job: $SCHEDULER_JOB"
        exit 1
        ;;
esac