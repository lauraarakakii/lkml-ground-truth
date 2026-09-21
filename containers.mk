# Shared container runtime detection, aligned with MLH-Archiver.
# Override CONTAINER when using another compatible runtime.
CONTAINER ?=

ifeq ($(CONTAINER),)
  ifeq ($(shell command -v podman 2>/dev/null),)
    CONTAINER := docker
  else
    CONTAINER := podman
  endif
endif
