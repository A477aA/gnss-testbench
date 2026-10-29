.PHONY: install lint test integration acceptance report serve clean

install:            ## установить с зависимостями для разработки
	pip install -e ".[dev]"

lint:               ## ruff + mypy + shellcheck
	ruff check .
	mypy
	shellcheck scripts/*.sh

test:               ## unit + property + integration
	pytest --cov

integration:        ## только сквозные тесты через виртуальный порт
	pytest -m integration -v

acceptance:         ## все сценарии с ожидаемыми вердиктами
	scripts/acceptance.sh scenarios/open_sky_rtk.toml   criteria/rtk_static.toml        pass
	scripts/acceptance.sh scenarios/noisy_serial.toml   criteria/serial_robustness.toml pass
	scripts/acceptance.sh scenarios/urban_canyon.toml   criteria/rtk_static.toml        fail
	scripts/acceptance.sh scenarios/tunnel_dropout.toml criteria/rtk_static.toml        fail

serve:              ## виртуальный приёмник в pty — подключайся picocom'ом
	gnss-testbench serve scenarios/open_sky_rtk.toml

clean:
	rm -rf reports logs/*/ .pytest_cache .mypy_cache .ruff_cache .coverage coverage.xml report*.xml
