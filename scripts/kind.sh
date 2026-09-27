#!/usr/bin/env bash
# Local Kubernetes: `scripts/kind.sh up|scale N|smoke|status|down`.
set -euo pipefail
cd "$(dirname "$0")/.."

KIND_VERSION=v0.31.0
CLUSTER=scm
K8S=infrastructure/kubernetes
SECRETS=$K8S/secrets.env
IMAGES=(scm-backend:local scm-ml:local scm-frontend:local)
# third-party images are loaded too, so the node never pulls during a rollout
EXTRA_IMAGES=(pgvector/pgvector:pg16 busybox:1.37)

kind_bin() {
  if command -v kind >/dev/null 2>&1; then echo kind; return; fi
  local os arch name bin
  case "$(uname -s)" in
    Linux) os=linux ;; Darwin) os=darwin ;; *) os=windows ;;
  esac
  case "$(uname -m)" in arm64 | aarch64) arch=arm64 ;; *) arch=amd64 ;; esac
  name="kind-$os-$arch"
  bin=".tools/kind"
  [[ $os == windows ]] && bin=".tools/kind.exe"
  if [[ ! -x $bin ]]; then
    mkdir -p .tools
    printf '# Local tool binaries (kind); downloaded by scripts, never committed.\n*\n' > .tools/.gitignore
    curl -fsSL -o "$bin" "https://github.com/kubernetes-sigs/kind/releases/download/$KIND_VERSION/$name"
    expected=$(curl -fsSL "https://github.com/kubernetes-sigs/kind/releases/download/$KIND_VERSION/$name.sha256sum" | cut -d' ' -f1)
    actual=$(sha256sum "$bin" | cut -d' ' -f1)
    [[ $expected == "$actual" ]] || { rm -f "$bin"; echo "kind checksum mismatch" >&2; exit 1; }
    chmod +x "$bin"
  fi
  echo "$bin"
}

random() { od -An -N"$1" -tx1 /dev/urandom | tr -d ' \n'; }

ensure_secrets() {
  [[ -f $SECRETS ]] && return
  {
    echo "POSTGRES_PASSWORD=$(random 16)"
    echo "SCM_JWT_SECRET=$(random 32)"
    echo "SCM_ML_INTERNAL_TOKEN=$(random 24)"
    echo "SCM_DEMO_PASSWORD=demo-$(random 6)"
  } > "$SECRETS"
  echo "created $SECRETS with random local secrets"
}

kc() { kubectl --context "kind-$CLUSTER" -n scm "$@"; }

wait_ready() {
  kc rollout status statefulset/postgres --timeout=300s
  for d in backend worker engine frontend; do
    kc rollout status "deployment/$d" --timeout=600s
  done
  kc wait --for=condition=complete job/seed --timeout=600s
}

case "${1:-up}" in
  up)
    KIND=$(kind_bin)
    ensure_secrets
    if [[ ${SKIP_BUILD:-0} != 1 ]]; then docker compose build; fi
    if ! "$KIND" get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
      "$KIND" create cluster --config "$K8S/kind-cluster.yaml" --wait 120s
    fi
    for image in "${EXTRA_IMAGES[@]}"; do docker image inspect "$image" >/dev/null 2>&1 || docker pull -q "$image"; done
    "$KIND" load docker-image --name "$CLUSTER" "${IMAGES[@]}" "${EXTRA_IMAGES[@]}"
    kubectl --context "kind-$CLUSTER" apply -k "$K8S"
    # pods pick up rebuilt images with the same tag only on restart
    kc rollout restart deployment backend worker engine frontend >/dev/null
    wait_ready
    echo
    echo "Cluster is up: http://localhost:8300 (API on http://localhost:8380)"
    echo "Sign in as planner, manager, finance or admin with password: $(grep '^SCM_DEMO_PASSWORD=' "$SECRETS" | cut -d= -f2-)"
    ;;
  scale)
    n=${2:?usage: $0 scale N}
    kc scale deployment/worker --replicas="$n"
    kc rollout status deployment/worker --timeout=600s
    ;;
  smoke)
    export SCM_SMOKE_URL=http://localhost:8300
    export SCM_SMOKE_PASSWORD="$(grep '^SCM_DEMO_PASSWORD=' "$SECRETS" | cut -d= -f2-)"
    uv run pytest tests/smoke -m smoke -v
    ;;
  status) kc get pods,svc,jobs -o wide ;;
  down) "$(kind_bin)" delete cluster --name "$CLUSTER" ;;
  *) echo "usage: $0 up|scale N|smoke|status|down" >&2; exit 2 ;;
esac
