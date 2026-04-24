# Kubernetes Nova Driver Testing

This document describes how to run unit tests for the Kubernetes Nova driver.

## Test Files

The Kubernetes driver tests are located at:
- `nova/tests/unit/virt/kubernetes/test_driver.py` - Driver tests (19 test cases)
- `nova/tests/unit/virt/kubernetes/test_crd_os_instance.py` - CRD tests (5 test cases)

## Running Tests with Docker (Recommended)

The OpenStack 2023.2 dependencies require Python 3.10 and specific package versions that don't build on modern macOS/Python 3.12+. Use Docker with the same base image as the deployed nova-compute.

### Prerequisites

- Docker installed and running
- Access to `keppel.eu-de-1.cloud.sap/ccloud/loci-nova:bobcat-latest` (or set `BASE_IMAGE`)

### Run All Kubernetes Driver Tests

```bash
cd deploy
./run-tests.sh
```

### Run Specific Tests

```bash
# Run only driver tests
./run-tests.sh nova.tests.unit.virt.kubernetes.test_driver

# Run only CRD tests
./run-tests.sh nova.tests.unit.virt.kubernetes.test_crd_os_instance

# Run a specific test case
./run-tests.sh nova.tests.unit.virt.kubernetes.test_driver.KubernetesTestCase.test_spawn
```

### Use a Different Base Image

```bash
BASE_IMAGE=my-registry/nova:latest ./run-tests.sh
```

## Running Tests with tox (Local Python)

> **Note:** This requires Python 3.10 and may fail on macOS with newer Python versions due to dependency build issues (PyYAML 6.0, Cython compatibility).

### Prerequisites

Install tox if not already installed:
```bash
pip install tox
```

### Run All Kubernetes Driver Tests

```bash
tox -e py3 -- nova.tests.unit.virt.kubernetes
```

### Run Only Driver Tests

```bash
tox -e py3 -- nova.tests.unit.virt.kubernetes.test_driver
```

### Run Only CRD Tests

```bash
tox -e py3 -- nova.tests.unit.virt.kubernetes.test_crd_os_instance
```

### Run a Specific Test Case

```bash
tox -e py3 -- nova.tests.unit.virt.kubernetes.test_driver.KubernetesTestCase.test_spawn
```

## Test Coverage

### Driver Tests (`test_driver.py`)

| Test | Description |
|------|-------------|
| `test_init_host` | Driver initialization |
| `test_get_host_uptime` | Host uptime reporting |
| `test_get_info` | Instance information retrieval |
| `test_spawn` | Instance creation |
| `test_instance_exist` | Instance existence checking |
| `test_list_instances` | Listing instance names |
| `test_list_instance_uuids` | Listing instance UUIDs |
| `test_destroy_instance` | Instance deletion |
| `test_reboot` | Instance reboot |
| `test_pause` | Instance pause |
| `test_unpause` | Instance unpause |
| `test_power_off` | Power off operation |
| `test_power_on` | Power on operation |
| `test_suspend` | Instance suspension |
| `test_resume` | Instance resumption |
| `test_get_nodenames_by_uuid` | Node UUID to name mapping |
| `test_get_available_nodes` | Available nodes retrieval |
| `test_get_available_resources` | Resource availability info |
| `test_update_provider_tree` | Provider tree updates |

### CRD Tests (`test_crd_os_instance.py`)

| Test | Description |
|------|-------------|
| `test_crd_os_instance_manifest` | CRD manifest creation |
| `test_crd_instance_create` | CRD instance creation |
| `test_crd_instance_get` | CRD instance retrieval |
| `test_crd_instance_list` | CRD instance listing |
| `test_crd_instance_patch` | CRD instance patching |

## Troubleshooting

### Docker: Image pull fails

Ensure you're authenticated to the SAP container registry:
```bash
docker login keppel.eu-de-1.cloud.sap
```

### tox: PyYAML build fails

This is expected on Python 3.12+. Use the Docker approach instead.

### Tests hang

Set a timeout:
```bash
# Docker
docker run --rm -e OS_TEST_TIMEOUT=300 ...

# tox
OS_TEST_TIMEOUT=300 tox -e py3 -- nova.tests.unit.virt.kubernetes
```
