"""Lossless, schema-directed decoding of JSON containers returned as strings."""

import copy
import json


def normalize_containers(value, schema):
    """Only decode array/object strings where that type is required; never infer values."""
    definitions = schema.get('$defs', {})
    changes = []

    def resolve(spec):
        ref = spec.get('$ref', '')
        return definitions.get(ref.removeprefix('#/$defs/'), spec) if ref.startswith('#/$defs/') else spec

    def visit(item, spec, path):
        spec = resolve(spec)
        options = [resolve(s) for s in spec.get('anyOf', [spec])]
        types = {option.get('type') for option in options}
        if isinstance(item, str) and 'string' not in types and types & {'array', 'object'}:
            try:
                decoded = json.loads(item)
            except ValueError:
                pass
            else:
                target = 'array' if isinstance(decoded, list) else 'object' if isinstance(decoded, dict) else None
                if target is not None and target in types:
                    item = decoded
                    changes.append({'path': path, 'operation': 'decode_json_string', 'target_type': target})
        if isinstance(item, dict):
            selected = next((s for s in options if s.get('type') == 'object'), {})
            properties = selected.get('properties', {})
            return {key: visit(v, properties[key], f'{path}.{key}') if key in properties else v
                    for key, v in item.items()}
        if isinstance(item, list):
            selected = next((s for s in options if s.get('type') == 'array'), {})
            return [visit(v, selected.get('items', {}), f'{path}[{i}]') for i, v in enumerate(item)]
        return item

    return visit(copy.deepcopy(value), schema, '$'), changes
