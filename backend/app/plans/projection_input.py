"""Reject incomplete model-request views without repairing or executing them."""

from pydantic import BaseModel, ValidationError

from app.api import AppError


def _markers(value):
    """Read existing containers only, including typed nested inputs; never serialize."""
    pending, seen = [value], set()
    while pending:
        item = pending.pop()
        if not isinstance(item, (dict, list, tuple, BaseModel)) or id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, BaseModel):
            # No computed fields, arbitrary attribute access or model serializers.
            pending.append(vars(item))
            extra = getattr(item, '__pydantic_extra__', None)
            if isinstance(extra, dict):
                pending.append(extra)
        elif isinstance(item, dict):
            if 'context_projection' in item:
                yield item['context_projection']
            pending.extend(item.values())
        else:
            pending.extend(item)


def reject_context_projection(value):
    """Unmarked inputs keep their original parser behavior and object identity."""
    from app.agents.schemas import WorkspaceRef

    found, reread = False, []
    for marker in _markers(value):
        found = True
        candidates = marker.get('reread') if isinstance(marker, dict) else None
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if (not isinstance(candidate, dict) or set(candidate) != {'tool', 'arguments'}
                    or candidate['tool'] != 'read_workspace'):
                continue
            # Reject coercion/model objects: reread metadata must be exact JSON.
            arguments = candidate['arguments']
            if (not isinstance(arguments, dict) or set(arguments) != {'key', 'version'}
                    or type(arguments['key']) is not str or type(arguments['version']) is not int):
                continue
            try:
                ref = WorkspaceRef.model_validate(arguments).model_dump(mode='json')
            except (TypeError, ValueError, ValidationError, AppError):
                continue
            if ref != arguments:
                continue
            address = {'tool': 'read_workspace', 'arguments': ref}
            if address not in reread:
                reread.append(address)
            if len(reread) == 3:
                break
        if len(reread) == 3:
            break
    if not found:
        return value
    raise AppError('PLAN_CONTEXT_PROJECTION',
        'This draft contains an incomplete model-context projection. Reread the original saved '
        'workspace version before writing or checking a complete Plan; never execute the projection.',
        422, payload={'reread': reread, 'repair_guidance':
            'Use read_workspace with an exact saved key/version. If no valid address is listed, '
            'locate the original saved draft first; do not guess omitted nodes, fields or versions.'})
