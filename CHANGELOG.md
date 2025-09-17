# Changelog
v1.2.0 — CPU & Memory stats for containers (2025‑09‑17)

Added
	•	Per‑container CPU Usage (%)
	•	Formula: ((cpu_delta / system_delta) * online_cpus * 100)
	•	Device class: power_factor, state class: measurement, unit: %.
	•	Icon: mdi:cpu-64-bit (from sensor_types.py).
	•	Entity naming honors container_sensor_name_mode (service | container | stack/service).
	•	Per‑container Memory Used (MiB)
	•	Device class: data_size, state class: measurement, unit: MiB.
	•	Optional cache exclusion via CONF_MEM_EXCLUDE_CACHE.
	•	Icon: mdi:memory (from sensor_types.py).
	•	Per‑container Memory Usage (%)
	•	Device class: power_factor, state class: measurement, unit: %.

Options
	•	Stats polling: CONF_STATS_SCAN_INTERVAL (default from const.py).
	•	CPU smoothing: CONF_STATS_SMOOTHING_ALPHA (EWMA; set 0 to disable).
	•	Memory cache exclusion: CONF_MEM_EXCLUDE_CACHE (true/false).

Fixed
	•	Stack container sensors reliably restore after HA restart.
	•	Update path now only skips entities already active on the platform, so restored registry entries are correctly re‑instantiated.
	•	Fallback synthesis of stacks from Compose labels when Portainer /stacks is empty.
	•	Stack sensors enabled by default.

Changed
	•	Stats sensors now use icons defined in sensor_types.py for consistency.

Performance
	•	Introduced a lightweight per‑container StatsCoordinator
	•	Shared by CPU%, Mem (MiB), Mem% sensors for the same container.
	•	Non‑blocking startup: base entities added first; stats refresh scheduled asynchronously.

## [1.1.0]
### Added
- **Stacks** support:
  - Fetch from `/api/stacks` into `raw_data["stacks"]`.
  - **Stack switch** entities (`PortainerStackSwitch`) using proper start/stop endpoints:
    - `POST /api/stacks/{stack_id}/start?endpointId={endpoint_id}`
    - `POST /api/stacks/{stack_id}/stop?endpointId={endpoint_id}`
  - **Stack Containers sensor** reporting `running/total` with attrs (running, total, stopped).

- **Hierarchical devices**:
  - **Endpoint ? Stack ? Container** device graph.
  - Containers under their Stack device when Compose labels exist; otherwise under Endpoint.

- **Stable-by-name container entities**:
  - Coordinator builds `raw_data["containers_by_name"]` keyed as `"<EndpointId>:<ContainerName>"`.
  - Container switches/sensors resolve the current container by name, with **Compose fallback** (stack+service) to survive container re-creation/rename.

- **Container sensor naming option**:
  - New option: `container_sensor_name_mode` with values:
    - `service` (default): `CPU: web`
    - `container`: `CPU: my_container`
    - `stack_service`: `CPU: myapp/web`
  - Configurable via **Integration ? Portainer ? Configure**.

- **Test suite** (pytest + HA plugin):
  - `tests/test_api.py` � API 200 JSON path.
  - `tests/test_control_api.py` � stack/container action URLs & 204 handling.
  - `tests/test_coordinator_utils.py` � containers_by_name index.
  - `tests/test_switch.py` � rename fallback, stack ON semantics.
  - `tests/test_sensor.py` � stack container counts.
  - `tests/test_sensor_naming.py` � compact naming, rename stability, device vs entity naming.
  - `tests/test_sensor_name_mode.py` � option-driven naming modes.

### Changed
- Switches and sensors refresh twice after start/stop to reflect Portainer�s re-creation of containers.
- Sensor entity names are **compact by default** (prefer Compose service), while **device names** remain descriptive (e.g., `Container: stack/service`).

### Fixed
- Control API now uses the correct Stack endpoints and treats `204/304` as success.

### Breaking Changes
- Container entities are now **stable-by-name** rather than by container ID.  
  If you referenced the old (ID-based) entity IDs, you may need to re-link them in dashboards/automations.

### Migration
1. Open **Settings ? Devices & Services ? Portainer** and confirm entities are present under the new **Endpoint ? Stack ? Container** hierarchy.
2. If any dashboards/automations reference old entity IDs, update them to the new name-stable ones.
3. (Optional) Adjust **Container sensor name mode** under **Configure**:
   - `service` (recommended) keeps entities compact (e.g., `CPU: web`).
   - `container` uses container name.
   - `stack_service` uses `stack/service`.

---
## [1.0.3]
 container control actions and container switch for start/stop

## [1.0.2] - Previous
- Containers & endpoints, basic switches and sensors.
