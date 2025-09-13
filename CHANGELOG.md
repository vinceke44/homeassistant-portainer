# Changelog

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
  - `tests/test_api.py` – API 200 JSON path.
  - `tests/test_control_api.py` – stack/container action URLs & 204 handling.
  - `tests/test_coordinator_utils.py` – containers_by_name index.
  - `tests/test_switch.py` – rename fallback, stack ON semantics.
  - `tests/test_sensor.py` – stack container counts.
  - `tests/test_sensor_naming.py` – compact naming, rename stability, device vs entity naming.
  - `tests/test_sensor_name_mode.py` – option-driven naming modes.

### Changed
- Switches and sensors refresh twice after start/stop to reflect Portainer’s re-creation of containers.
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
