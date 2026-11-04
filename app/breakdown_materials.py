"""Reusable, source-grounded details added to the original breakdown schema."""
from __future__ import annotations
from typing import Any
import re


def normalize_details(value: dict[str, Any], transcript: str | None = None) -> dict[str, Any]:
    # Missing fields mean a historical analysis, not evidence of an absent CTA.
    if 'hookQuote' not in value and 'cta' not in value:
        return {}
    quote = value.get('hookQuote')
    cta = value.get('cta')
    if not isinstance(quote, str) or not quote.strip() or len(quote) > 400:
        raise ValueError('开头原文无效。')
    if not isinstance(cta, dict) or set(cta) != {'present', 'quote', 'type', 'explanation'}:
        raise ValueError('结尾分析无效。')
    if type(cta['present']) is not bool:
        raise ValueError('结尾引导状态无效。')
    for field in ('quote', 'type', 'explanation'):
        if not isinstance(cta[field], str) or len(cta[field]) > 400:
            raise ValueError('结尾分析内容无效。')
    if cta['present'] and not all(cta[key].strip() for key in ('quote', 'type', 'explanation')):
        raise ValueError('结尾引导缺少原文或说明。')
    if not cta['present'] and cta['quote'].strip():
        raise ValueError('无结尾引导时不能包含引导原文。')
    if transcript is not None:
        compact = lambda text: re.sub(r'[\W_]+', '', text, flags=re.UNICODE).lower()
        source = compact(transcript)
        for text in (quote, cta['quote'] if cta['present'] else ''):
            if text and (not compact(text) or compact(text) not in source):
                raise ValueError('引用内容不在视频原文中。')
    summary = value.get('structureSummary', '')
    if not isinstance(summary, str) or len(summary) > 200:
        raise ValueError('视频结构总结无效。')
    result = {'structureSummary': summary.strip(), 'hookQuote': quote.strip(), 'cta': {key: val.strip() if isinstance(val, str) else val for key, val in cta.items()}}

    if 'templates' in value:
        templates = value['templates']
        if not isinstance(templates, dict) or set(templates) != {'hook', 'structure', 'ending'}:
            raise ValueError('模板草稿不完整。')
        normalized = {}
        for kind in ('hook', 'structure', 'ending'):
            draft = templates[kind]
            if kind == 'ending' and not cta['present']:
                if draft is not None:
                    raise ValueError('无结尾引导时不能生成结尾模板。')
                normalized[kind] = None
                continue
            compact_fields = {'name', 'content', 'note'} if kind == 'structure' else {'name', 'content'}
            if not isinstance(draft, dict) or set(draft) not in (compact_fields, {'name', 'content', 'note', 'example'}):
                raise ValueError('模板草稿字段无效。')
            if set(draft) == compact_fields:
                # Expand only the compact contract; validate legacy supplied values unchanged.
                draft = {**draft, 'example': '' if kind == 'structure' else (quote.strip() if kind == 'hook' else cta['quote'].strip())}
                if kind != 'structure':
                    draft['note'] = draft['content']
            cleaned = {}
            for field, limit in [('name', 20), ('content', 2000), ('note', 400), ('example', 400)]:
                text = draft[field]
                if not isinstance(text, str) or len(text.strip()) > limit:
                    raise ValueError('模板草稿字段过长或无效。')
                cleaned[field] = text.strip()
            if not cleaned['name'] or not cleaned['content'] or '\n' in cleaned['name']:
                raise ValueError('模板名称和内容不能为空。')
            if kind == 'structure':
                if cleaned['example'] or not 2 <= len([x for x in cleaned['content'].split('→') if x.strip()]) <= 12:
                    raise ValueError('结构模板应包含2到12个通用环节。')
            else:
                expected = quote.strip() if kind == 'hook' else cta['quote'].strip()
                if cleaned['example'] != expected:
                    raise ValueError('模板示例必须使用对应的逐字原文。')
                if cleaned['content'] != cleaned['note'] or not cleaned['note']:
                    raise ValueError('开头和结尾模板的内容应与说明一致。')
            normalized[kind] = cleaned
        result['templates'] = normalized
    return result
