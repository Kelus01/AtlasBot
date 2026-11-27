"""Gemini/OpenAI-сумісний помічник техпідтримки."""

import asyncio
import logging
import math
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI


ROOT_DIR = Path(__file__).resolve().parent.parent
CONTEXT_FILE = Path(__file__).resolve().parent / "context.md"

load_dotenv(ROOT_DIR / ".env")
logger = logging.getLogger(__name__)

MAX_RETRIES = 2
RETRY_DELAYS = (1.0, 2.5)


class SupportAIError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _setting(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        logger.error("Помічник AI: не задано змінну середовища %s", name)
        raise SupportAIError("Помічник тимчасово не налаштований.")
    return value


def _number_setting(name: str, default: str, *, minimum: float) -> float:
    try:
        value = float(os.getenv(name, default))
    except ValueError as exc:
        raise SupportAIError("Параметри помічника налаштовані некоректно.") from exc
    if not math.isfinite(value) or value < minimum:
        raise SupportAIError("Параметри помічника налаштовані некоректно.")
    return value


def _client() -> OpenAI:
    return OpenAI(
        base_url=_setting("LLM_BASE_URL"),
        api_key=_setting("LLM_API_KEY"),
        timeout=_number_setting("LLM_TIMEOUT", "30", minimum=0.01),
        max_retries=0,
    )


def _load_context() -> str:
    try:
        return CONTEXT_FILE.read_text(encoding="utf-8")
    except OSError as exc:
        raise SupportAIError("Не вдалося завантажити базу знань.") from exc


def _call_model(question: str, history: list[dict[str, str]]) -> tuple[str, str, float]:
    model = _setting("LLM_MODEL")
    base_url = _setting("LLM_BASE_URL")
    logger.info(
        "AI: початок запиту | model=%s | base_url=%s | question_chars=%d",
        model,
        base_url,
        len(question),
    )
    temperature = _number_setting("LLM_TEMPERATURE", "0.2", minimum=0)
    if temperature > 2:
        raise SupportAIError("Параметр temperature налаштований некоректно.")

    try:
        max_tokens = int(os.getenv("LLM_MAX_TOKENS", "600"))
    except ValueError as exc:
        raise SupportAIError("Параметр max_tokens налаштований некоректно.") from exc
    if max_tokens < 1:
        raise SupportAIError("Параметр max_tokens налаштований некоректно.")

    try:
        budget = int(os.getenv("LLM_TOKEN_BUDGET", "3000"))
    except ValueError as exc:
        raise SupportAIError("Бюджет токенів налаштований некоректно.") from exc
    if budget < 500:
        raise SupportAIError("Бюджет токенів налаштований некоректно.")

    context = _load_context()
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "Ти — ШІ-асистент техпідтримки Minecraft-сервера Testia. "
                "Відповідай коротко та українською, спирайся на базу знань і не "
                "вигадуй дані. Спершу використовуй уже надану інформацію, став не "
                "більше двох уточнювальних питань за раз і пропонуй практичні "
                "безпечні кроки. Для проблем запуску, підключення чи вильотів "
                "з'ясовуй, чи є моди; якщо так — які саме, версію Minecraft і "
                "завантажувача. Не радь ризикованих змін без резервної копії. "
                "Уважно враховуй усю передану історію чату, включно з відповідями "
                "в embed-повідомленнях. Перед кожним уточненням перевір, чи користувач "
                "вже відповів на це раніше. Вважай негативні відповіді (наприклад, "
                "«ще не пробував») повноцінною інформацією та не став те саме питання "
                "знову; запитай лише про результат нового кроку, який сам запропонував. "
                "Якщо не можеш допомогти, потрібна перевірка "
                "адміністратора або відповідь відсутня в базі знань, прямо порадь "
                "натиснути кнопку «Почекати адміністратора» під повідомленням. "
                "Обмежуй кожну відповідь приблизно 1500 символами. Нумеровані пункти "
                "розділяй окремими рядками, не обрізай питання всередині."
            ),
        },
        {
            "role": "user",
            "content": "Правила техпідтримки:\n\n<rules>\n" + context + "\n</rules>",
        },
    ]

    estimated_tokens = sum(max(1, (len(str(turn["content"])) + 3) // 4) for turn in history)
    while estimated_tokens > budget and len(history) > 1:
        history = history[1:]
        estimated_tokens = sum(
            max(1, (len(str(turn["content"])) + 3) // 4) for turn in history
        )

    messages.extend(history)
    messages.append({"role": "user", "content": question})

    started = time.perf_counter()
    completion = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            completion = _client().chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            break
        except APITimeoutError as exc:
            logger.warning(
                "AI: таймаут | attempt=%d/%d | %s",
                attempt + 1,
                MAX_RETRIES + 1,
                exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAYS[attempt])
                continue
            logger.error("AI: перевищено час очікування після повторів: %s", exc)
            raise SupportAIError("Час очікування відповіді минув.") from exc
        except APIConnectionError as exc:
            logger.warning(
                "AI: помилка з'єднання | attempt=%d/%d | %s",
                attempt + 1,
                MAX_RETRIES + 1,
                exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAYS[attempt])
                continue
            logger.error("AI: помилка з'єднання після повторів: %s", exc)
            raise SupportAIError("Не вдалося з'єднатися із сервісом AI.") from exc
        except APIStatusError as exc:
            logger.error(
                "AI: HTTP помилка | status=%s | code=%s | body=%r",
                exc.status_code,
                getattr(exc, "code", None),
                getattr(exc, "body", None),
            )
            if exc.status_code in (429, 503) and attempt < MAX_RETRIES:
                retry_delay = RETRY_DELAYS[attempt]
                logger.warning(
                    "AI: тимчасова помилка %s, повтор через %.1f c",
                    exc.status_code,
                    retry_delay,
                )
                time.sleep(retry_delay)
                continue
            if exc.status_code == 429:
                raise SupportAIError(
                    "Забагато запитів до AI-сервісу. Спробуйте трохи пізніше."
                ) from exc
            if exc.status_code == 503:
                raise SupportAIError(
                    "Модель тимчасово перевантажена. Спробуйте ще раз через хвилину."
                ) from exc
            raise SupportAIError("Сервіс AI тимчасово недоступний.") from exc
        except Exception as exc:
            logger.exception("AI: неочікувана помилка виклику моделі")
            raise SupportAIError("Сервіс AI тимчасово недоступний.") from exc

    if completion is None:
        raise SupportAIError("Сервіс AI тимчасово недоступний.")

    if not completion.choices:
        logger.error("AI: провайдер повернув порожній choices")
        raise SupportAIError("Модель не повернула відповідь.")
    choice = completion.choices[0]
    answer = choice.message.content
    logger.info(
        "AI: finish_reason=%r | prompt_tokens=%r",
        getattr(choice, "finish_reason", None),
        getattr(getattr(completion, "usage", None), "prompt_tokens", None),
    )
    if not isinstance(answer, str) or not answer.strip():
        logger.error("AI: провайдер повернув порожній або не текстовий answer")
        raise SupportAIError("Модель повернула порожню відповідь.")

    elapsed = round(time.perf_counter() - started, 3)
    logger.info(
        "AI: успішна відповідь | model=%s | elapsed=%.3f c | usage=%r",
        model,
        elapsed,
        getattr(completion, "usage", None),
    )
    return answer.strip(), model, elapsed


async def ask_support(
    question: str,
    history: list[dict[str, str]] | None = None,
) -> tuple[str, str, float]:
    """Викликати модель поза циклом event loop Discord."""
    return await asyncio.to_thread(_call_model, question, history or [])
