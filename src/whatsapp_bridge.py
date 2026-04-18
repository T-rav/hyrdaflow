"""WhatsApp Business API bridge for Shape conversation notifications."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("hydraflow.whatsapp")

_ISSUE_NUMBER_RE = re.compile(r"#(\d+)")


class WhatsAppBridge:
    """Sends and receives Shape conversation messages via WhatsApp Business API.

    Outbound: Posts condensed turn summaries with artifact links.
    Inbound: Parses webhook payloads and extracts issue numbers + response text.
    """

    def __init__(
        self,
        phone_id: str,
        token: str,
        recipient: str,
    ) -> None:
        self._phone_id = phone_id
        self._token = token
        self._recipient = recipient
        self._message_ids: dict[int, str] = {}  # issue_number → last wa message id

    async def send_shape_turn(
        self,
        issue_number: int,
        title: str,
        summary: str,
        artifact_url: str,
    ) -> None:
        """Send a shape turn notification via WhatsApp."""
        message = (
            f"🔷 Shape #{issue_number}: {title}\n\n"
            f"{summary}\n\n"
            f"📎 View directions: {artifact_url}\n\n"
            f"Reply to continue the conversation, "
            f"or say 'ship it' to finalize."
        )
        msg_id = await self._send_message(message)
        if msg_id:
            self._message_ids[issue_number] = msg_id

    async def _send_message(self, text: str) -> str | None:
        """Send a text message via WhatsApp Cloud API.

        Returns the message ID on success, None on failure.
        """
        try:
            import httpx  # noqa: PLC0415

            url = f"https://graph.facebook.com/v21.0/{self._phone_id}/messages"
            headers = {
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            }
            payload = {
                "messaging_product": "whatsapp",
                "to": self._recipient,
                "type": "text",
                "text": {"body": text},
            }
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                messages = data.get("messages") or []
                if not messages:
                    return None
                return messages[0].get("id")
        except Exception:
            logger.warning("WhatsApp send failed", exc_info=True)
            return None

    @staticmethod
    def parse_webhook(payload: dict) -> tuple[str, int | None]:
        """Parse a WhatsApp webhook payload into (text, issue_number).

        Returns the message text and extracted issue number (if found).
        The issue number is parsed from #N patterns in the conversation context.
        """
        text = ""
        try:
            entries = payload.get("entry") or []
            if not entries:
                return text, None
            entry = entries[0]
            changes = entry.get("changes") or []
            if not changes:
                return text, None
            value = changes[0].get("value", {})
            messages = value.get("messages", [])
            if messages:
                text = messages[0].get("text", {}).get("body", "")
        except (KeyError, TypeError):
            pass

        issue_number = None
        match = _ISSUE_NUMBER_RE.search(text)
        if match:
            issue_number = int(match.group(1))

        return text, issue_number

    @staticmethod
    def format_condensed_summary(content: str, max_length: int = 300) -> str:
        """Condense agent output for WhatsApp (shorter, no markdown tables)."""
        # Strip markdown formatting
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", content)  # bold
        text = re.sub(r"#{1,3}\s+", "", text)  # headers
        text = re.sub(r"\n{3,}", "\n\n", text)  # excessive newlines
        if len(text) > max_length:
            text = text[:max_length].rsplit(" ", 1)[0] + "..."
        return text.strip()
