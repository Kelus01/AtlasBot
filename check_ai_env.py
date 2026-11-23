import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI


ROOT_DIR = Path(__file__).parent


def get_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} не задано у .env")
    return value


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    load_dotenv(ROOT_DIR / ".env")

    try:
        base_url = get_required("LLM_BASE_URL")
        api_key = get_required("LLM_API_KEY")
        model = get_required("LLM_MODEL")
        timeout = float(os.getenv("LLM_TIMEOUT", "30"))
    except (RuntimeError, ValueError) as exc:
        print(f"Конфігурація помилкова: {exc}")
        return

    print(f"Перевірка моделі: {model}")
    print(f"Ендпоінт: {base_url}")
    print(f"Ключ задано: {'так' if api_key else 'ні'}")

    started = time.perf_counter()
    client = OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=timeout,
        max_retries=0,
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": "Відповідь одним словом: перевірка."}
            ],
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "600")),
            temperature=0,
        )
        elapsed = round(time.perf_counter() - started, 3)
        answer = response.choices[0].message.content if response.choices else None
        finish_reason = response.choices[0].finish_reason if response.choices else None
        print("Перевірка успішна")
        print(f"Час: {elapsed:.3f} c")
        print(f"Модель: {model}")
        print(f"Відповідь: {answer}")
        print(f"Причина завершення: {finish_reason}")
        print(f"Usage: {getattr(response, 'usage', None)}")
    except APITimeoutError as exc:
        print(f"Таймаут: {exc}")
    except APIConnectionError as exc:
        print(f"Помилка з'єднання: {exc}")
    except APIStatusError as exc:
        print(
            f"HTTP помилка: status={exc.status_code}, "
            f"code={getattr(exc, 'code', None)}, body={getattr(exc, 'body', None)!r}"
        )
    except Exception as exc:
        print(f"Неочікувана помилка: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
