from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from air.change_intelligence import compare_openapi
from air.dependency_impact import Dependency, ImpactError, analyze_changes, _validate_locations


LOCATION = '/paths/~1items/get/responses/200/content/application~1json/schema/properties/id'


def contract():
    return {'openapi': '3.1.0', 'info': {'title': 'Demo', 'version': '1'}, 'paths': {
        '/items': {'get': {'responses': {'200': {'content': {'application/json': {'schema': {
            'type': 'object', 'properties': {'id': {'type': 'string'}, 'identifier': {'type': 'string'}}}}}}}}},
        '/other': {'get': {'responses': {'200': {'description': 'OK'}}}}}}


def dep(**kwargs):
    return Dependency(**{'integration_id': 'billing', 'mapping_id': 'invoice-id',
                         'location': LOCATION, 'operation': 'GET /items', **kwargs})


def changed():
    old = contract()
    new = deepcopy(old)
    new['paths']['/items']['get']['responses']['200']['content']['application/json']['schema']['properties']['id']['type'] = 'integer'
    return compare_openapi(old, new)


def test_direct_schema_mapping_impact_is_explained():
    result = analyze_changes(changed(), [dep()]).to_dict()
    impact, = result['impacts']
    assert impact['classification'] == 'BREAKING'
    assert impact['match'] == 'LOCATION_OVERLAP'
    assert impact['change_location'] == LOCATION + '/type'
    assert impact['dependency']['integration_id'] == 'billing'
    assert impact['dependency']['mapping_id'] == 'invoice-id'
    assert impact['change_id'] and impact['impact_id'] and impact['reason']
    assert result['review_required'] and result['scope'] == 'explicit_registry_only'


@pytest.mark.parametrize('remove', ['path', 'operation'])
def test_removed_ancestor_impacts_registered_mapping(remove):
    old = contract()
    new = deepcopy(old)
    if remove == 'path':
        del new['paths']['/items']
    else:
        del new['paths']['/items']['get']
    result = analyze_changes(compare_openapi(old, new), [dep()]).to_dict()
    assert len(result['impacts']) == 1
    assert result['impacts'][0]['match'] == 'LOCATION_OVERLAP'


def test_operation_fallback_is_conservative_and_other_operations_are_excluded():
    result = analyze_changes(changed(), [dep(location=LOCATION[:-2] + 'identifier'),
        dep(integration_id='unrelated', operation='GET /other', location='/paths/~1other/get')]).to_dict()
    impact, = result['impacts']
    assert impact['match'] == 'OPERATION_REVIEW'
    assert impact['dependency']['integration_id'] == 'billing'


def test_pointer_matching_is_token_based():
    result = analyze_changes(changed(), [dep(operation=None, location=LOCATION + 'entifier')]).to_dict()
    # Similar text is not a direct pointer match; only the operation fallback applies.
    assert [i['match'] for i in result['impacts']] == ['OPERATION_REVIEW']
    assert result['review_required']
    old = contract()
    old['components'] = {'schemas': {'id': {'type': 'string'}, 'identifier': {'type': 'string'}}}
    new = deepcopy(old)
    new['components']['schemas']['id']['type'] = 'integer'
    report = analyze_changes(compare_openapi(old, new), [dep(operation=None,
        location='/components/schemas/identifier')]).to_dict()
    assert report['impacts'] == []
    assert report['review_required']  # Empty matching does not authorize deployment.


def test_order_deduplication_and_hash_are_deterministic():
    deps = [dep(), dep(integration_id='crm', integration_kind='adapter')]
    first = analyze_changes(changed(), deps)
    second = analyze_changes(changed(), [deps[1], deps[0], deps[1]])
    assert first == second and first.content_hash == second.content_hash
    assert len(first.to_dict()['impacts']) == 2
    mutated = first.to_dict()
    mutated['impacts'].clear()
    assert len(first.to_dict()['impacts']) == 2
    with pytest.raises(FrozenInstanceError):
        deps[0].mapping_id = 'changed'


def test_no_change_and_additive_change_do_not_report_impact():
    old = contract()
    for new in (deepcopy(old), {**old, 'paths': {**old['paths'], '/new': old['paths']['/other']}}):
        report = analyze_changes(compare_openapi(old, new), [dep()]).to_dict()
        assert report['impacts'] == [] and not report['review_required']


def test_global_security_change_requires_review_for_registered_consumers():
    old = contract()
    new = deepcopy(old)
    new['components'] = {'securitySchemes': {'token': {'type': 'http', 'scheme': 'bearer'}}}
    impacts = analyze_changes(compare_openapi(old, new), [dep()]).to_dict()['impacts']
    assert any(i['match'] == 'GLOBAL_SECURITY_REVIEW' and i['classification'] == 'SECURITY_RELEVANT' for i in impacts)


def test_unsupported_coverage_cannot_produce_safe_verdict():
    old = contract()
    old['paths']['/items']['get']['responses']['200']['content']['application/json']['schema']['allOf'] = [{'type': 'object'}]
    report = analyze_changes(compare_openapi(old, old), []).to_dict()
    assert report['coverage_warnings'] and report['review_required']


@pytest.mark.parametrize('kwargs', [dict(integration_id=''), dict(mapping_id='contains a secret'),
    dict(integration_kind='unknown'), dict(location='relative'), dict(location='/bad~2pointer'),
    dict(location='/bad\n'), dict(operation='get /items'), dict(operation='GET items'),
    dict(operation='GET /other'), dict(location='/paths/~1items/post'), dict(operation='GET /items\n')])
def test_malformed_dependency_rejected(kwargs):
    with pytest.raises(ImpactError):
        dep(**kwargs)


def test_dependency_and_comparison_limits(monkeypatch):
    import air.dependency_impact as module
    monkeypatch.setattr(module, 'MAX_DEPENDENCIES', 1)
    with pytest.raises(ImpactError, match='dependency_limit'):
        analyze_changes(changed(), [dep(), dep()])
    monkeypatch.setattr(module, 'MAX_COMPARISONS', 0)
    with pytest.raises(ImpactError, match='comparison_limit'):
        analyze_changes(changed(), [dep()])


def test_result_limit(monkeypatch):
    import air.dependency_impact as module
    monkeypatch.setattr(module, 'MAX_IMPACTS', 0)
    with pytest.raises(ImpactError, match='result_limit'):
        analyze_changes(changed(), [dep()])


def test_effective_locations_support_local_refs_and_inherited_parameters():
    old = contract()
    old['components'] = {'schemas': {'Id': {'type': 'string'}}}
    old['paths']['/items']['parameters'] = [{'name': 'X-Token', 'in': 'header', 'schema': {'type': 'string'}}]
    old['paths']['/items']['get']['responses']['200']['content']['application/json']['schema']['properties']['id'] = {'$ref': '#/components/schemas/Id'}
    _validate_locations(old, [dep().__dict__, dep(location=LOCATION + '/type').__dict__,
        dep(location='/paths/~1items/get/parameters/header/x-token/schema/type').__dict__])
    with pytest.raises(ImpactError, match='location_not_found'):
        _validate_locations(old, [dep(location=LOCATION + '/missing').__dict__])
    with pytest.raises(ImpactError, match='operation_not_found'):
        _validate_locations(old, [dep(operation='POST /items', location='/paths/~1items').__dict__])


def test_operation_inferred_for_selector_without_explicit_operation():
    result = analyze_changes(changed(), [dep(operation=None, location=LOCATION[:-2] + 'identifier')]).to_dict()
    assert result['impacts'][0]['match'] == 'OPERATION_REVIEW'


def test_required_property_affects_component_property_without_operation():
    old = contract()
    old['components'] = {'schemas': {'Item': {'type': 'object', 'properties': {'id': {'type': 'string'}}}}}
    new = deepcopy(old)
    new['components']['schemas']['Item']['required'] = ['id']
    report = analyze_changes(compare_openapi(old, new), [dep(operation=None,
        location='/components/schemas/Item/properties/id')]).to_dict()
    assert report['impacts'][0]['match'] == 'SCHEMA_REVIEW'


def test_enclosing_schema_type_change_affects_nested_field_without_operation():
    old = contract()
    old['components'] = {'schemas': {'Item': {'type': 'object', 'properties': {'id': {'type': 'string'}}}}}
    new = deepcopy(old)
    new['components']['schemas']['Item']['type'] = ['object', 'null']
    report = analyze_changes(compare_openapi(old, new), [dep(operation=None,
        location='/components/schemas/Item/properties/id')]).to_dict()
    assert report['impacts'][0]['match'] == 'SCHEMA_REVIEW'
