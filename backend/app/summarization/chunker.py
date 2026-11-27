from dataclasses import dataclass


@dataclass
class TranscriptChunk:
    chunk_index: int
    text: str
    start_position: int
    end_position: int


def chunk_transcript(
    text: str,
    chunk_size: int = 12000,
    overlap: int = 1000
) -> list[TranscriptChunk]:

    if chunk_size <= overlap:
        raise ValueError(
            "chunk_size must be greater than overlap"
        )

    if not text.strip():
        return []

    chunks = []

    start = 0
    index = 1
    text_length = len(text)

    while start < text_length:

        end = min(
            start + chunk_size,
            text_length
        )

        # Prefer paragraph boundaries.
        if end < text_length:
            boundary = text.rfind(
                "\n\n",
                start + chunk_size // 2,
                end
            )

            if boundary > start:
                end = boundary

        content = text[start:end].strip()

        if content:
            chunks.append(
                TranscriptChunk(
                    chunk_index=index,
                    text=content,
                    start_position=start,
                    end_position=end
                )
            )

            index += 1

        if end >= text_length:
            break

        start = end - overlap

    return chunks