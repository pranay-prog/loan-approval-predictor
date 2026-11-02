# Shortcuts:  make build | up | down | purge | logs | test | demo | net | persist | push | doctor | kube
VERSION ?= 1.0.0
export VERSION

.PHONY: build up down purge logs shell test demo net persist push doctor kube local

build:   ## build the custom image
	./podman/build.sh
up:      ## create network + volumes, start db and app
	./podman/up.sh
down:    ## stop & remove containers (keep data)
	./podman/down.sh
purge:   ## remove containers, volumes and network
	./podman/down.sh --purge
logs:    ## follow app logs
	podman logs -f loan-app
shell:   ## open a shell inside the app container
	podman exec -it loan-app /bin/bash
test:    ## run the test-suite inside the container
	podman exec loan-app python -m pytest -q
demo:    ## lifecycle walkthrough
	./podman/lifecycle-demo.sh
net:     ## networking checks
	./podman/network-test.sh
persist: ## persistence test (removes and recreates containers)
	./podman/persistence-test.sh
push:    ## push to registry (set REGISTRY_USER=...)
	./podman/push.sh
doctor:  ## troubleshooting report
	./podman/troubleshoot.sh
kube:    ## export running containers as Kubernetes YAML
	podman generate kube loan-app loan-db > podman/loan-kube.yaml && echo "wrote podman/loan-kube.yaml"
local:   ## run without containers (SQLite) on http://localhost:5000
	python wsgi.py
