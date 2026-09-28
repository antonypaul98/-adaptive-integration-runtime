from copy import deepcopy
from dataclasses import FrozenInstanceError
import json

import pytest

from air.change_intelligence import Classification as C, ContractError, compare_openapi


def spec(schema=None, context='response'):
    schema = schema if schema is not None else {'type': 'object', 'properties': {'id': {'type': 'integer'}}}
    operation = {'responses': {'200': {'description': 'OK'}}}
    content = {'application/json': {'schema': schema}}
    if context == 'response':
        operation['responses']['200']['content'] = content
    else:
        operation['requestBody'] = {'content': content}
    return {'openapi': '3.1.0', 'info': {'title': 'Demo', 'version': '1'},
            'paths': {'/items': {'get': operation}}}


def op(doc):
    return doc['paths']['/items']['get']


def changes(old, new, code=None):
    found = compare_openapi(old, new).changes
    return [c for c in found if code is None or c.change_type == code]


def test_no_change_and_frozen_result():
    result = compare_openapi(spec(), spec())
    assert result.changes == () and not result.review_required
    assert result.previous_semantic_hash == result.new_semantic_hash
    with pytest.raises(FrozenInstanceError):
        result.version = 'mutated'


def test_object_order_and_annotations_are_irrelevant():
    old = spec()
    new = json.loads(json.dumps(old, sort_keys=True))
    new['info']['version'] = '2'
    op(new)['responses']['200']['description'] = 'different docs'
    result = compare_openapi(old, new)
    assert result.changes == ()
    assert result.previous_semantic_hash == result.new_semantic_hash


@pytest.mark.parametrize('code,mutate,classification', [
    ('PATH_ADDED', lambda d: d['paths'].update({'/extra': {'get': deepcopy(op(d))}}), C.NON_BREAKING),
    ('PATH_REMOVED', lambda d: d['paths'].clear(), C.BREAKING),
    ('OPERATION_ADDED', lambda d: d['paths']['/items'].update({'post': deepcopy(op(d))}), C.NON_BREAKING),
    ('OPERATION_REMOVED', lambda d: d['paths']['/items'].pop('get'), C.BREAKING),
    ('PARAMETER_ADDED', lambda d: op(d).update(parameters=[{'name': 'q', 'in': 'query'}]), C.NON_BREAKING),
    ('PARAMETER_ADDED', lambda d: op(d).update(parameters=[{'name': 'q', 'in': 'query', 'required': True}]), C.BREAKING),
    ('RESPONSE_STATUS_ADDED', lambda d: op(d)['responses'].update({'400': {'description': 'Bad'}}), C.REVIEW_REQUIRED),
])
def test_operations_and_parameters(code, mutate, classification):
    old, new = spec(), spec()
    mutate(new)
    found = changes(old, new, code)
    assert len(found) == 1 and found[0].classification == classification
    assert found[0].reason and found[0].change_id and found[0].location


def test_parameter_removal_requiredness_type_and_serialization():
    old = spec()
    op(old)['parameters'] = [{'name': 'q', 'in': 'query', 'schema': {'type': 'string'}}]
    new = deepcopy(old)
    op(new)['parameters'] = []
    assert changes(old, new, 'PARAMETER_REMOVED')[0].classification == C.BREAKING
    new = deepcopy(old)
    op(new)['parameters'][0].update(required=True, schema={'type': 'integer'}, style='simple')
    found = changes(old, new)
    assert {'PARAMETER_REQUIRED_CHANGED', 'TYPE_CHANGED', 'PARAMETER_SERIALIZATION_CHANGED'} <= {c.change_type for c in found}
    assert all(c.classification == C.BREAKING for c in found)
    assert changes(new, old, 'PARAMETER_REQUIRED_CHANGED')[0].classification == C.NON_BREAKING


def test_parameter_inheritance_override_and_order():
    old = spec()
    old['paths']['/items']['parameters'] = [{'name': 'a', 'in': 'query', 'required': True}]
    op(old)['parameters'] = [{'name': 'a', 'in': 'query', 'required': False}, {'name': 'b', 'in': 'query'}]
    new = deepcopy(old)
    new['paths']['/items']['parameters'][0]['required'] = False
    op(new)['parameters'].reverse()
    assert changes(old, new) == []


@pytest.mark.parametrize('context,a,b,expected', [
    ('request', 'integer', 'number', C.NON_BREAKING), ('response', 'integer', 'number', C.BREAKING),
    ('request', 'number', 'integer', C.BREAKING), ('response', 'number', 'integer', C.NON_BREAKING),
    ('request', 'string', 'integer', C.BREAKING), ('response', 'string', 'integer', C.BREAKING),
])
def test_directional_type_changes(context, a, b, expected):
    found = changes(spec({'type': a}, context), spec({'type': b}, context), 'TYPE_CHANGED')
    assert len(found) == 1 and found[0].classification == expected


@pytest.mark.parametrize('context,added,expected', [
    ('request', True, C.BREAKING), ('request', False, C.NON_BREAKING),
    ('response', True, C.NON_BREAKING), ('response', False, C.BREAKING),
])
def test_required_property_direction(context, added, expected):
    a = {'type': 'object', 'properties': {'id': {'type': 'integer'}}}
    b = {**a, 'required': ['id']}
    old, new = (a, b) if added else (b, a)
    found = changes(spec(old, context), spec(new, context))
    assert len(found) == 1 and found[0].classification == expected


@pytest.mark.parametrize('context,old_enum,new_enum,code,expected', [
    ('request', ['a', 'b'], ['a'], 'ENUM_VALUES_REMOVED', C.BREAKING),
    ('response', ['a', 'b'], ['a'], 'ENUM_VALUES_REMOVED', C.NON_BREAKING),
    ('request', ['a'], ['a', 'b'], 'ENUM_VALUES_ADDED', C.NON_BREAKING),
    ('response', ['a'], ['a', 'b'], 'ENUM_VALUES_ADDED', C.BREAKING),
])
def test_enum_variance(context, old_enum, new_enum, code, expected):
    found = changes(spec({'type': 'string', 'enum': old_enum}, context),
                    spec({'type': 'string', 'enum': new_enum}, context), code)
    assert len(found) == 1 and found[0].classification == expected


@pytest.mark.parametrize('context,old_schema,new_schema,expected', [
    ('request', {'type': 'string'}, {'type': ['string', 'null']}, C.NON_BREAKING),
    ('response', {'type': 'string'}, {'type': ['string', 'null']}, C.BREAKING),
    ('request', {'type': ['null', 'string']}, {'type': 'string'}, C.BREAKING),
    ('response', {'type': ['null', 'string']}, {'type': 'string'}, C.NON_BREAKING),
])
def test_nullable(context, old_schema, new_schema, expected):
    found = changes(spec(old_schema, context), spec(new_schema, context), 'NULLABILITY_CHANGED')
    assert len(found) == 1 and found[0].classification == expected


def test_openapi30_nullable_and_equivalent31_types():
    a, b = spec({'type': 'string'}, 'request'), spec({'type': 'string', 'nullable': True}, 'request')
    a['openapi'] = b['openapi'] = '3.0.3'
    assert changes(a, b, 'NULLABILITY_CHANGED')[0].classification == C.NON_BREAKING
    assert not changes(spec({'type': 'string', 'nullable': True}), spec({'type': ['null', 'string']}))


def test_property_add_remove_and_closed_objects():
    a = {'type': 'object', 'properties': {}, 'additionalProperties': False}
    b = {**a, 'properties': {'id': {'type': 'integer'}}}
    assert changes(spec(a, 'request'), spec(b, 'request'), 'PROPERTY_ADDED')[0].classification == C.NON_BREAKING
    assert changes(spec(b), spec(a), 'PROPERTY_REMOVED')[0].classification == C.BREAKING
    assert changes(spec(a), spec(b), 'PROPERTY_ADDED')[0].classification == C.BREAKING
    a.pop('additionalProperties')
    b.pop('additionalProperties')
    assert changes(spec(a), spec(b), 'PROPERTY_ADDED')[0].classification == C.NON_BREAKING


def test_request_body_requirement_and_response_status_removal():
    a, b = spec({}, 'request'), spec({}, 'request')
    op(b)['requestBody']['required'] = True
    assert changes(a, b, 'REQUEST_BODY_REQUIRED_CHANGED')[0].classification == C.BREAKING
    op(a)['responses']['400'] = {'description': 'Bad'}
    assert changes(a, b, 'RESPONSE_STATUS_REMOVED')[0].classification == C.BREAKING


def test_request_schema_deep_change_and_escaped_pointer():
    a = spec({'type': 'object', 'properties': {'a/b~c': {'type': 'string'}}}, 'request')
    b = spec({'type': 'object', 'properties': {'a/b~c': {'type': 'number'}}}, 'request')
    item = changes(a, b)[0]
    assert item.context == 'request' and item.operation == 'GET /items'
    assert '/paths/~1items/get/requestBody/content/application~1json/schema/properties/a~1b~0c/type' == item.location
    assert item.to_dict()['old_value'] == ['string']


def secured():
    d = spec()
    d['components'] = {'securitySchemes': {'auth': {'type': 'http', 'scheme': 'bearer'}}}
    d['security'] = [{'auth': []}]
    return d


def test_security_inheritance_and_override():
    a, b = secured(), secured()
    b['security'] = []
    found = changes(a, b)
    assert {c.change_type for c in found} == {'GLOBAL_SECURITY_CHANGED', 'OPERATION_SECURITY_CHANGED'}
    assert all(c.classification == C.SECURITY_RELEVANT for c in found)
    op(a)['security'] = op(b)['security'] = []
    assert len(changes(a, b)) == 1


@pytest.mark.parametrize('action,code', [('add', 'SECURITY_SCHEME_ADDED'), ('remove', 'SECURITY_SCHEME_REMOVED'), ('edit', 'SECURITY_SCHEME_CHANGED')])
def test_security_schemes(action, code):
    a, b = secured(), secured()
    schemes = b['components']['securitySchemes']
    if action == 'add':
        schemes['key'] = {'type': 'apiKey', 'in': 'header', 'name': 'X-API-Key'}
    elif action == 'remove':
        del schemes['auth']
    else:
        schemes['auth']['scheme'] = 'basic'
    assert changes(a, b, code)[0].classification == C.SECURITY_RELEVANT


def test_local_references_change_at_each_operation_and_provenance():
    a = spec({'$ref': '#/components/schemas/Item'})
    a['components'] = {'schemas': {'Item': {'type': 'string'}}}
    b = deepcopy(a)
    b['components']['schemas']['Item']['type'] = 'integer'
    result = compare_openapi(a, b)
    assert any(c.change_type == 'TYPE_CHANGED' and c.operation == 'GET /items' for c in result.changes)
    assert any(x['reference'] == '#/components/schemas/Item' for x in json.loads(result.references_json))


def test_recursive_and_external_references_are_bounded_and_reviewed():
    a = spec({'$ref': '#/components/schemas/Item'})
    a['components'] = {'schemas': {'Item': {'type': 'object', 'properties': {'child': {'$ref': '#/components/schemas/Item'}}}}}
    result = compare_openapi(a, deepcopy(a))
    assert not result.changes and result.review_required
    external = spec({'$ref': 'https://169.254.169.254/schema'})
    result = compare_openapi(external, external)
    assert not result.changes and result.review_required


def test_schema_literal_refs_and_metadata_property_names():
    a = spec({'type': 'object', 'properties': {'$ref': {'type': 'string'}, 'description': {'type': 'string'}}})
    b = deepcopy(a)
    schema = op(b)['responses']['200']['content']['application/json']['schema']
    schema['properties']['description']['type'] = 'number'
    result = compare_openapi(a, b)
    assert result.changes and result.previous_semantic_hash != result.new_semantic_hash
    literal = spec({'enum': [{'$ref': 'literal-value'}]})
    assert not compare_openapi(literal, literal).review_required


def test_unknown_schema_changes_never_claim_compatibility():
    a, b = spec({'type': 'string', 'pattern': '^a'}), spec({'type': 'string', 'pattern': '^b'})
    assert changes(a, b)[0].classification == C.REVIEW_REQUIRED
    a = spec({'allOf': [{'type': 'string'}, {'minLength': 1}]})
    assert compare_openapi(a, a).review_required


def test_deterministic_ordering_set_semantics_and_hash():
    a = spec({'type': 'object', 'required': ['a', 'b'], 'properties': {'a': {'enum': [1, 2]}, 'b': {'type': 'string'}}})
    b = deepcopy(a)
    schema = op(b)['responses']['200']['content']['application/json']['schema']
    schema['required'].reverse()
    schema['properties']['a']['enum'].reverse()
    assert changes(a, b) == []
    del schema['properties']['b']
    first = compare_openapi(a, b)
    second = compare_openapi(json.loads(json.dumps(a, sort_keys=True)), json.loads(json.dumps(b, sort_keys=True)))
    assert first.to_dict() == second.to_dict() and first.content_hash == second.content_hash
    assert list(first.changes) == sorted(first.changes, key=lambda c: (c.location, c.operation or '', c.change_type, c.change_id))


@pytest.mark.parametrize('schema', [{'type': 'bad'}, {'type': []}, {'required': True}, {'properties': []},
    {'properties': {'x': 'bad'}}, {'enum': []}, {'nullable': 'true'}, {'minLength': -1},
    {'minimum': True}, {'items': []}, {'oneOf': []}])
def test_malformed_schemas_even_when_contracts_identical(schema):
    with pytest.raises(ContractError):
        compare_openapi(spec(schema), spec(schema))


@pytest.mark.parametrize('bad', [{}, {'openapi': '2.0', 'info': {}, 'paths': {}},
    {'openapi': '3.2.0', 'info': {}, 'paths': {}}, {'openapi': '3.1.0', 'info': {}, 'paths': []}])
def test_unsupported_or_malformed_contracts(bad):
    with pytest.raises(ContractError):
        compare_openapi(bad, spec())


def test_invalid_parameter_and_missing_ref():
    a = spec()
    op(a)['parameters'] = [{'name': 'a', 'in': 'query'}, {'name': 'a', 'in': 'query'}]
    with pytest.raises(ContractError, match='duplicate_parameter'):
        compare_openapi(a, a)
    a = spec({'$ref': '#/components/schemas/Missing'})
    with pytest.raises(ContractError, match='unresolved_local_reference'):
        compare_openapi(a, a)


def test_enum_objects_preserve_literal_array_order_and_boolean_number_identity():
    old = spec({'enum': [{'required': ['a', 'b']}, True]})
    new = spec({'enum': [{'required': ['b', 'a']}, 1]})
    result = changes(old, new)
    assert {c.change_type for c in result} == {'ENUM_VALUES_ADDED', 'ENUM_VALUES_REMOVED'}
    assert len(json.loads(result[0].old_json) if result[0].old_present else json.loads(result[0].new_json)) == 2


@pytest.mark.parametrize('context,key,a,b,expected', [
    ('request', 'minLength', 1, 2, C.BREAKING), ('response', 'minLength', 1, 2, C.NON_BREAKING),
    ('request', 'maximum', 10, 20, C.NON_BREAKING), ('response', 'maximum', 10, 20, C.BREAKING),
    ('request', 'maxItems', 10, 5, C.BREAKING), ('response', 'maxItems', 10, 5, C.NON_BREAKING),
])
def test_bounds_are_directional(context, key, a, b, expected):
    found = changes(spec({key: a}, context), spec({key: b}, context), 'SCHEMA_BOUND_CHANGED')
    assert len(found) == 1 and found[0].classification == expected


def test_composition_order_and_unknown_semantics():
    a = spec({'allOf': [{'type': 'string'}, {'minLength': 1}]})
    b = spec({'allOf': [{'minLength': 1}, {'type': 'string'}]})
    assert not changes(a, b)
    assert compare_openapi(a, b).review_required


def test_added_paths_with_bad_schemas_are_rejected():
    a = spec()
    b = spec({'type': 'not-a-type'})
    b['paths']['/new'] = b['paths'].pop('/items')
    with pytest.raises(ContractError):
        compare_openapi(a, b)


@pytest.mark.parametrize('external', [False, True])
def test_reference_fanout_has_a_byte_budget_not_only_a_node_budget(external):
    document = spec({'$ref': '#/components/schemas/Huge'})
    document['components'] = {'schemas': {'Huge': ({'$ref': 'https://example.com/' + 'x' * 80_000}
        if external else {'type': 'string', 'enum': ['x' * 80_000]})}}
    document['paths'] = {f'/item{i}': deepcopy(document['paths']['/items']) for i in range(60)}
    with pytest.raises(ContractError, match='reference_expansion_limit'):
        compare_openapi(document, document)


def test_redundant_integer_union_and_cross_version_boolean_schema():
    assert not changes(spec({'type': 'number'}), spec({'type': ['integer', 'number']}))
    old, new = spec({}), spec(True)
    old['openapi'] = '3.0.3'
    assert any(c.classification == C.REVIEW_REQUIRED for c in changes(old, new))
