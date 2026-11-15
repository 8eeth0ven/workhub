"""Bounded, source-backed reference notes. README claims are evidence, not verified features."""
import re


def safe_text(value, limit=1000):
    text = str(value or '')[:65536]
    patterns = [r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-(?:proj-|ant-api\d*-)?[A-Za-z0-9_-]{20,})\b',
                r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',r'\bxox[baprs]-[A-Za-z0-9-]{20,}\b',
                r'(?i)\bBearer\s+\S+', r'(?i)(?:https?|ssh)://[^\s/@]+@[^\s]+',
                r'(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret)["\']?\s*[:=]\s*["\']?[^\s,"\'<>]+',
                r'(?i)[A-Z]:[\\/](?:Users|Documents and Settings)[\\/][^\s<>"\']+',
                r'/(?:Users|home)/[^\s<>"\']+', r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b']
    text = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----', '[redacted]', text)
    for pattern in patterns:
        text = re.sub(pattern, '[redacted]', text)
    return text[:limit]


# A match is a documentation lead. Actions remain bounded experiments in existing details.
FEATURES = [
    ('handoff', '会话衔接', 'Session continuity', r'\bhandoff\b|\bresume (?:a |the )?session|会话衔接|恢复会话|会话绑定',
     '核对客户端会话标识与恢复协议，在项目详情试做一个手动继续入口，并验证跨项目不会串会话。',
     'Check session IDs and the resume protocol; prototype one manual resume action in project details and test project isolation.'),
    ('events', '事件驱动状态', 'Event-driven status', r'event[- ]driven|event stream|websocket|server.sent.events|事件驱动|事件订阅|宿主事件',
     '先确认客户端可用的事件接口，在现有详情试做只读状态摘要，验证断线恢复和过期标记。',
     'Confirm an available event API; prototype a read-only status summary in existing details and test reconnects and stale states.'),
    ('worktree', '隔离工作区', 'Isolated workspaces', r'\bworktrees?\b|隔离工作区',
     '检查当前目录与分支关联方式，先增加只读工作区提示，验证分支切换后来源仍准确。',
     'Inspect directory-to-branch mapping; first add a read-only workspace hint and verify it after branch changes.'),
    ('approval', '人工审批', 'Human approval', r'human.in.the.loop|approval gate|permission gate|人工审批|审批门槛|权限确认',
     '列出确需人工批准的写入动作，在原有操作处试做一次确认并验证取消后没有副作用。',
     'Identify writes that need approval; prototype confirmation at the existing action and test that cancellation has no side effects.'),
    ('search', '搜索与定位', 'Search and navigation', r'full.text search|semantic search|全文检索|语义搜索|全文搜索',
     '选少量公开样本，在现有搜索框验证关键词召回、来源定位与空结果，再决定是否扩展索引。',
     'Use a small public fixture to test recall, source navigation and empty results in the existing search box before expanding the index.'),
    ('schedule', '定时任务', 'Scheduled tasks', r'\bcron\b|\bschedul(?:e|ed|ing)\b|定时检索|定时任务|周期调度',
     '对照调度的去重、关闭、失败保留和重启行为，先补最薄弱的一项并用同一配置复测。',
     'Compare deduplication, disabling, failure retention and restart behavior; improve the weakest case and retest with the same configuration.'),
    ('plugins', '扩展接口', 'Extension interfaces', r'\bplugins?\b|\bMCP\b|插件|扩展接口',
     '先确认协议和权限边界，用一个只读适配器接入现有项目详情，验证超时和不兼容时的降级。',
     'Confirm protocol and permission boundaries; try one read-only adapter in existing details and test timeout and incompatibility fallbacks.'),
    ('multi', '多项目组织', 'Multi-project organization', r'multi.project|project.switch|多项目|切换项目|项目集中',
     '用多个项目测试选择、筛选与草稿保留，只把能减少切换成本的改动并入现有项目列表。',
     'Test selection, filtering and draft retention across projects; add only changes that reduce switching effort to the existing list.'),
    ('terminal', '终端协作', 'Terminal collaboration', r'\bterminal\b|\bPTY\b|终端|分栏',
     '先验证能否安全打开已有客户端会话；只有确有需要时再试单项目入口，并测试目录与权限隔离。',
     'First verify safe access to an existing client session; try a single-project entry only if needed and test directory and permission isolation.'),
    ('provenance', '来源与证据', 'Sources and evidence', r'provenance|audit trail|evidence|证据|溯源|来源记录',
     '选一条结论，从详情追溯到来源、读取时间和版本，补齐无法复现的环节后再验证一次。',
     'Trace one conclusion from details to its source, retrieval time and version; fill gaps and reproduce the check.'),
]


def extract(profile):
    matches = {}
    fence = None
    planned_level = None
    for index, raw in enumerate(profile.get('readme', '').splitlines()):
        line = safe_text(raw, 360).strip()
        marker = re.match(r'^(`{3,}|~{3,})',line)
        if marker:
            if fence is None:fence=marker[1][0]
            elif fence==marker[1][0]:fence=None
            continue
        if fence:continue
        heading=re.match(r'^(#{1,6})\s+(.+)',line)
        if heading:
            level=len(heading[1])
            if planned_level is not None and level<=planned_level:planned_level=None
            if re.search(r'roadmap|future|planned|计划|待实现|未来',heading[2],re.I):planned_level=level
        if planned_level is not None:continue
        # Avoid treating installation commands, badges and explicitly negative statements as capability claims.
        if not line or line.startswith(('```', '~~~', '![', '<', '$ ', 'pip ', 'npm ', 'git ')):
            continue
        if re.search(r'not (?:yet |currently )?(?:support|implement)|does not|unsupported|不支持|未实现|尚未|计划|roadmap|planned|todo', line, re.I):
            continue
        for feature in FEATURES:
            key=feature[0]
            if key not in matches and re.search(feature[3], line, re.I):
                matches[key] = {'text': line, 'url': profile.get('readme_url'), 'line': index + 1, 'kind': 'readme', 'sha': profile.get('readme_sha')}
    for feature in FEATURES:
        if feature[0] not in matches and not re.search(r'not support|does not|unsupported|不支持|未实现|计划|roadmap|planned',profile.get('description',''),re.I) and re.search(feature[3], profile.get('description', ''), re.I):
            matches[feature[0]] = {'text': safe_text(profile['description'], 360), 'url': profile.get('url'), 'kind': 'description'}
    return matches


def compare(reference, baseline, focus=''):
    external, own = extract(reference), extract(baseline)
    focus_profile = {'description': focus}
    focus_keys = extract(focus_profile)
    features = sorted(FEATURES, key=lambda item: (item[0] not in focus_keys, item[0] in own))
    notes = []
    for key, zh, en, _pattern, action_zh, action_en in features:
        if key not in external:
            continue
        if key in own:
            difference = {'zh': f'双方材料都提到{zh}；实现方式与实际效果仍需对照。', 'en': f'Both sources mention {en.lower()}; implementation and effectiveness still need comparison.'}
            state = 'shared_claim'
        elif baseline.get('readme') or baseline.get('description') or focus:
            difference = {'zh': f'参考材料提到{zh}，本项目本次材料未见对应说明；不等于没有实现。', 'en': f'The reference mentions {en.lower()}; the current project material does not document it. This does not establish a missing implementation.'}
            state = 'not_documented'
        else:
            difference = {'zh': '缺少本项目公开资料，暂不能判断实现差别；可补充项目定位或关联公开仓库。', 'en': 'No public baseline is available; add project focus or connect a public repository before judging differences.'}
            state = 'unknown'
        notes.append({'feature': key, 'title': {'zh': zh, 'en': en},
                      'benefit': {'zh': f'可研究其{zh}做法，先核对下方材料声明。', 'en': f'Study its approach to {en.lower()}, starting with the source claim below.'},
                      'difference': difference, 'next_step': {'zh': action_zh, 'en': action_en},
                      'state': state, 'evidence': external[key], 'baseline_evidence': own.get(key)})
        if len(notes) == 3:
            break
    return {'method': 'documentation_rules_v1', 'notes': notes,
            'coverage': 'readme' if reference.get('readme') else 'description',
            'readme_status': reference.get('readme_status', 'not_read'),
            'truncated': bool(reference.get('truncated')),
            'observed_at': reference.get('observed_at'), 'readme_sha': reference.get('readme_sha'),
            'license': safe_text(reference.get('license'), 80)}
