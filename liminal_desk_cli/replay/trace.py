"""Parse and validate version-1 Desk JSON traces."""
import json
from pathlib import Path
from .models import Event

def load_trace(path, stream):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    doc = json.loads(Path(path).read_text(), object_pairs_hook=unique,
                     parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    if (not isinstance(doc, dict) or set(doc) != {'version', 'steps'}
            or type(doc['version']) is not int or doc['version'] != 1
            or not isinstance(doc['steps'], list)):
        raise ValueError(f'{path}: expected version 1 and steps array')
    elapsed = 0
    events = []
    for i, step in enumerate(doc['steps']):
        if not isinstance(step, dict):
            raise ValueError(f'{path}: step {i+1} must be an object')
        if step.get('type') == 'delay' and set(step) == {'type', 'duration_ms'}:
            duration = step['duration_ms']
            if type(duration) is not int or duration < 0:
                raise ValueError(f'{path}: step {i+1}: invalid delay')
            elapsed += duration
        elif step.get('type') == 'send' and set(step) == {'type', 'payload'}:
            if not isinstance(step['payload'], dict):
                raise ValueError(f'{path}: step {i+1}: payload must be an object')
            payload = step['payload']
            if type(payload.get('timestamp_ms')) is not int:
                raise ValueError(f'{path}: step {i+1}: integer timestamp_ms required')
            events.append(Event(elapsed, stream, i, payload))
        else:
            raise ValueError(f'{path}: unsupported step {i+1}')
    if not events:
        raise ValueError(f'{path}: no send events')
    origins = {e.payload['timestamp_ms'] - e.at for e in events}
    if len(origins) != 1:
        raise ValueError(f'{path}: timestamps disagree with delay offsets')
    return events, elapsed, origins.pop()
