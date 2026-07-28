.PHONY: install preflight m0-render m0-probe smoke bench-ab report monitor-serve monitor-watch
install:
	pip install -e . --break-system-packages 2>/dev/null || pip install -e .
	git submodule update --init
preflight:
	python -m tokiln.cli preflight
m0-render:
	python -m tokiln.cli render --profile m0-sglang-only
m1-render:
	python -m tokiln.cli render --profile m1-dynamo-agg-2xtp8
m2-render:
	python -m tokiln.cli render --profile m1-dynamo-agg-2xtp8 --overlay hicache-l2 --overlay l3-mooncake
probe:
	python -m tokiln.cli probe all --url $${URL:-http://localhost:8000/v1} --model $${MODEL:-glm52}
smoke:
	python -m tokiln.cli bench --workload smoke --arm A --url $${URL:-http://localhost:8000/v1}
bench-ab:
	python -m tokiln.cli bench --workload agentic-replay --arm A
	@echo ">>> 切换 router (glm52ta -> glm52 或改 profile) 后:"
	@echo "python -m tokiln.cli bench --workload agentic-replay --arm B"
monitor-serve:
	python -m tokiln.cli monitor serve --sglang $${SGLANG:-http://localhost:8000}
monitor-watch:
	python -m tokiln.cli monitor watch --monitor-url $${MON:-http://localhost:8100}
