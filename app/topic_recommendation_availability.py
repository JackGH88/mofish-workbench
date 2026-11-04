"""Reversible product pause; account settings and stored jobs remain untouched."""
from fastapi import HTTPException

TOPIC_RECOMMENDATIONS_PAUSED = True


def require_available():
    if TOPIC_RECOMMENDATIONS_PAUSED:
        raise HTTPException(status_code=503, detail={
            "code": "topic_recommendations_paused",
            "message": "选题推荐已暂停",
        })
