"""Event bus: in-process for local/tests, Pub/Sub on GCP."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable
from typing import Protocol

from ..config import Settings
from ..domain.models import Event, Notification

Handler = Callable[[Event], None]


class EventBus(Protocol):
    def publish(self, event: Event) -> None: ...
    def publish_notification(self, n: Notification) -> None: ...


class InMemoryBus:
    """Dispatches iteratively (queue) so follow-on events never recurse deeply."""

    def __init__(self) -> None:
        self._handler: Handler | None = None
        self._queue: deque[Event] = deque()
        self._draining = False
        self.notifications: list[Notification] = []
        self.published: list[Event] = []

    def subscribe(self, handler: Handler) -> None:
        self._handler = handler

    def publish(self, event: Event) -> None:
        self.published.append(event)
        self._queue.append(event)
        if self._draining or self._handler is None:
            return
        self._draining = True
        try:
            while self._queue:
                self._handler(self._queue.popleft())
        finally:
            self._draining = False

    def publish_notification(self, n: Notification) -> None:
        self.notifications.append(n)


class PubSubBus:
    """Publishes to ``{prefix}-events`` / ``{prefix}-notifications``; the worker consumes via push."""

    def __init__(self, settings: Settings) -> None:
        from google.cloud import pubsub_v1

        self._pub = pubsub_v1.PublisherClient()
        project = settings.gcp_project
        self._events = self._pub.topic_path(project, f"{settings.pubsub_topic_prefix}-events")
        self._notifications = self._pub.topic_path(project, f"{settings.pubsub_topic_prefix}-notifications")

    def publish(self, event: Event) -> None:
        self._pub.publish(
            self._events,
            event.model_dump_json().encode(),
            tenant_id=event.tenant_id,
            project_id=event.project_id,
            event_type=event.type,
        ).result(timeout=30)

    def publish_notification(self, n: Notification) -> None:
        self._pub.publish(
            self._notifications, n.model_dump_json().encode(), tenant_id=n.tenant_id, recipient=n.recipient
        ).result(timeout=30)


def decode_push_envelope(body: dict) -> dict:
    """Decode a Pub/Sub push request body into its JSON message data."""
    import base64

    msg = body.get("message") or {}
    raw = base64.b64decode(msg.get("data", "") or b"")
    data = json.loads(raw) if raw else {}
    data.setdefault("_attributes", msg.get("attributes", {}))
    return data
