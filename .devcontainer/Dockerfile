FROM mcr.microsoft.com/devcontainers/python:3-3.12-bookworm

USER root
# The app uses npm in its Node build stage. Remove the unused Yarn repository
# so an obsolete Yarn signing key cannot break feature installation via APT.
# Debian and Docker repository signature verification stays enabled.
RUN rm -f /etc/apt/sources.list.d/yarn.list /etc/apt/sources.list.d/yarn.sources
