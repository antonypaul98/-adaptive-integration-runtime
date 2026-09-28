"""Deterministic, conservative OpenAPI 3.0/3.1 client-compatibility analysis.

Request acceptance is contravariant; response guarantees are covariant. This is
an explicit supported subset, never a claim of general JSON Schema subsumption.
Unknown behavior yields REVIEW_REQUIRED and coverage warnings, not a safe verdict.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Any

from air.observer import ObservationError, parse_contract
from air.postgres import canonical_json

DETECTOR_VERSION = 'air-openapi-diff-v1'
MAX_CHANGES = 2000
MAX_EXPANDED_BYTES = 4_194_304
METHODS = frozenset(('get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace'))
ANNOTATIONS = frozenset(('description', 'summary', 'title', 'example', 'examples',
                        'externalDocs', 'tags'))
SCHEMA_KEYS = frozenset(('type', 'enum', 'nullable', 'properties', 'required', 'items',
    'additionalProperties', 'minimum', 'maximum', 'minLength', 'maxLength',
    'minItems', 'maxItems', 'minProperties', 'maxProperties', 'readOnly', 'writeOnly'))
MAP_KEYS = frozenset(('properties', 'schemas', 'securitySchemes', 'paths', 'responses',
                      'headers', 'content', 'links', 'callbacks', 'variables', 'parameters', 'requestBodies'))
MISSING = object()


class ContractError(ValueError):
    """Fixed diagnostic codes: no raw contract or secrets in exception messages."""


class Classification(str, Enum):
    NON_BREAKING = 'NON_BREAKING'
    BREAKING = 'BREAKING'
    SECURITY_RELEVANT = 'SECURITY_RELEVANT'
    REVIEW_REQUIRED = 'REVIEW_REQUIRED'


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False)


def _hash(value: Any) -> str:
    return sha256(_json(value).encode('utf-8')).hexdigest()


def pointer(base: str, token: str) -> str:
    return base + '/' + token.replace('~', '~0').replace('/', '~1')


def _normalize(value: Any, key: str = '', *, literal=False, mapping=False) -> Any:
    if isinstance(value, dict):
        return {k: _normalize(v, k, literal=literal or (not mapping and k in
                    ('const', 'default', 'example', 'examples')),
                    mapping=not mapping and k in MAP_KEYS)
                for k, v in sorted(value.items())}
    if isinstance(value, list):
        result = [_normalize(item, literal=literal or key == 'enum') for item in value]
        if not literal and key in ('required', 'enum', 'type', 'allOf', 'anyOf', 'oneOf'):
            result = sorted({_json(item): item for item in result}.values(), key=_json)
        return result
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


@dataclass(frozen=True)
class Change:
    change_id: str
    location: str
    operation: str | None
    change_type: str
    context: str
    classification: Classification
    reason: str
    old_present: bool
    new_present: bool
    old_json: str
    new_json: str

    def to_dict(self) -> dict[str, Any]:
        return {**{name: getattr(self, name) for name in (
            'change_id', 'location', 'operation', 'change_type', 'context',
            'classification', 'reason', 'old_present', 'new_present')},
            'old_value': json.loads(self.old_json), 'new_value': json.loads(self.new_json)}


@dataclass(frozen=True)
class ChangeSet:
    changes: tuple[Change, ...]
    warnings_json: str
    references_json: str
    previous_semantic_hash: str
    new_semantic_hash: str
    version: str = DETECTOR_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {'detector_version': self.version,
                'previous_semantic_hash': self.previous_semantic_hash,
                'new_semantic_hash': self.new_semantic_hash,
                'changes': [c.to_dict() for c in self.changes],
                'coverage_warnings': json.loads(self.warnings_json),
                'reference_provenance': json.loads(self.references_json)}

    @property
    def content_hash(self) -> str:
        return _hash(self.to_dict())

    @property
    def review_required(self) -> bool:
        return bool(json.loads(self.warnings_json)) or any(
            c.classification != Classification.NON_BREAKING for c in self.changes)


class _Document:
    def __init__(self, contract: dict[str, Any], side: str):
        try:
            # Reuse existing input bounds/duplicate/nonfinite/depth validation, without I/O.
            self.raw = parse_contract(canonical_json(contract).encode('utf-8'))
        except (ValueError, TypeError, RecursionError, ObservationError):
            raise ContractError('invalid_contract') from None
        if not re.fullmatch(r'3\.[01]\.\d+', str(self.raw.get('openapi', ''))):
            raise ContractError('unsupported_openapi_version')
        self.side, self.warnings, self.references, self.nodes = side, [], [], 0
        self.expanded_bytes = 0
        self.value = _normalize(self.expand(self.raw, '', (), 0))
        self.validate()

    def warn(self, location: str, reason: str):
        self.warnings.append({'snapshot': self.side, 'location': location, 'reason': reason})

    def charge(self, value):
        self.expanded_bytes += len(_json(value).encode('utf-8'))
        if self.expanded_bytes > MAX_EXPANDED_BYTES:
            raise ContractError('reference_expansion_limit')
        return value

    def expand(self, value: Any, location: str, stack: tuple, depth: int, mapping=False) -> Any:
        self.nodes += 1
        self.expanded_bytes += 2
        if depth > 80 or self.nodes > 100_000:
            raise ContractError('reference_expansion_limit')
        if isinstance(value, dict):
            for key in value:
                self.charge(key)
            if '$ref' in value and not mapping:
                ref = value['$ref']
                if not isinstance(ref, str):
                    raise ContractError('invalid_reference')
                if not ref.startswith('#/'):
                    self.warn(location, 'external_or_anchor_reference_not_resolved')
                    return _normalize(value)
                if ref in stack:
                    self.warn(location, 'recursive_reference_requires_review')
                    return _normalize(value)
                if set(value) - {'$ref'} - ANNOTATIONS:
                    self.warn(location, 'reference_sibling_semantics_not_supported')
                    return _normalize(value)
                target = self.raw
                try:
                    for token in ref[2:].split('/'):
                        if re.search(r'~(?![01])', token):
                            raise ValueError()
                        token = token.replace('~1', '/').replace('~0', '~')
                        target = target[int(token)] if isinstance(target, list) else target[token]
                except (KeyError, TypeError, ValueError, IndexError):
                    raise ContractError('unresolved_local_reference') from None
                self.references.append({'snapshot': self.side, 'location': location, 'reference': ref})
                return self.expand(target, location, stack + (ref,), depth + 1)
            return {key: (_normalize(self.charge(item), literal=True) if not mapping and key in
                        ANNOTATIONS | {'enum', 'const', 'default'} else
                        self.expand(item, pointer(location, key), stack, depth + 1,
                                    mapping=not mapping and key in MAP_KEYS))
                    for key, item in sorted(value.items())}
        if isinstance(value, list):
            return [self.expand(item, pointer(location, str(i)), stack, depth + 1)
                    for i, item in enumerate(value)]
        return self.charge(value)

    def validate(self):
        doc = self.value
        if not isinstance(doc.get('paths'), dict) or not isinstance(doc.get('info'), dict):
            raise ContractError('invalid_openapi_structure')
        if not isinstance(doc.get('components', {}), dict):
            raise ContractError('invalid_components')
        _security(doc.get('security', []))
        def content_schemas(container):
            _body(container)
            for media in container.get('content', {}).values():
                _schema_shape(media.get('schema', {}), self.raw['openapi'])
        def parameter_schemas(parameters):
            for parameter in _parameters(parameters).values():
                _schema_shape(parameter.get('schema', {}), self.raw['openapi'])
                content_schemas(parameter)

        for path, item in doc['paths'].items():
            if not path.startswith('/') or not isinstance(item, dict):
                raise ContractError('invalid_path_item')
            parameter_schemas(item.get('parameters', []))
            for method in METHODS & item.keys():
                operation = item[method]
                if not isinstance(operation, dict):
                    raise ContractError('invalid_operation')
                parameter_schemas(operation.get('parameters', []))
                if 'security' in operation:
                    _security(operation['security'])
                if 'requestBody' in operation:
                    content_schemas(operation['requestBody'])
                responses = operation.get('responses')
                if not isinstance(responses, dict) or not responses:
                    raise ContractError('missing_operation_responses')
                for status, response in responses.items():
                    if not re.fullmatch(r'(?:[1-5][0-9]{2}|[1-5]XX|default)', status):
                        raise ContractError('invalid_response_status')
                    content_schemas(response)
        for field in ('schemas', 'securitySchemes'):
            if not isinstance(doc.get('components', {}).get(field, {}), dict):
                raise ContractError('invalid_components')
        for schema in doc.get('components', {}).get('schemas', {}).values():
            _schema_shape(schema, self.raw['openapi'])
        for scheme in doc.get('components', {}).get('securitySchemes', {}).values():
            if not isinstance(scheme, dict) or (scheme.get('type') not in
                    ('apiKey', 'http', 'oauth2', 'openIdConnect', 'mutualTLS') and '$ref' not in scheme):
                raise ContractError('invalid_security_scheme')


def _security(value: Any) -> list:
    if not isinstance(value, list):
        raise ContractError('invalid_security_requirement')
    result = []
    for requirement in value:
        if not isinstance(requirement, dict):
            raise ContractError('invalid_security_requirement')
        item = {}
        for name, scopes in requirement.items():
            if not isinstance(scopes, list) or any(not isinstance(s, str) for s in scopes):
                raise ContractError('invalid_security_scopes')
            item[name] = sorted(set(scopes))
        result.append(item)
    return sorted({_json(item): item for item in result}.values(), key=_json)


def _parameters(value: Any) -> dict:
    if not isinstance(value, list):
        raise ContractError('invalid_parameters')
    result = {}
    for parameter in value:
        if not isinstance(parameter, dict):
            raise ContractError('invalid_parameter')
        if '$ref' in parameter:
            # Unresolved external/cyclic refs remain explicit review-only entries.
            identity = ('$ref', parameter['$ref'])
        else:
            name, where = parameter.get('name'), parameter.get('in')
            if not isinstance(name, str) or not name or where not in ('path', 'query', 'header', 'cookie'):
                raise ContractError('invalid_parameter_identity')
            if type(parameter.get('required', False)) is not bool:
                raise ContractError('invalid_parameter_required')
            if where == 'path' and parameter.get('required') is not True:
                raise ContractError('path_parameter_must_be_required')
            if 'schema' in parameter and 'content' in parameter:
                raise ContractError('parameter_schema_content_conflict')
            identity = (where, name.lower() if where == 'header' else name)
        if identity in result:
            raise ContractError('duplicate_parameter')
        result[identity] = parameter
    return result


def _body(value: Any):
    if not isinstance(value, dict):
        raise ContractError('invalid_body_or_response')
    if type(value.get('required', False)) is not bool:
        raise ContractError('invalid_body_required')
    content = value.get('content', {})
    if not isinstance(content, dict) or any(not isinstance(media, dict) for media in content.values()):
        raise ContractError('invalid_content')


class _Engine:
    def __init__(self, previous: _Document, current: _Document):
        self.previous, self.current = previous, current
        self.changes = []
        self.warnings = previous.warnings + current.warnings

    def emit(self, code, location, operation, context, old, new, classification, reason):
        if len(self.changes) >= MAX_CHANGES:
            raise ContractError('change_count_limit')
        payload = {'location': location, 'operation': operation, 'change_type': code,
            'context': context, 'classification': classification, 'reason': reason,
            'old_present': old is not MISSING, 'new_present': new is not MISSING,
            'old_value': None if old is MISSING else old,
            'new_value': None if new is MISSING else new}
        self.changes.append(Change(_hash(payload), location, operation, code, context,
            Classification(classification), reason, payload['old_present'], payload['new_present'],
            _json(payload['old_value']), _json(payload['new_value'])))

    def change(self, code, location, operation, context, old, new, classification, reason):
        if old is MISSING and new is MISSING:
            return
        if old is not MISSING and new is not MISSING and _json(old) == _json(new):
            return
        self.emit(code, location, operation, context, old, new, classification, reason)

    def coverage(self, location, reason):
        self.warnings.append({'snapshot': 'comparison', 'location': location, 'reason': reason})

    def unknown_fields(self, old, new, handled, location, operation, context):
        for key in sorted((old.keys() | new.keys()) - handled - ANNOTATIONS):
            if context in ('request', 'response', 'neutral') or key in ('jsonSchemaDialect', '$ref', 'allOf', 'anyOf', 'oneOf', 'not', 'if', 'then', 'else',
                       'discriminator', 'unevaluatedProperties', '$dynamicRef', '$schema'):
                self.coverage(pointer(location, key), 'unsupported_semantics_require_review')
            self.change('UNSUPPORTED_FIELD_CHANGED', pointer(location, key), operation, context,
                        old.get(key, MISSING), new.get(key, MISSING), 'REVIEW_REQUIRED',
                        'This field is outside the supported compatibility rules; review its effect.')

    @staticmethod
    def variance(narrowing: bool, context: str) -> str:
        if context not in ('request', 'response'):
            return 'REVIEW_REQUIRED'
        breaking = narrowing if context == 'request' else not narrowing
        return 'BREAKING' if breaking else 'NON_BREAKING'

    def schema(self, old, new, location, operation, context, depth=0):
        if depth > 70:
            raise ContractError('schema_comparison_limit')
        for schema in (old, new):
            if not isinstance(schema, (dict, bool)):
                raise ContractError('invalid_schema')
        if isinstance(old, bool) or isinstance(new, bool):
            classification = ('REVIEW_REQUIRED' if type(old) is not type(new) else
                              self.variance(new is False, context))
            self.change('BOOLEAN_SCHEMA_CHANGED', location, operation, context, old, new,
                        classification, 'Boolean schema acceptance changed; direction follows request/response use.')
            return
        for schema in (old, new):
            _validate_schema(schema)
        old_types, new_types = _types(old), _types(new)
        if old_types != new_types:
            if old_types is not None and new_types is not None:
                old_accept = old_types | ({'integer'} if 'number' in old_types else set())
                new_accept = new_types | ({'integer'} if 'number' in new_types else set())
                if old_accept < new_accept:
                    classification = self.variance(False, context)
                elif new_accept < old_accept:
                    classification = self.variance(True, context)
                else:
                    classification = 'BREAKING' if context != 'neutral' else 'REVIEW_REQUIRED'
            elif old_types is None and new_types is not None:
                classification = self.variance(True, context)
            else:
                classification = self.variance(False, context)
            code = 'NULLABILITY_CHANGED' if (old_types or set()) ^ (new_types or set()) == {'null'} else 'TYPE_CHANGED'
            self.emit(code, pointer(location, 'type'), operation, context,
                      sorted(old_types) if old_types is not None else None,
                      sorted(new_types) if new_types is not None else None, classification,
                      'Request narrowing or response widening can violate existing client expectations.')
        elif old.get('nullable', False) != new.get('nullable', False) and old_types is None:
            self.change('NULLABILITY_CHANGED', pointer(location, 'nullable'), operation, context,
                old.get('nullable', False), new.get('nullable', False), 'REVIEW_REQUIRED',
                'Nullable without a concrete type cannot be proven compatible.')
        old_enum, new_enum = old.get('enum', MISSING), new.get('enum', MISSING)
        if old_enum is not MISSING or new_enum is not MISSING:
            a = {_json(v): v for v in old_enum} if old_enum is not MISSING else {}
            b = {_json(v): v for v in new_enum} if new_enum is not MISSING else {}
            if old_enum is MISSING or new_enum is MISSING:
                self.change('ENUM_CONSTRAINT_CHANGED', pointer(location, 'enum'), operation, context,
                    old_enum, new_enum, self.variance(new_enum is not MISSING, context),
                    'An enum restricts accepted requests or guarantees a bounded set of response values.')
            else:
                for code, values, narrowing in [('ENUM_VALUES_REMOVED', a.keys() - b.keys(), True),
                                               ('ENUM_VALUES_ADDED', b.keys() - a.keys(), False)]:
                    if values:
                        self.emit(code, pointer(location, 'enum'), operation, context,
                            [a[v] for v in sorted(values)] if narrowing else MISSING,
                            [b[v] for v in sorted(values)] if not narrowing else MISSING,
                            self.variance(narrowing, context),
                            'Enum contraction narrows requests; enum expansion widens possible responses.')
        a_required, b_required = set(old.get('required', [])), set(new.get('required', []))
        for key in sorted(a_required ^ b_required):
            required = key in b_required
            self.emit('REQUIRED_PROPERTY_ADDED' if required else 'REQUIRED_PROPERTY_REMOVED',
                pointer(pointer(location, 'required'), key), operation, context,
                not required, required, self.variance(required, context),
                'New request requirements break existing inputs; lost response requirements weaken guarantees.')
        a_props, b_props = old.get('properties', {}), new.get('properties', {})
        for key in sorted(a_props.keys() | b_props.keys()):
            here = pointer(pointer(location, 'properties'), key)
            if key not in a_props:
                classification = ('NON_BREAKING' if context == 'response' else
                                  'BREAKING' if context == 'request' and key in b_required else
                                  'NON_BREAKING' if context == 'request' and old.get('additionalProperties') is False else
                                  'REVIEW_REQUIRED')
                if context == 'response' and old.get('additionalProperties') is False:
                    classification = 'BREAKING'
                self.emit('PROPERTY_ADDED', here, operation, context, MISSING, b_props[key],
                    classification, 'Response additions are additive unless the old object was closed; new request property constraints may reject previously accepted values.')
            elif key not in b_props:
                classification = ('BREAKING' if context == 'response' or new.get('additionalProperties') is False else
                                  'NON_BREAKING' if context == 'request' and new.get('additionalProperties', True) is True else
                                  'REVIEW_REQUIRED')
                self.emit('PROPERTY_REMOVED', here, operation, context, a_props[key], MISSING,
                          classification, 'Consumers may depend on this property; request handling depends on additional-property behavior.')
            else:
                self.schema(a_props[key], b_props[key], here, operation, context, depth + 1)
        if 'items' in old or 'items' in new:
            self.schema(old.get('items', {}), new.get('items', {}), pointer(location, 'items'), operation, context, depth + 1)
        a_extra, b_extra = old.get('additionalProperties', True), new.get('additionalProperties', True)
        if isinstance(a_extra, bool) and isinstance(b_extra, bool):
            self.change('ADDITIONAL_PROPERTIES_CHANGED', pointer(location, 'additionalProperties'),
                operation, context, a_extra, b_extra, self.variance(b_extra is False, context),
                'Closing request objects narrows accepted inputs; opening response objects widens output.')
        elif a_extra != b_extra:
            self.change('ADDITIONAL_PROPERTIES_SCHEMA_CHANGED', pointer(location, 'additionalProperties'),
                operation, context, a_extra, b_extra, 'REVIEW_REQUIRED',
                'Additional-property schema subsumption requires review.')
        for key in ('minimum', 'maximum', 'minLength', 'maxLength', 'minItems', 'maxItems', 'minProperties', 'maxProperties'):
            a, b = old.get(key, MISSING), new.get(key, MISSING)
            if a == b:
                continue
            narrowing = b is not MISSING and (a is MISSING or (b > a if key.startswith('min') else b < a))
            self.change('SCHEMA_BOUND_CHANGED', pointer(location, key), operation, context, a, b,
                self.variance(narrowing, context), 'Tighter request bounds or looser response guarantees can break clients.')
        for key in ('readOnly', 'writeOnly'):
            if old.get(key, False) or new.get(key, False):
                self.coverage(pointer(location, key), 'directional_property_visibility_requires_review')
            self.change('PROPERTY_VISIBILITY_CHANGED', pointer(location, key), operation, context,
                old.get(key, False), new.get(key, False), 'REVIEW_REQUIRED',
                'Read/write-only property visibility affects directional requiredness.')
        self.unknown_fields(old, new, SCHEMA_KEYS, location, operation, context)

    def content(self, old, new, location, operation, context):
        for media in sorted(old.keys() | new.keys()):
            here = pointer(location, media)
            if media not in old or media not in new:
                added = media in new
                self.emit('MEDIA_TYPE_ADDED' if added else 'MEDIA_TYPE_REMOVED', here, operation,
                    context, old.get(media, MISSING), new.get(media, MISSING),
                    'NON_BREAKING' if added and context == 'request' else 'BREAKING',
                    'Request media additions extend accepted inputs; removed support or new output formats can break clients.')
                continue
            self.schema(old[media].get('schema', {}), new[media].get('schema', {}),
                        pointer(here, 'schema'), operation, context)
            self.unknown_fields(old[media], new[media], {'schema'}, here, operation, context)

    def parameters(self, old, new, location, operation):
        for identity in sorted(old.keys() | new.keys()):
            here = pointer(pointer(location, identity[0]), identity[1])
            if identity not in old or identity not in new:
                added = identity in new
                value = new[identity] if added else old[identity]
                classification = ('REVIEW_REQUIRED' if '$ref' in value else
                    'NON_BREAKING' if added and not value.get('required', False) else 'BREAKING')
                self.emit('PARAMETER_ADDED' if added else 'PARAMETER_REMOVED', here, operation,
                    'request', old.get(identity, MISSING), new.get(identity, MISSING), classification,
                    'Adding optional input is compatible; requiring new input or removing a supported parameter can break clients.')
                continue
            a, b = old[identity], new[identity]
            self.change('PARAMETER_REQUIRED_CHANGED', pointer(here, 'required'), operation, 'request',
                a.get('required', False), b.get('required', False),
                'BREAKING' if b.get('required', False) else 'NON_BREAKING',
                'Introducing a requirement rejects clients that omit this parameter.')
            self.schema(a.get('schema', {}), b.get('schema', {}), pointer(here, 'schema'), operation, 'request')
            self.content(a.get('content', {}), b.get('content', {}), pointer(here, 'content'), operation, 'request')
            for key, default in (('style', 'form' if identity[0] in ('query', 'cookie') else 'simple'),
                                 ('explode', None), ('allowReserved', False), ('allowEmptyValue', False)):
                av = a.get(key, a.get('style', 'form' if identity[0] in ('query', 'cookie') else 'simple') == 'form' if key == 'explode' else default)
                bv = b.get(key, b.get('style', 'form' if identity[0] in ('query', 'cookie') else 'simple') == 'form' if key == 'explode' else default)
                self.change('PARAMETER_SERIALIZATION_CHANGED', pointer(here, key), operation,
                    'request', av, bv, 'BREAKING', 'Changing parameter serialization can invalidate existing requests.')
            self.unknown_fields(a, b, {'name', 'in', 'required', 'schema', 'content', 'style',
                                'explode', 'allowReserved', 'allowEmptyValue'}, here, operation, 'request')

    def run(self):
        a, b = self.previous.value, self.current.value
        self.change('OPENAPI_VERSION_CHANGED', '/openapi', None, 'contract', a['openapi'], b['openapi'],
            'REVIEW_REQUIRED', 'OpenAPI version changes may alter schema semantics.')
        self.change('GLOBAL_SECURITY_CHANGED', '/security', None, 'security',
            _security(a.get('security', [])), _security(b.get('security', [])), 'SECURITY_RELEVANT',
            'Global authentication alternatives or scopes changed; security review is mandatory.')
        old_schemes, new_schemes = (d.get('components', {}).get('securitySchemes', {}) for d in (a, b))
        for name in sorted(old_schemes.keys() | new_schemes.keys()):
            here = pointer('/components/securitySchemes', name)
            self.change('SECURITY_SCHEME_ADDED' if name not in old_schemes else
                        'SECURITY_SCHEME_REMOVED' if name not in new_schemes else 'SECURITY_SCHEME_CHANGED',
                here, None, 'security', old_schemes.get(name, MISSING), new_schemes.get(name, MISSING),
                'SECURITY_RELEVANT', 'Authentication scheme configuration changed; never approve automatically.')
            if '[REDACTED]' in _json([old_schemes.get(name), new_schemes.get(name)]):
                self.coverage(here, 'redacted_authentication_details_cannot_be_compared')
        for path in sorted(a['paths'].keys() | b['paths'].keys()):
            here = pointer('/paths', path)
            if path not in a['paths'] or path not in b['paths']:
                added = path in b['paths']
                self.emit('PATH_ADDED' if added else 'PATH_REMOVED', here, None, 'contract',
                    a['paths'].get(path, MISSING), b['paths'].get(path, MISSING),
                    'NON_BREAKING' if added else 'BREAKING', 'Adding a path extends the API; removing a path breaks existing callers.')
                continue
            ai, bi = a['paths'][path], b['paths'][path]
            for method in sorted(METHODS & (ai.keys() | bi.keys())):
                at, operation = pointer(here, method), method.upper() + ' ' + path
                if method not in ai or method not in bi:
                    added = method in bi
                    self.emit('OPERATION_ADDED' if added else 'OPERATION_REMOVED', at, operation, 'contract',
                        ai.get(method, MISSING), bi.get(method, MISSING),
                        'NON_BREAKING' if added else 'BREAKING', 'Adding an operation extends the API; removing it breaks callers.')
                    continue
                ao, bo = ai[method], bi[method]
                ap = {**_parameters(ai.get('parameters', [])), **_parameters(ao.get('parameters', []))}
                bp = {**_parameters(bi.get('parameters', [])), **_parameters(bo.get('parameters', []))}
                self.parameters(ap, bp, pointer(at, 'parameters'), operation)
                ar, br = ao.get('requestBody', {}), bo.get('requestBody', {})
                if ('requestBody' in ao) != ('requestBody' in bo):
                    added = 'requestBody' in bo
                    self.emit('REQUEST_BODY_ADDED' if added else 'REQUEST_BODY_REMOVED', pointer(at, 'requestBody'),
                        operation, 'request', ao.get('requestBody', MISSING), bo.get('requestBody', MISSING),
                        'NON_BREAKING' if added and not br.get('required', False) else 'BREAKING',
                        'Optional request bodies are additive; required additions or removals can break callers.')
                else:
                    self.change('REQUEST_BODY_REQUIRED_CHANGED', at + '/requestBody/required', operation, 'request',
                        ar.get('required', False), br.get('required', False),
                        'BREAKING' if br.get('required', False) else 'NON_BREAKING', 'New mandatory request bodies reject existing empty requests.')
                    self.content(ar.get('content', {}), br.get('content', {}), at + '/requestBody/content', operation, 'request')
                    self.unknown_fields(ar, br, {'required', 'content'}, at + '/requestBody', operation, 'request')
                for status in sorted(ao['responses'].keys() | bo['responses'].keys()):
                    loc = pointer(at + '/responses', status)
                    if status not in ao['responses'] or status not in bo['responses']:
                        added = status in bo['responses']
                        self.emit('RESPONSE_STATUS_ADDED' if added else 'RESPONSE_STATUS_REMOVED', loc, operation, 'response',
                            ao['responses'].get(status, MISSING), bo['responses'].get(status, MISSING),
                            'REVIEW_REQUIRED' if added else 'BREAKING', 'New status handling requires review; removed documented outcomes can break client workflows.')
                        continue
                    av, bv = ao['responses'][status], bo['responses'][status]
                    self.content(av.get('content', {}), bv.get('content', {}), loc + '/content', operation, 'response')
                    self.unknown_fields(av, bv, {'content'}, loc, operation, 'response')
                self.change('OPERATION_SECURITY_CHANGED', at + '/security', operation, 'security',
                    _security(ao.get('security', a.get('security', []))),
                    _security(bo.get('security', b.get('security', []))), 'SECURITY_RELEVANT',
                    'Effective authentication alternatives or scopes changed for this operation.')
                self.unknown_fields(ao, bo, {'parameters', 'requestBody', 'responses', 'security'}, at, operation, 'contract')
            self.unknown_fields(ai, bi, METHODS | {'parameters'}, here, None, 'contract')
        old_schemas, new_schemas = (d.get('components', {}).get('schemas', {}) for d in (a, b))
        for name in sorted(old_schemas.keys() | new_schemas.keys()):
            here = pointer('/components/schemas', name)
            if name not in old_schemas or name not in new_schemas:
                self.emit('SCHEMA_COMPONENT_ADDED' if name in new_schemas else 'SCHEMA_COMPONENT_REMOVED',
                    here, None, 'neutral', old_schemas.get(name, MISSING), new_schemas.get(name, MISSING),
                    'REVIEW_REQUIRED', 'Component consumers may be outside observed operations.')
            else:
                self.schema(old_schemas[name], new_schemas[name], here, None, 'neutral')
        self.unknown_fields(a.get('components', {}), b.get('components', {}), {'schemas', 'securitySchemes'}, '/components', None, 'contract')
        self.unknown_fields(a, b, {'openapi', 'info', 'paths', 'components', 'security'}, '', None, 'contract')
        changes = tuple(sorted(self.changes, key=lambda c: (c.location, c.operation or '', c.change_type, c.change_id)))
        warnings = sorted({_json(w): w for w in self.warnings}.values(), key=_json)
        refs = sorted(self.previous.references + self.current.references, key=_json)
        return ChangeSet(changes, _json(warnings), _json(refs), _hash(_semantic(a)), _hash(_semantic(b)))


def _validate_schema(schema):
    if 'type' in schema:
        kinds = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        if not kinds or any(not isinstance(k, str) or k not in ('null', 'boolean', 'object', 'array', 'number', 'integer', 'string') for k in kinds):
            raise ContractError('invalid_schema_type')
    if 'required' in schema and (not isinstance(schema['required'], list) or any(not isinstance(k, str) for k in schema['required'])):
        raise ContractError('invalid_schema_required')
    if 'properties' in schema and not isinstance(schema['properties'], dict):
        raise ContractError('invalid_schema_properties')
    if 'enum' in schema and (not isinstance(schema['enum'], list) or not schema['enum']):
        raise ContractError('invalid_schema_enum')
    for key in ('nullable', 'readOnly', 'writeOnly'):
        if key in schema and type(schema[key]) is not bool:
            raise ContractError('invalid_schema_boolean')
    for key in ('minimum', 'maximum', 'minLength', 'maxLength', 'minItems', 'maxItems', 'minProperties', 'maxProperties'):
        if key in schema and (type(schema[key]) not in (float, int) or
                (key not in ('minimum', 'maximum') and (type(schema[key]) is not int or schema[key] < 0))):
            raise ContractError('invalid_schema_bound')
    if 'additionalProperties' in schema and not isinstance(schema['additionalProperties'], (dict, bool)):
        raise ContractError('invalid_additional_properties')


def _schema_shape(schema, version, depth=0):
    if depth > 75 or not isinstance(schema, (dict, bool)):
        raise ContractError('invalid_schema')
    if isinstance(schema, bool):
        if version.startswith('3.0'):
            raise ContractError('boolean_schema_requires_openapi31')
        return
    _validate_schema(schema)
    if version.startswith('3.0') and (isinstance(schema.get('type'), list) or schema.get('type') == 'null'):
        raise ContractError('invalid_openapi30_type')
    for value in schema.get('properties', {}).values():
        _schema_shape(value, version, depth + 1)
    for key in ('items', 'additionalProperties', 'not', 'if', 'then', 'else', 'contains', 'propertyNames'):
        if key in schema and not (key == 'additionalProperties' and isinstance(schema[key], bool)):
            _schema_shape(schema[key], version, depth + 1)
    for key in ('allOf', 'anyOf', 'oneOf'):
        if key in schema:
            if not isinstance(schema[key], list) or not schema[key]:
                raise ContractError('invalid_schema_composition')
            for value in schema[key]:
                _schema_shape(value, version, depth + 1)


def _types(schema):
    if 'type' not in schema:
        return None
    types = set(schema['type'] if isinstance(schema['type'], list) else [schema['type']])
    if 'number' in types:
        types.discard('integer')
    if schema.get('nullable', False):
        types.add('null')
    return types


def _semantic(value, key='', mapping=False, literal=False):
    if literal:
        return value
    if isinstance(value, dict):
        return {k: _semantic(v, k, mapping=not mapping and k in MAP_KEYS,
                            literal=not mapping and k in ('enum', 'const', 'default'))
                for k, v in sorted(value.items())
                if mapping or (k not in ANNOTATIONS and not (key == '' and k == 'info'))}
    if isinstance(value, list):
        if key == 'security':
            return _security(value)
        items = [_semantic(v) for v in value]
        if key == 'parameters':
            return sorted(items, key=_json)
        return items
    return value


def compare_openapi(previous: dict[str, Any], current: dict[str, Any]) -> ChangeSet:
    """Pure comparison; never fetches a reference or invokes an LLM.

    Locations are escaped JSON pointers in the effective document (inherited
    parameters use /parameters/{in}/{name}). Reference provenance maps expanded
    usage locations back to the original local reference paths.
    """
    return _Engine(_Document(previous, 'previous'), _Document(current, 'current')).run()
