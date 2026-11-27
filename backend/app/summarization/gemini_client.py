import json
import logging
import time

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)


class GeminiSummarizer:
    def __init__(self):
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is missing from .env")

        # Timeout is in milliseconds.
        http_options = types.HttpOptions(timeout=120_000)

        self.client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=http_options,
        )
        self.model = settings.gemini_model

    @staticmethod
    def is_retryable(exc: Exception) -> bool:
        message = str(exc).lower()
        status_code = getattr(exc, "code", None)

        retryable_codes = {408, 429, 500, 502, 503, 504}

        if status_code in retryable_codes:
            return True

        retryable_messages = [
            "503",
            "429",
            "500",
            "502",
            "504",
            "unavailable",
            "resource exhausted",
            "rate limit",
            "timeout",
            "timed out",
            "temporarily",
            "connection reset",
        ]

        return any(term in message for term in retryable_messages)

    def generate_structured(
        self,
        prompt: str,
        response_schema: type[BaseModel],
        retries: int = 5,
    ) -> BaseModel:

        last_error = None

        for attempt in range(retries):
            try:
                logger.info(
                    "Sending request to Gemini model %s (attempt %s/%s)",
                    self.model,
                    attempt + 1,
                    retries,
                )

                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        response_mime_type="application/json",
                        response_schema=response_schema,
                    ),
                )

                if not response.text:
                    raise ValueError("Gemini returned an empty response")

                data = json.loads(response.text)
                result = response_schema.model_validate(data)

                logger.info("Gemini response received successfully")
                return result

            except Exception as exc:
                last_error = exc

                logger.warning(
                    "Gemini attempt %s/%s failed: %s",
                    attempt + 1,
                    retries,
                    exc,
                )

                if not self.is_retryable(exc):
                    logger.error(
                        "Non-retryable Gemini error. Stopping retries."
                    )
                    break

                if attempt < retries - 1:
                    delay = min(10 * (2 ** attempt), 60)

                    logger.warning(
                        "Retrying Gemini request in %s seconds...",
                        delay,
                    )
                    time.sleep(delay)

        raise RuntimeError(
            f"Gemini generation failed after {retries} attempts: {last_error}"
        )