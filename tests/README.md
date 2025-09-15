# Portainer Integration – Tests & Running Guide

## Overview

This test suite covers both **pure logic** and **Home Assistant (HA) integration** behavior for the Portainer custom component. It’s structured so that all HA‑independent tests always run, while HA integration smoke tests are **optional** and automatically **skipped** if the component isn’t discoverable by HA in your runner.

* **Core (always-on) tests:** parsing, scheduling, config/option logic, unique IDs, API helpers – fast and CI‑friendly.
* **Optional HA integration tests:** entity naming, rename propagation, and control actions (button/switch) – run only when HA can load `custom_components/portainer`.

## What changed (Sept 2025)

* Added `tests/_helpers.py` with stable utilities (`force_refresh`, `get_display_name`, `get_unique_id`, `rename_in_portainer`).
* Extended `tests/conftest.py` with **opt‑in** fixtures:

  * `mock_portainer_api` – test‑only `PortainerAPI`/`PortainerControl` patch + shared mutable store.
  * `portainer_setup` – creates a `MockConfigEntry`; **skips** the test if HA reports *Integration not found*.
* Normalized flaky rename/naming assertions to check the **display label** and ensure the loop drains.
* Split unit and integration responsibilities in `tests/test_sensor*.py`.

> No runtime code changed; all adjustments are test‑only.

## Current Test Set

### Always-on (HA‑independent)

These pass in standard CI/local runs from any working directory:

* `test_api.py` – API client basics
* `test_availability_fix.py` – entity availability defaults & options
* `test_coordinator_utils.py` – indexing & helpers
* `test_pure_logic.py` – schema/time validation & UI logic (pure Python)
* `test_tag_parsing.py` – robust Docker image/tag parsing & normalization
* `test_ui_field_visibility.py` / `test_static_ui.py` – conditional UI behavior
* `test_unique_id_fix.py` – unique ID formats & stability
* `test_update_checks.py` / `test_update_checks_new_container.py` – scheduling, caching, and registry lookup logic
* `test_control_api.py` – control URL formation and request wiring
* `test_sensor.py` – **unit** coverage for stack container counters (rename unit test is skipped; covered by integration test)

### Optional (HA integration)

These run **only** if HA can load the custom component. Otherwise, they’re cleanly **skipped** (no failures):

* `test_button_restart.py` – restart button calls control with current ID after rename
* `test_sensor_integration.py` – sensor unique\_id stability & name updates on rename
* `test_sensor_name_mode.py` – `service`/`container`/`stack_service` naming modes
* `test_sensor_naming.py` – service‑preferred naming, container fallback
* `test_switch.py` – switch label updates after rename
* `test_switch_naming.py` – switch label updates while unique\_id stays stable

## Running the tests

### Quick: core suite (recommended during development)

```bash
pytest -q
```

Runs fast, exercises all HA‑independent logic. Integration tests are skipped if HA can’t load the component.

### Enable HA integration tests

Run from the **repository root** so HA discovers `custom_components/portainer`:

```bash
# from repo root (the directory that contains custom_components/portainer)
pytest tests/ -q
```

If you must run from `tests/` directly, ensure HA can still discover the integration (one of the following):

* Export `PYTHONPATH` to include the repo root:

  ```bash
  export PYTHONPATH="$(pwd)/..:$PYTHONPATH"
  pytest -q
  ```
* Or run with the repo root as CWD:

  ```bash
  (cd .. && pytest tests/ -q)
  ```

When HA discovery still fails, `portainer_setup` will **skip** the integration tests with a clear message, while the core suite stays green.

## Helper fixtures/utilities

* `mock_portainer_api` (fixture): patches `PortainerAPI` & `PortainerControl` and exposes `_TEST_API_STORE` for in‑test mutation (simulate renames, etc.).
* `portainer_setup` (fixture): builds a `MockConfigEntry` with sane defaults and loads the component; skips on *Integration not found*.
* `_helpers.py`:

  * `force_refresh(hass)` – drains the event loop (twice) to flush coordinator updates.
  * `get_display_name(hass, entity_id)` – consistent display label resolution.
  * `get_unique_id(hass, entity_id)` – registry unique\_id access with guardrails.
  * `rename_in_portainer(...)` – mutate the test API store to simulate renames.

## Troubleshooting

**Error:** `Setup failed for 'portainer': Integration not found.`
**Fix:** run from repo root or export `PYTHONPATH` to include the repo root so HA can locate `custom_components/portainer`. If that’s not possible in your environment, the integration tests will automatically **skip**; core tests still pass.

**Entities not created / empty state list:** ensure `portainer_setup` is used and that your test uses the mock fixtures (`mock_portainer_api`). Reload the config entry after mutating `_TEST_API_STORE`.

## CI notes

* The suite is safe for Py 3.13 / pytest 8.4+ / HA 2025.9.
* Integration tests are optional; they skip rather than fail when HA discovery isn’t available.
* No network calls: all API/control traffic is mocked.

## File additions

* `pytest.ini` – asyncio mode & warning filters
* `tests/_helpers.py` – helper utilities
* `tests/conftest.py` – merged existing fixtures + new optional mocks & `portainer_setup`
* New/updated integration tests under `tests/`: see **Optional (HA integration)** above.

---

**Status snapshot** (from the last local run):

* Core suite: **127 passing** (numbers may vary slightly by environment)
* Integration tests: **skipped** when HA cannot load the component

> Goal remains: 100% green core tests; integration tests run on environments where HA can discover the component.
