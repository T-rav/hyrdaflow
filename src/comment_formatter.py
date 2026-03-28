"""GitHub comment body formatting — chunking and hard-truncation."""

from __future__ import annotations


class CommentFormatter:
    """GitHub comment body formatting — chunking and hard-truncation."""

    GITHUB_COMMENT_LIMIT: int = 65_536  # GitHub maximum comment body size
    TRUNCATION_MARKER: str = "\n\n*...truncated to fit GitHub comment limit*"

    @staticmethod
    def chunk(body: str, limit: int | None = None) -> list[str]:
        """Split *body* into chunks that fit within *limit* characters."""
        if limit is None:
            limit = CommentFormatter.GITHUB_COMMENT_LIMIT
        if len(body) <= limit:
            return [body]
        chunks: list[str] = []
        while body:
            if len(body) <= limit:
                chunks.append(body)
                break
            split_at = body.rfind("\n", 0, limit)
            if split_at <= 0:
                split_at = limit
            chunks.append(body[:split_at])
            body = body[split_at:].lstrip("\n")
        return chunks

    @staticmethod
    def cap(body: str, limit: int | None = None) -> str:
        """Hard-truncate *body* to *limit* characters.

        Acts as a safety net after chunking / header prepending to guarantee
        no single payload exceeds GitHub's comment size limit.
        """
        if limit is None:
            limit = CommentFormatter.GITHUB_COMMENT_LIMIT
        if len(body) <= limit:
            return body
        marker = CommentFormatter.TRUNCATION_MARKER
        return body[: limit - len(marker)] + marker


class SelfReviewError(RuntimeError):
    """Raised when a formal review fails due to the 'own pull request' restriction."""
