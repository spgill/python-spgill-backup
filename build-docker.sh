#!/bin/bash
FILE="Dockerfile"
TAG="docker.home.spgill.me/backup"
FROM="python:3-bullseye"
PUSH=true

docker rmi "$TAG:previous"
docker tag "$TAG:latest" "$TAG:previous"
docker pull "$FROM"
docker build --force-rm "$@" -f "$FILE" -t "$TAG:latest" .

# If push variable is "true", then push the image
if [ $PUSH = true ]; then
    docker push "$TAG:latest"
fi
