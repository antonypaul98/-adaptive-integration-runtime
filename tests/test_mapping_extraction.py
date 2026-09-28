from copy import deepcopy
from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from air.mapping_extraction import (MAPPING_VERSION, ExtractionError,
    extract_dependencies, normalize_mapping)

TENANT, SNAPSHOT = str(uuid4()), str(uuid4())


def manifest():
    return {'mapping_version': MAPPING_VERSION, 'tenant_id': TENANT,
        'snapshot_id': SNAPSHOT, 'adapter_id': 'billing', 'mappings': [
        {'mapping_id': 'fetch-items', 'method': 'GET', 'path': '/items', 'bindings': [
            {'binding_id': 'id', 'contract': {'kind': 'response_body', 'status': '200',
                'media_type': 'application/json', 'field': '/id'},
             'adapter_field': '/invoice/id', 'transform': 'identity'}]}]}


def test_simple_mapping_derives_operation_and_field_with_provenance():
    result = extract_dependencies(manifest(), TENANT)
    dependencies = result.to_dict()['dependencies']
    assert {d['location'] for d in dependencies} == {
        '/paths/~1items/get',
        '/paths/~1items/get/responses/200/content/application~1json/schema/properties/id'}
    assert all(d['integration_id'] == 'billing' and d['mapping_id'] == 'fetch-items'
        and d['operation'] == 'GET /items' and d['integration_kind'] == 'adapter' for d in dependencies)
    sources = [s for p in result.to_dict()['provenance'] for s in p['sources']]
    assert {s['manifest_location'] for s in sources} == {'/mappings/0', '/mappings/0/bindings/0'}
    assert {s['reason'] for s in sources} == {'registered_http_operation', 'contract_response_body_binding'}
    assert all(s['mapping_id'] == 'fetch-items' for s in sources)


def test_multiple_operations_mappings_and_adapters():
    value = manifest()
    value['mappings'] += [{'mapping_id': 'create', 'method': 'post', 'path': '/items', 'bindings': []},
                          {'mapping_id': 'read-other', 'method': 'GET', 'path': '/other', 'bindings': []}]
    result = extract_dependencies(value, TENANT)
    assert {d.operation for d in result.dependencies} == {'POST /items', 'GET /items', 'GET /other'}
    assert len(result.dependencies) == 4
    value['adapter_id'] = 'other'
    assert extract_dependencies(value, TENANT).content_hash != result.content_hash


def test_order_duplicates_casing_and_canonical_ownership():
    value = manifest()
    binding = deepcopy(value['mappings'][0]['bindings'][0]); binding['binding_id'] = 'other-copy'
    value['mappings'][0]['bindings'].append(binding)
    value['mappings'].append({'mapping_id': 'another', 'method': 'POST', 'path': '/items', 'bindings': []})
    reordered = deepcopy(value)
    reordered['mappings'].reverse()
    reordered['mappings'][1]['bindings'].reverse()
    reordered['mappings'].append(deepcopy(reordered['mappings'][1]))
    reordered['mappings'][1]['method'] = 'get'
    reordered['mappings'][1]['bindings'].append(deepcopy(binding))
    reordered['tenant_id'] = '{' + TENANT.upper() + '}'
    assert extract_dependencies(value, TENANT) == extract_dependencies(reordered, TENANT)
    result = extract_dependencies(value, TENANT)
    assert len(result.dependencies) == 3  # Two bindings to one field preserve both explanations.
    assert sorted(len(p['sources']) for p in result.to_dict()['provenance']) == [1, 1, 2]
    with pytest.raises(FrozenInstanceError):
        result.payload_json = '{}'
    modified = result.to_dict(); modified['dependencies'].clear()
    assert result.dependencies


@pytest.mark.parametrize('contract,expected', [
    ({'kind': 'request_body', 'media_type': 'application/json', 'field': '/outer/a~1b/~0key'},
     '/requestBody/content/application~1json/schema/properties/outer/properties/a~1b/properties/~0key'),
    ({'kind': 'parameter', 'in': 'header', 'name': 'X-Client'}, '/parameters/header/x-client'),
    ({'kind': 'parameter', 'in': 'query', 'name': 'a/b'}, '/parameters/query/a~1b'),
    ({'kind': 'response_body', 'status': 'default', 'media_type': 'application/json', 'field': ''},
     '/responses/default/content/application~1json/schema'),
])
def test_supported_bindings_and_escaped_fields(contract, expected):
    value = manifest(); value['mappings'][0]['bindings'][0]['contract'] = contract
    deps = extract_dependencies(value, TENANT).dependencies
    assert any(d.location == '/paths/~1items/get' + expected for d in deps)


@pytest.mark.parametrize('mutation', ['tenant_missing', 'tenant_other', 'tenant_nil', 'tenant_list',
    'snapshot_missing', 'snapshot_invalid', 'version', 'adapter_missing', 'adapter_invalid',
    'unknown_root', 'mapping_missing', 'mapping_unknown', 'mapping_tenant', 'mapping_not_list',
    'empty_mappings', 'bindings_not_list', 'binding_missing', 'binding_unknown',
    'unsupported_transform', 'unsupported_binding', 'invalid_pointer', 'bad_method', 'bad_path',
    'invalid_parameter', 'invalid_media', 'invalid_status'])
def test_malformed_unsupported_and_missing_ownership_fail_closed(mutation):
    value = manifest(); mapping = value['mappings'][0]; binding = mapping['bindings'][0]
    if mutation == 'tenant_missing': del value['tenant_id']
    elif mutation == 'tenant_other': value['tenant_id'] = str(uuid4())
    elif mutation == 'tenant_nil': value['tenant_id'] = str(UUID_ZERO)
    elif mutation == 'tenant_list': value['tenant_id'] = [TENANT]
    elif mutation == 'snapshot_missing': del value['snapshot_id']
    elif mutation == 'snapshot_invalid': value['snapshot_id'] = 'secret-not-a-uuid'
    elif mutation == 'version': value['mapping_version'] = 'unknown'
    elif mutation == 'adapter_missing': del value['adapter_id']
    elif mutation == 'adapter_invalid': value['adapter_id'] = 'contains secret'
    elif mutation == 'unknown_root': value['execute'] = 'untrusted-code'
    elif mutation == 'mapping_missing': del mapping['method']
    elif mutation == 'mapping_unknown': mapping['execute'] = 'untrusted-code'
    elif mutation == 'mapping_tenant': mapping['tenant_id'] = str(uuid4())
    elif mutation == 'mapping_not_list': value['mappings'] = {}
    elif mutation == 'empty_mappings': value['mappings'] = []
    elif mutation == 'bindings_not_list': mapping['bindings'] = {}
    elif mutation == 'binding_missing': del binding['contract']
    elif mutation == 'binding_unknown': binding['secret'] = 'sensitive'
    elif mutation == 'unsupported_transform': binding['transform'] = 'python:eval'
    elif mutation == 'unsupported_binding': binding['contract']['kind'] = 'dynamic'
    elif mutation == 'invalid_pointer': binding['adapter_field'] = '/bad~2pointer'
    elif mutation == 'bad_method': mapping['method'] = 'EXECUTE'
    elif mutation == 'bad_path': mapping['path'] = 'https://private.example'
    elif mutation == 'invalid_parameter': binding['contract'] = {'kind': 'parameter', 'in': 'elsewhere', 'name': 'x'}
    elif mutation == 'invalid_media': binding['contract']['media_type'] = 'application/json; secret'
    else: binding['contract']['status'] = '999'
    with pytest.raises(ExtractionError) as raised:
        extract_dependencies(value, TENANT)
    assert all(secret not in str(raised.value) for secret in ('sensitive', 'untrusted-code', 'private.example', 'secret-not'))


UUID_ZERO = '00000000-0000-0000-0000-000000000000'


@pytest.mark.parametrize('duplicate', ['mapping', 'binding'])
def test_conflicting_duplicate_identities_are_ambiguous(duplicate):
    value = manifest()
    if duplicate == 'mapping':
        other = deepcopy(value['mappings'][0]); other['path'] = '/different'
        value['mappings'].append(other)
    else:
        other = deepcopy(value['mappings'][0]['bindings'][0]); other['adapter_field'] = '/elsewhere'
        value['mappings'][0]['bindings'].append(other)
    with pytest.raises(ExtractionError, match='ambiguous'):
        extract_dependencies(value, TENANT)


@pytest.mark.parametrize('limit', ['MAX_MAPPINGS', 'MAX_BINDINGS'])
def test_extraction_work_limits(monkeypatch, limit):
    import air.mapping_extraction as module
    monkeypatch.setattr(module, limit, 0)
    with pytest.raises(ExtractionError, match='count_limit'):
        extract_dependencies(manifest(), TENANT)


def test_input_is_not_mutated_and_non_json_or_oversized_input_rejected():
    value = manifest(); original = deepcopy(value)
    normalize_mapping(value, TENANT)
    assert value == original
    for invalid in (float('nan'), 'x' * 1_048_576, object()):
        value = manifest(); value['adapter_id'] = invalid
        with pytest.raises(ExtractionError):
            extract_dependencies(value, TENANT)
