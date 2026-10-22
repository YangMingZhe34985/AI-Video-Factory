"""Read-only versioned evaluation accounting. Standard library; no app/network imports."""
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import argparse
import json
import re
import sqlite3
import tempfile

if __package__:
    from .aspect_evidence import inspect_aspect_chain
    from .round_profiles import round_profile
    from .image_evidence import image_evidence, read_image_tables, identity_request_evidence, identity_archive_evidence
else:
    from aspect_evidence import inspect_aspect_chain
    from round_profiles import round_profile
    from image_evidence import image_evidence, read_image_tables, identity_request_evidence, identity_archive_evidence

TEMP = Path(tempfile.gettempdir()).resolve()
MARKER = {'round': 'V12-Gate5b', 'call_limit': 150, 'real_image_limit': 0,
          'real_video_limit': 0, 'media_mode': 'mock'}
TEXT = 'deepseek-v4.1-flash'
VISION = 'qwen3.7-plus'
LLM_TOOLS = {'agent_llm_turn': 'text', 'analyze_images': 'vision', 'gate6_identity_review': 'vision'}
MEDIA_TOOLS = {'generate_image', 'animate_shot', 'generate_video', 'transform_video', 'request_preview'}
EXPECTED = {'c7_complete_story': 1, 'c3_story': 2, 'c1_portrait': 1}


def checked_work(value, profile="V12"):
    selected = round_profile(profile)
    work = Path(value).resolve()
    if not work.is_relative_to(TEMP) or work == TEMP or not work.name.startswith(selected["prefix"]):
        raise ValueError("Only the selected profile's dedicated TEMP directory is allowed")
    marker = work / selected["marker_file"]
    if not marker.resolve().is_relative_to(work) or json.loads(marker.read_text(encoding="utf-8")) != selected["marker"]:
        raise ValueError("Exact selected round marker required")
    return work

@contextmanager
def ro(work, name):
    path = (work / name).resolve()
    if not path.is_relative_to(work) or not path.is_file():
        raise ValueError('Read-only database must exist inside this evaluation directory')
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        yield conn
    finally:
        conn.close()


def obj(value, fallback=None):
    if value is None:
        return {} if fallback is None else fallback
    result = json.loads(value) if isinstance(value, str) else value
    return ({} if fallback is None else fallback) if result is None else result


def valid_token(value):
    return type(value) is int and value >= 0


def usage(rows, *, physical=False):
    pairs = [(row.get('input_tokens'), row.get('output_tokens')) if physical else
             ((obj(row.get('output_payload')).get('usage') or {}).get('prompt_tokens'),
              (obj(row.get('output_payload')).get('usage') or {}).get('completion_tokens'))
             for row in rows]
    inputs = [a for a, _ in pairs if valid_token(a)]
    outputs = [b for _, b in pairs if valid_token(b)]
    missing = sum(not (valid_token(a) and valid_token(b)) for a, b in pairs)
    return {'calls': len(rows), 'input_tokens_max': max(inputs) if inputs else None,
            'input_tokens_known_sum': sum(inputs), 'output_tokens_known_sum': sum(outputs),
            'usage_missing_calls': missing, 'usage_complete': missing == 0 and bool(rows)}


def credits(rows):
    return float(sum((Decimal(str(row.get('estimated_cost') or 0)) for row in rows
                      if row['status'] != 'rejected'), Decimal(0)))


def ledger_metrics(rows, image_audit=None):
    model = [r for r in rows if r['tool_name'] in LLM_TOOLS]
    media = [r for r in rows if r['tool_name'] in MEDIA_TOOLS]
    real_ids = set((image_audit or {}).get('real_invocation_ids', []))
    uncertain_ids = set((image_audit or {}).get('unattributed_invocation_ids', []))
    real_media = [r for r in media if r['invocation_id'] in real_ids]
    uncertain = [r for r in media if r['invocation_id'] in uncertain_ids]
    mock_media = [r for r in media if r['invocation_id'] not in real_ids | uncertain_ids]
    return {'unique_invocations': len(rows), 'text': usage([r for r in model if r['tool_name'] == 'agent_llm_turn']),
        'vision': usage([r for r in model if LLM_TOOLS[r['tool_name']] == 'vision']), 'all_model_usage': usage(model),
        'llm_demo_credits': credits(model), 'mock_media_demo_credits': credits(mock_media),
        'real_image_demo_credits': credits(real_media), 'unattributed_media_demo_credits': credits(uncertain),
        'other_demo_credits': credits([r for r in rows if r['tool_name'] not in MEDIA_TOOLS | set(LLM_TOOLS)]),
        'accounted_demo_credits': credits(rows),
        'pending_or_running_demo_reservations': credits([r for r in rows if r['status'] in {'pending', 'running'}]),
        'statuses': dict(Counter(r['status'] for r in rows)),
        'generation_tools': dict(Counter(r['tool_name'] for r in media if r['status'] != 'rejected'))}


def goal(name, passed, evidence=None, *, covered=True):
    return {'name': name, 'status': 'not_covered' if not covered else 'passed' if passed else 'failed', 'evidence': evidence}


def refs(value):
    if isinstance(value, dict):
        if set(value) == {'ref'} and isinstance(value['ref'], str):
            yield value['ref']
        else:
            for child in value.values():
                yield from refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from refs(child)


def plan_evidence(plan):
    nodes = plan.get('nodes', [])
    by_id = {node['id']: node for node in nodes}
    selectors = [n for n in nodes if n['tool'] == 'select_image']
    independent = []
    for selector in selectors:
        candidates = selector.get('inputs', {}).get('candidate_artifact_ids')
        sources = list(refs(candidates))
        matched = [by_id.get(ref.partition('.')[0], {}) for ref in sources]
        valid = (isinstance(candidates, list) and len(sources) == len(candidates) == 3
            and len(set(sources)) == 3 and all(ref.endswith('.image') for ref in sources)
            and all(n.get('tool') == 'generate_image' and n.get('params', {}).get('n', 1) == 1 for n in matched))
        downstream = [n['id'] for n in nodes if n['tool'] == 'animate_shot'
            and n.get('inputs', {}).get('first_frame_artifact_id') == {'ref': selector['id'] + '.image'}]
        independent.append({'selector': selector['id'], 'candidates': sources, 'three_independent_n1': valid,
                            'choice_gate': selector.get('gate') == 'choice', 'animation_node_ids': downstream})
    catalog = plan.get('character_references') or {}
    generated = [n for n in nodes if n['tool'] in MEDIA_TOOLS]
    multi = [{'node_id': n['id'], 'tool': n['tool'], 'characters': n.get('characters'),
              'media_refs': list(refs(n.get('inputs', {}))), 'model_id': n.get('model_id')}
             for n in generated if len(n.get('characters') or []) > 1]
    return {'node_count': len(nodes), 'selectors': independent,
            'declared_characters': sorted(catalog), 'generation_nodes_missing_declarations':
                [n['id'] for n in generated if n.get('characters') is None],
            'multi_character_nodes': multi, 'planned_delivery_video_seconds': plan.get('estimates', {}).get('video_seconds'),
            'generated_video_seconds': sum(n.get('params', {}).get('duration', 0) or 0 for n in generated if n['tool'] != 'generate_image'),
            'semantic_identity_and_style_review': 'needs_review'}


def planning_audit_label(data, profile):
    """V13 archives explicitly bind a fixed phase; V12 retains historical labels."""
    rid, case = data.get('run_id'), data.get('case')
    if profile['name'] == 'V12':
        return case + ':' + rid if isinstance(case, str) and isinstance(rid, str) else None
    label = data.get('audit_label')
    if data.get('phase') != 'planning' or not isinstance(label, str) or not isinstance(rid, str):
        return None
    phase, separator, bound_run = label.partition(':')
    if separator and bound_run == rid and profile['planning_labels'].get(phase) == case:
        return label
    return None


def read_archives(work, diagnostics):
    grouped = defaultdict(list)
    for path in sorted((work / 'results').glob('*.json')):
        if path.name.endswith('_private_profile.json') or not path.name.startswith(('result_', 'hybrid_')):
            continue
        if not path.resolve().is_relative_to(work):
            raise ValueError('Archive escapes V12 work directory')
        raw = path.read_bytes()
        data = json.loads(raw.decode('utf-8'))
        run_id = data.get('run_id')
        kind = 'planning' if data.get('case') else 'hybrid' if data.get('scenario') else None
        if not run_id or not kind:
            continue
        key = (kind, data.get('case') or data.get('scenario'), run_id)
        grouped[key].append((path, data, sha256(raw).hexdigest()))
    records = []
    for (kind, label, rid), items in sorted(grouped.items()):
        canonical = [item for item in items if rid in item[0].stem]
        chosen = sorted(canonical or items, key=lambda item: item[0].name)[0]
        conflict = any(item[1] != chosen[1] for item in items)
        if conflict:
            diagnostics.append({'code': 'ARCHIVE_CONFLICT', 'run_id': rid, 'label': label,
                                'sources': [str(item[0]) for item in items]})
        records.append({'kind': kind, 'label': label, 'run_id': rid, 'data': chosen[1], 'conflict': conflict,
            'source': {'path': str(chosen[0]), 'sha256': chosen[2]},
            'ignored_duplicate_files': [str(item[0]) for item in items if item is not chosen]})
    return records


def reason(code):
    explanations = {
        'INVALID_WORKSPACE_PAYLOAD': '工作区结构校验失败；具体字段需核对原工具参数和 Schema。',
        'INVALID_TOOL_ARGUMENTS': '工具参数结构不合法；不推断为模型截断，需看具体解析证据。',
        'AGENT_OUTPUT_TRUNCATED': '工具回执明确记录输出截断；独立核对服务商 finish_reason 与分批计划调用。',
        'PLAN_CHARACTER_REFERENCE_MISSING': '声明角色的必需身份依据未通过真实媒体引用链到达节点。',
        'PLAN_UNUSED_PAID_NODE': '付费生成节点未通过数据引用到达交付结果。',
        'PATCH_INTENT_CHANGED': '结构化审阅标记用户点名元素改变，自动批准被阻止。',
        'PATCH_INTENT_UNCERTAIN': '意图评估未知或不确定，自动批准被阻止。',
        'DataInspectionFailed': '本轮 Mock 内容审核故障；不能据此推断真实服务商拒绝原因。',
        'AGENT_ARGUMENT_CORRECTION_LIMIT': '连续参数纠错达到限制；初始错误原因需查看对应回执。'}
    return explanations.get(code, '需人工定位根因；保留原回执/消息位置，不能仅凭最终成功推断已解释。')


def failure_evidence(ledger, delegates):
    found = []
    seen = set()
    def add(code, source, **extra):
        key = (code, json.dumps(source, sort_keys=True))
        if key not in seen:
            found.append({'code': code or 'UNCLASSIFIED_FAILURE', 'source': source,
                'observed_cause': reason(code), 'root_cause_review': 'needs_review', **extra})
            seen.add(key)
    def walk(value, source):
        if isinstance(value, dict):
            if isinstance(value.get('code'), str):
                add(value['code'], source, detail={key: value[key] for key in ('node_id', 'message', 'path', 'loc') if key in value})
            for key, child in value.items():
                if key in {'issues', 'error', 'errors', 'tool_call_errors'}:
                    walk(child, {**source, 'field': key})
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, {**source, 'index': index})
    for row in ledger:
        source = {'table': 'tool_invocations', 'invocation_id': row['invocation_id'], 'tool': row['tool_name']}
        if row.get('error_code') or row['status'] in {'failed', 'rejected'}:
            add(row.get('error_code'), source, message=str(row.get('error_message') or '')[:1000])
        output = obj(row.get('output_payload'))
        walk(output, source)
        for index, error in enumerate(output.get('tool_call_errors') or []):
            if not isinstance(error, dict) or not error.get('code'):
                add('TOOL_ARGUMENT_PARSE_ERROR', {**source, 'argument_error_index': index},
                    message=str(error.get('error', error) if isinstance(error, dict) else error)[:1000])
    for row in delegates:
        walk(obj(row.get('error')), {'table': 'agent_delegations', 'delegation_id': row['id'], 'field': 'error'})
        for index, msg in enumerate(obj(row.get('state')).get('messages', [])):
            if msg.get('role') != 'tool':
                continue
            try:
                receipt = obj(msg.get('content'))
            except (ValueError, TypeError):
                continue
            if isinstance(receipt, dict):
                walk(receipt, {'table': 'agent_delegations', 'delegation_id': row['id'],
                    'message_index': index, 'tool_call_id': msg.get('tool_call_id'), 'tool': msg.get('name')})
    return found


def reconcile(ledger, physical):
    settled = [row for row in ledger if row['tool_name'] in LLM_TOOLS and row['status'] == 'success']
    good = [row for row in physical if row['status'] == 'success']
    logical, actual = usage(settled), usage(good, physical=True)
    nonsettled = [row['invocation_id'] for row in ledger if row['tool_name'] in LLM_TOOLS and row['status'] not in {'success', 'rejected'}]
    complete = bool(good) and logical['usage_complete'] and actual['usage_complete']
    per_kind = {}
    for kind in ('text', 'vision'):
        left = usage([r for r in settled if LLM_TOOLS[r['tool_name']] == kind])
        right = usage([r for r in good if r.get('kind') == kind], physical=True)
        keys = ('calls', 'input_tokens_known_sum', 'output_tokens_known_sum', 'input_tokens_max')
        per_kind[kind] = {'logical': left, 'physical': right, 'equal': all(left[key] == right[key] for key in keys)}
    equal = (all(item['equal'] for item in per_kind.values()) and len(settled) == len(good)
        and logical['input_tokens_known_sum'] == actual['input_tokens_known_sum']
        and logical['output_tokens_known_sum'] == actual['output_tokens_known_sum']
        and logical['input_tokens_max'] == actual['input_tokens_max'])
    return {'status': 'passed' if complete and equal and not nonsettled else 'not_covered' if not physical and not settled else 'needs_review',
        'logical_successes': len(settled), 'physical_successes': len(good), 'success_usage_equal': equal,
        'logical_usage': logical, 'physical_usage': actual, 'nonsettled_model_invocations': nonsettled,
        'physical_non_success_ids': [r['id'] for r in physical if r['status'] != 'success'], 'by_kind': per_kind,
        'granularity': 'Run aggregate; audit has no invocation_id/response_id link in application receipt, not a per-attempt identity proof'}


def latest_briefs(connection):
    """Read the same last persisted brief that compilation uses; no app import."""
    exists = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='agent_workspace_items'").fetchone()
    if not exists:
        return {}
    result = {}
    for row in connection.execute("SELECT id,run_id,key,version,payload FROM agent_workspace_items WHERE kind='brief' ORDER BY id"):
        payload = obj(row['payload'])
        if not isinstance(payload, dict):
            result[row['run_id']] = {'payload': {}, 'source': {'status': 'not_covered', 'reason': 'invalid_persisted_brief'}}
            continue
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        result[row['run_id']] = {'payload': payload, 'source': {'status': 'persisted_validated_workspace',
            'table': 'agent_workspace_items', 'id': row['id'], 'key': row['key'], 'version': row['version'],
            'payload_hash': sha256(canonical.encode('utf-8')).hexdigest(), 'aspect_ratio': payload.get('aspect_ratio'),
            'selection': 'latest brief by row id in this Run at readonly statistics snapshot'}}
    return result


def summarize(work, profile="V12"):
    work = checked_work(work, profile)
    profile = round_profile(profile)
    diagnostics = []
    archives = read_archives(work, diagnostics)
    with ro(work, 'eval.db') as app, ro(work, 'real_call_audit.sqlite') as audit:
        runs = [dict(row) for row in app.execute('SELECT run_id,status,error FROM agent_runs ORDER BY id')]
        ledger = [dict(row) for row in app.execute('SELECT id,invocation_id,budget_scope,tool_name,status,caller_agent,delegation_id,estimated_cost,output_payload,error_code,error_message FROM tool_invocations ORDER BY id')]
        delegates = [dict(row) for row in app.execute('SELECT id,run_id,parent_id,agent,status,llm_calls,steps,state,error FROM agent_delegations ORDER BY id')]
        briefs = latest_briefs(app)
        physical = [dict(row) for row in audit.execute('SELECT * FROM calls ORDER BY id')]
        blocked = [dict(row) for row in audit.execute('SELECT id,label,kind,reason FROM blocked ORDER BY id')]
        limit = audit.execute('SELECT max_calls FROM limits WHERE id=1').fetchone()[0]
        raw_images = read_image_tables(audit)
    unique = {}
    for row in ledger:
        key = (row['budget_scope'], row['invocation_id'])
        if key in unique:
            diagnostics.append({'code': 'DUPLICATE_INVOCATION', 'run_id': key[0], 'invocation_id': key[1]})
        else:
            unique[key] = row
    ledger = list(unique.values())
    images = image_evidence(raw_images, ledger, profile)
    diagnostics.extend(images["diagnostics"])
    image_run = (images.get("manifest") or {}).get("run_id")
    identity_label = "04-identity:" + image_run if isinstance(image_run, str) else ""
    identity_vision = identity_request_evidence(raw_images.get("identity_requests", []), physical,
        expected_label=identity_label if profile["name"] == "V13" else None)
    identity_archives=[]
    if profile['name']=='V13':
        for path in sorted((work/'results').glob('identity_04-identity_agent_*.json')):
            if not path.resolve().is_relative_to(work):
                raise ValueError('Identity archive escapes the evaluation directory')
            raw=path.read_bytes()
            identity_archives.append({'source':{'path':str(path),'sha256':sha256(raw).hexdigest()},
                'data':json.loads(raw.decode('utf-8'))})
    identity_archive=identity_archive_evidence(identity_archives,images,identity_vision,ledger,display_audit=raw_images)
    diagnostics.extend(identity_archive['diagnostics'])
    run_ids = {row['run_id'] for row in runs}
    if any(row['budget_scope'] not in run_ids for row in ledger):
        diagnostics.append({'code': 'ORPHAN_LEDGER', 'scopes': sorted({r['budget_scope'] for r in ledger} - run_ids)})
    physical_by_run = defaultdict(list)
    unmapped = []
    for row in physical:
        label = row.get('label') or ''
        matched = [rid for rid in run_ids if label == rid or label.endswith(':' + rid) or label.endswith('-' + rid)]
        if len(matched) == 1:
            physical_by_run[matched[0]].append(row)
        else:
            unmapped.append(row['id'])
    if unmapped:
        diagnostics.append({'code': 'UNMAPPED_PHYSICAL_ATTEMPTS', 'ids': unmapped})
    by_run = {rid: [row for row in ledger if row['budget_scope'] == rid] for rid in run_ids}
    evidence = []
    for run in runs:
        rid = run['run_id']
        children = [d for d in delegates if d['run_id'] == rid]
        evidence.append({'run_id': rid, 'current_status': run['status'], 'error': obj(run['error']),
            'metrics': ledger_metrics(by_run[rid], images), 'reconciliation': reconcile(by_run[rid], physical_by_run[rid]),
            'delegations': [{k: d[k] for k in ('id', 'parent_id', 'agent', 'status', 'steps', 'llm_calls')} for d in children],
            'failure_evidence': failure_evidence(by_run[rid], children),
            'model_finish_reasons': [{'invocation_id': row['invocation_id'], 'tool': row['tool_name'],
                'finish_reason': obj(row.get('output_payload'))['finish_reason']}
                for row in by_run[rid] if row['tool_name'] in LLM_TOOLS
                and obj(row.get('output_payload')).get('finish_reason') is not None],
            'archive_labels': [a['label'] for a in archives if a['run_id'] == rid],
            'physical_attempt_ids': [p['id'] for p in physical_by_run[rid]]})
    planning, hybrid = [], []
    for archive in archives:
        data, rid = archive['data'], archive['run_id']
        base = {k: archive[k] for k in ('label', 'run_id', 'source', 'ignored_duplicate_files', 'conflict')}
        base['status'] = data.get('status')
        if archive['kind'] == 'hybrid':
            accept = data.get('acceptance') or {}
            hybrid.append({**base, 'acceptance': accept, 'evidence_keys': sorted((data.get('evidence') or {})),
                'historical_fixture': 'historical-fixed' in archive['label'],
                'coverage': 'passed' if data.get('status') == 'passed' and accept.get('safe_control_flow') is True and not archive['conflict']
                    else 'not_covered' if data.get('status') in {'not_covered', 'running'} else 'failed',
                'manual_intent_path': bool(accept.get('manual_intent_path_covered')) and data.get('status') == 'passed' and not archive['conflict']})
            continue
        ids = [item.get('invocation_id') for key in ('turns', 'vision_calls') for item in data.get('metrics', {}).get(key, [])]
        ids_ok = bool(ids) and None not in ids and len(ids) == len(set(ids))
        available = {r['invocation_id']: r for r in by_run.get(rid, [])}
        exact = ids_ok and set(ids) <= available.keys() and all(available[i]['tool_name'] in LLM_TOOLS for i in ids)
        selected = [available[i] for i in ids if i in available] if ids_ok else []
        if not exact:
            diagnostics.append({'code': 'PLANNING_LEDGER_SLICE_UNVERIFIED', 'run_id': rid})
        boundary = next((r['id'] for r in by_run.get(rid, []) if r['tool_name'] == 'submit_plan'
            and r['status'] == 'success' and obj(r.get('output_payload')).get('submitted') is True
            and obj(r.get('output_payload')).get('plan_version') == 1), None)
        initial = [r for r in by_run.get(rid, []) if boundary is not None and r['id'] <= boundary]
        planning_cost_verified = exact and boundary is not None and {
            r['invocation_id'] for r in initial if r['tool_name'] in LLM_TOOLS} == set(ids)
        metrics = ledger_metrics(selected)
        metrics['planning_accounted_demo_credits'] = credits(initial) if planning_cost_verified else None
        metrics['planning_cost_slice_verified'] = planning_cost_verified
        for kind, archived_key in [('text', 'llm'), ('vision', 'vision')]:
            original = data.get('metrics', {}).get(archived_key, {})
            actual = metrics[kind]
            for old, new in [('calls', 'calls'), ('input_tokens_sum', 'input_tokens_known_sum'),
                             ('output_tokens_sum', 'output_tokens_known_sum')]:
                if old in original and original[old] != actual[new]:
                    diagnostics.append({'code': 'ARCHIVE_METRIC_MISMATCH', 'run_id': rid,
                        'metric': archived_key + '.' + old, 'archive': original[old], 'database': actual[new]})
                    exact = False
        if planning_cost_verified and isinstance(data.get('spent_total'), (int, float)) and abs(credits(initial) - data['spent_total']) > 0.00011:
            diagnostics.append({'code': 'ARCHIVE_COST_MISMATCH', 'run_id': rid,
                'archive': data['spent_total'], 'database': credits(initial)})
            planning_cost_verified = False
            metrics['planning_cost_slice_verified'] = False
        goals = [goal('进入可审核计划', data.get('status') == 'awaiting_plan_review' and bool(data.get('full_plan', {}).get('nodes')) and data.get('final_compile_issue_codes') == [], covered=not archive['conflict'] and 'final_compile_issue_codes' in data)]
        audit_label = planning_audit_label(data, profile)
        if audit_label is None:
            diagnostics.append({'code': 'PLANNING_AUDIT_LABEL_INVALID', 'run_id': rid})
        phase_physical = [p for p in physical_by_run[rid] if audit_label is not None and p.get('label') == audit_label]
        phase_check = reconcile(selected, phase_physical)
        physical_verified = exact and audit_label is not None and phase_check['status'] == 'passed'
        model_usage = metrics['text']
        physical_usage = usage(phase_physical, physical=True)
        if archive['label'] in {'c1_portrait', 'c6_constraint'}:
            goals.append(goal('初始文本轮数≤6', model_usage['calls'] <= 6, model_usage, covered=physical_verified))
        if archive['label'] in {'c3_story', 'c7_complete_story'}:
            threshold = profile['input_token_limit']
            peak = physical_usage['input_tokens_max']
            known_excess = peak is not None and peak > threshold
            goals.append(goal(f'单轮真实输入≤{threshold} token', not known_excess, physical_usage,
                covered=known_excess or physical_verified and physical_usage['usage_complete']))
            goals.append(goal('规划演示费用≤20 credits', (metrics['planning_accounted_demo_credits'] or 0) <= 20,
                metrics['planning_accounted_demo_credits'], covered=planning_cost_verified and physical_verified))
        if archive['label'] == 'c7_complete_story':
            ds = data.get('delegations')
            goals.append(goal('完整情节不委派Creative', not any(d.get('agent') == 'creative' for d in ds or []), covered=isinstance(ds, list) and bool(ds)))
        plan = plan_evidence(data.get('full_plan') or {})
        plan['duration_evidence_scope'] = (
            'V13 compiler delivery-chain estimate: repeated segments count, master/package aliases deduplicate; not a probed result or billable seconds.'
            if profile['name']=='V13' else
            'V12 archived compiler estimate under its historical version; not recomputed using V13 rules, not probed delivery or billable input/output seconds.')
        if archive['label'] == 'c7_complete_story':
            brief = briefs.get(rid) or {'payload': {}, 'source': {'status': 'not_covered', 'reason': 'persisted_brief_missing'}}
            aspect = inspect_aspect_chain(data.get('full_plan') or {}, brief['payload'])
            aspect['brief_source'] = brief['source']
            plan['aspect_chain'] = aspect
            goals.append({'name': '显式16:9贯穿关键帧、视频、拼接与QC',
                'status': aspect['status'] if data.get('status') == 'awaiting_plan_review' and not archive['conflict'] else 'not_covered',
                'evidence': aspect})
        initial_delegations = data.get('delegations')
        if archive['label'] in {'c1_portrait', 'c6_constraint'}:
            goals.append(goal('简单任务不委派子Agent', len(initial_delegations or []) == 1
                and initial_delegations[0].get('agent') == 'producer',
                covered=isinstance(initial_delegations, list) and bool(initial_delegations)))
        if archive['label'] == 'c1_portrait':
            goals.append(goal('仅一次合并视觉理解', metrics['vision']['calls'] == 1, metrics['vision'], covered=physical_verified))
        if archive['label'] == 'c6_constraint':
            videos = [n for n in data.get('full_plan', {}).get('nodes', []) if n.get('tool') in {'animate_shot', 'generate_video', 'transform_video'}]
            models = [n.get('model_id') for n in videos]
            goals.append(goal('视频具体ID均为wan2.7且排除HappyHorse', bool(models) and all(isinstance(m, str)
                and m.startswith('wan2.7-') and 'happy' not in m.lower() for m in models), models, covered=bool(videos)))
        if archive['label'] in {'c3_story', 'c7_complete_story'}:
            goals.append(goal('最终无付费死节点问题', 'PLAN_UNUSED_PAID_NODE' not in (data.get('final_compile_issue_codes') or []),
                covered=data.get('status') == 'awaiting_plan_review' and isinstance(data.get('final_compile_issue_codes'), list)))
            goals.append(goal('角色目录与显式声明进入可审核计划', len(plan['declared_characters']) >= 2
                and not plan['generation_nodes_missing_declarations'], plan['declared_characters'],
                covered=data.get('status') == 'awaiting_plan_review'))
            goals.append({'name': '多角色镜头语义与真实引用链审读', 'status': 'needs_review', 'evidence': plan['multi_character_nodes']})
        if archive['label'] == 'c5_novel':
            goals.append(goal('三张独立n=1候选→choice→动画', any(s['three_independent_n1'] and s['choice_gate'] and s['animation_node_ids'] for s in plan['selectors']), plan['selectors']))
        if archive['label'] == 'c5_novel':
            goals.append({'name': '逐张风格提示词确实不同且对应用户要求', 'status': 'needs_review', 'evidence': archive['source']})
        planning.append({**base, 'audit_label': audit_label, 'metrics': metrics, 'ledger_slice_verified': exact, 'physical_slice_verified': physical_verified, 'planning_reconciliation': phase_check, 'planning_invocation_ids': ids,
            'goals': goals, 'plan': plan, 'initial_delegations': data.get('delegations'),
            'final_compile_issue_codes': data.get('final_compile_issue_codes'),
            'semantic_review': 'needs_review' if archive['label'] in {'c3_story', 'c5_novel', 'c7_complete_story'} else 'not_assessed'})
    required = [goal(f'{case} 已完成指定{count}次归档', sum(p['label'] == case and not p['conflict'] for p in planning) == count,
        {'expected': count, 'observed': sum(p['label'] == case for p in planning)}, covered=any(p['label'] == case for p in planning)) for case, count in profile["expected"].items()]
    if profile['name'] == 'V13':
        phases = [p['audit_label'].partition(':')[0] for p in planning if p.get('audit_label')]
        required.append(goal('三个固定规划阶段各一次且不重采', Counter(phases) == Counter(list(profile['planning_labels'])),
            {'expected': list(profile['planning_labels']), 'observed': phases}, covered=bool(planning)))
    if profile['require_review_b']:
        required.append(goal('审核B局部修订与实际作者验证', any(h['coverage'] == 'passed' and h['acceptance'].get('outcome')
            in {'story_scope_and_origin_passed', 'resumed_story_scope_and_origin_passed'} for h in hybrid),
            covered=any('V12-story-' in h['label'] for h in hybrid)))
    if profile['name'] == 'V13':
        required.append(goal('四个指定图节点的生成与下载证据', images['coverage'] == 'passed', images,
            covered=bool(images.get('rows'))))
        required.append({'name': '一次专用身份视觉调用', 'status': identity_vision['status'], 'evidence': identity_vision})
        required.append({'name': '身份归档与四图/工具回执绑定', 'status': identity_archive['status'], 'evidence': identity_archive})
        required.append({'name': '双人身份一致性与多图完整性审读', 'status': 'needs_review',
            'evidence': 'Use the independent fixed identity-sample archive; counts alone do not prove image completeness or appearance.'})
    invalid_models = [r['id'] for r in physical if (r['kind'], r['model']) not in {('text', TEXT), ('vision', VISION)}]
    pending = [r['id'] for r in physical if r['status'] in {'unknown', 'reserved'}]
    media_log = work / 'mock-media.jsonl'
    if not media_log.resolve().is_relative_to(work):
        raise ValueError('Mock event log escapes this evaluation directory')
    events = [json.loads(line) for line in media_log.read_text(encoding='utf-8').splitlines() if line.strip()] if media_log.is_file() else []
    safety_good = limit == profile['marker']['call_limit'] and len(physical) <= limit and not invalid_models and not blocked and not pending and not any(row.get('kind') == 'blocked_real_media' for row in events)
    safety_status = 'failed' if not safety_good or images['status'] == 'failed' else images['status']
    return {'schema': 'cinecrew-eval-readonly-statistics-v2', 'profile': profile, 'read_at': datetime.now(timezone.utc).isoformat(),
        'work': str(work), 'read_mode': 'SQLite mode=ro + PRAGMA query_only=ON; independent read transactions',
        'totals': ledger_metrics(ledger, images), 'unique_runs': len(runs), 'required_coverage': required,
        'physical_audit': {'call_limit': limit, 'attempts': len(physical), 'by_kind': dict(Counter(r['kind'] for r in physical)),
            'by_model': dict(Counter(r['model'] for r in physical)), 'by_status': dict(Counter(r['status'] for r in physical)),
            'usage': usage(physical, physical=True), 'invalid_model_attempt_ids': invalid_models,
            'unknown_or_reserved_ids': pending, 'unmapped_attempt_ids': unmapped, 'blocked': blocked,
            'rows': physical}, 'reconciliation': reconcile(ledger, physical),
        'safety': {'status': safety_status, 'real_media_calls_observed': images['image_post_attempts'] if not invalid_models else None,
            'meaning': 'Chat audit plus selected image reservations/transport records; not independent packet capture.'},
        'real_images': images, 'identity_vision': identity_vision, 'identity_archive': identity_archive,
        'mock_media': {'event_counts': dict(Counter(row.get('kind') for row in events)), 'ledger_demo_credits': ledger_metrics(ledger, images)['mock_media_demo_credits'],
            'log_present': media_log.is_file(), 'attribution': 'Media ledger minus verified real-image invocation IDs and unresolved attribution; Mock event log has no per-invocation identity proof.'},
        'planning': planning, 'hybrid': hybrid, 'runs': evidence, 'diagnostics': diagnostics, 'data_quality_status': 'needs_review' if diagnostics else 'passed',
        'limitations': ['演示credits不是实际货币账单；包含非rejected的账本费用，pending/running预留单列。',
            'JSON归档仅提供阶段边界和验收证据；费用只从唯一数据库invocation计一次。',
            '逻辑调用次数包含被拒绝的Registry记录；真实次数以物理审计by_kind为准，不把Mock/Stub逻辑回执称为真实调用。',
            '规划总费用取首次成功submit_plan的账本ID边界，须与归档模型调用ID集合一致；否则不判成本目标通过。',
            '两个SQLite读事务不是跨文件原子快照，建议待worker停止后统计；在途差异需复核。',
            '物理尝试与逻辑调用按Run聚合对照，无共享response_id，不能证明逐次一一对应。',
            '风格、故事覆盖、角色语义与根因仍需人工审读；编译通过不等于内容或画质通过。',
            '历史固定反例是独立补测，不覆盖或改写本轮新Repair的真实结果。']}


def markdown(result):
    lines = [f"# {result['profile']['name']} 只读统计与验收证据", '', f"读取：{result['read_at']}；唯一 Run：{result['unique_runs']}。", '',
        '统计仅读取指定 profile 临时 SQLite 与归档；未读取.env、导入应用或调用模型。', '',
        '|账目|结果|', '|---|---:|',
        f"|真实物理尝试|{result['physical_audit']['attempts']} / {result['physical_audit']['call_limit']}|",
        f"|账本演示 credits|{result['totals']['accounted_demo_credits']}|",
        f"|LLM/视觉演示 credits|{result['totals']['llm_demo_credits']}|",
        f"|Mock 媒体演示 credits|{result['totals']['mock_media_demo_credits']}|",
        f"|真实图片演示 credits|{result['totals']['real_image_demo_credits']}|",
        f"|未归因媒体演示 credits|{result['totals']['unattributed_media_demo_credits']}|",
        f"|物理账本对照|{result['reconciliation']['status']}|", '',
        '|用例 / Run|状态|初始文本轮数|输入峰值 token|输入已知合计|输出已知合计|完整规划演示 credits|其中 LLM/视觉 credits|', '|---|---|---:|---:|---:|---:|---:|---:|']
    for row in result['planning']:
        m = row['metrics']
        planning_cost = m['planning_accounted_demo_credits'] if m['planning_cost_slice_verified'] else '未核验'
        lines.append(f"|{row['label']} / {row['run_id']}|{row['status']}|{m['text']['calls']}|{m['text']['input_tokens_max']}|{m['all_model_usage']['input_tokens_known_sum']}|{m['all_model_usage']['output_tokens_known_sum']}|{planning_cost}|{m['llm_demo_credits']}|")
    lines.extend(['', '## 目标', ''])
    for item in result['required_coverage']:
        lines.append(f"- {item['status']}：{item['name']}。")
    for row in result['planning']:
        for item in row['goals']:
            lines.append(f"- {item['status']}：{row['label']} / {row['run_id']}：{item['name']}。")
    lines.extend(['', '## 混合执行', ''])
    for row in result['hybrid']:
        lines.append(f"- {row['label']}：归档状态 {row['status']}；控制流 {row['coverage']}；人工分支 {row['manual_intent_path']}；原结果 {row['acceptance'].get('outcome')}。")
    lines.extend(['', '## 中间失败与根因证据', ''])
    for row in result['runs']:
        for item in row['failure_evidence']:
            lines.append(f"- {row['run_id']} / `{item['code']}`：{item['observed_cause']} 位置 `{json.dumps(item['source'], ensure_ascii=False)}`；根因待审读。")
    if not any(row['failure_evidence'] for row in result['runs']):
        lines.append('未发现已记录的中间失败；没有记录不代表评测已覆盖。')
    lines.extend(['', '## 服务商结束原因（独立观察）', ''])
    for row in result['runs']:
        for item in row['model_finish_reasons']:
            lines.append(f"- {row['run_id']} / `{item['invocation_id']}`：finish_reason=`{item['finish_reason']}`；这是原始观察，不合成生产错误码。")
    if not any(row['model_finish_reasons'] for row in result['runs']):
        lines.append('未记录 finish_reason；不据此认定没有截断。')
    lines.extend(['', '## 数据诊断', '', '```json', json.dumps(result['diagnostics'], ensure_ascii=False, indent=2), '```', '', '## 限制', ''])
    lines.extend('- ' + text for text in result['limitations'])
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', required=True)
    parser.add_argument('--profile', choices=('V12', 'V13'), required=True)
    parser.add_argument('--snapshot-name', default='readonly-statistics-v2')
    args = parser.parse_args()
    if not re.fullmatch(r'readonly-statistics-v2(?:-[A-Za-z0-9_-]{1,64})?', args.snapshot_name):
        raise ValueError('Snapshot name must be a dedicated versioned statistics directory')
    result = summarize(args.work, args.profile)
    destination = checked_work(args.work, args.profile) / args.snapshot_name
    if not destination.resolve().is_relative_to(checked_work(args.work, args.profile)):
        raise ValueError('Output must stay inside this temporary round')
    destination.mkdir(exist_ok=True)
    basename = args.profile.lower() + '-statistics'
    if any(not (destination / name).resolve().is_relative_to(destination.resolve()) for name in (basename + '.json', basename + '.md')):
        raise ValueError('Output file escapes its statistics directory')
    if any((destination / (basename + suffix)).exists() for suffix in ('.json', '.md')):
        raise FileExistsError('Preserve existing statistics; use a new dedicated snapshot directory')
    (destination / (basename + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (destination / (basename + '.md')).write_text(markdown(result), encoding='utf-8')
    print(json.dumps({'work': result['work'], 'runs': result['unique_runs'], 'physical_attempts': result['physical_audit']['attempts'],
        'safety': result['safety']['status'], 'diagnostics': len(result['diagnostics']), 'output': str(destination)}))


if __name__ == '__main__':
    main()
