"""Read-only presentation enrichment; never changes billing records or cached rows."""
from copy import deepcopy


def enrich_monitor_labels(result, lookup):
    result = deepcopy(result)
    authors = {}
    for row in result.get("items", []):
        context = row.get("businessContext") or {}
        if context.get("source") != "monitor":
            continue
        identity = str(context.get("targetId") or "")
        if not identity or (context.get("targetName") and context.get("targetHandle")):
            continue
        if identity not in authors:
            authors[identity] = lookup(identity) or {}
        author = authors[identity]
        for target, field in (("targetName", "nickname"), ("targetHandle", "uniqueId")):
            if not context.get(target) and author.get(field):
                context[target] = str(author[field])
    return result
