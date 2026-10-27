# Підключення Retell AI

Тільки синтетичні дані: не підключайте реальних пацієнтів до оформлення договорів, згоди та політик зберігання.

## 0. Що потрібно

- Акаунт на retellai.com (на старті дають безкоштовні кредити).
- Запущений backend (`docker compose up --build` або `uvicorn`), `/health` повертає `ok: true`.
- Публічний HTTPS URL на ваш `127.0.0.1:8000` на час тесту (будь-який tunnel, наприклад cloudflared чи ngrok). Далі він позначений як `https://<host>`. Вимкніть tunnel після демо.

## 1. API key

1. Dashboard → **Settings → API Keys**.
2. Візьміть ключ, біля якого стоїть позначка **webhook**. Тільки цим ключем Retell підписує запити (`X-Retell-Signature`).
3. Запишіть його в `.env`: `RETELL_API_KEY=...` і перезапустіть backend.

## 2. Агент

1. **Agents → Create agent → Single Prompt Agent** (Retell LLM).
2. **Language:** Ukrainian (`uk-UA`).
3. **Voice:** оберіть голос, послухайте на українській. `TODO(verify-retell)`: перевірити кілька голосів, якість у різних провайдерів відрізняється.
4. **LLM model:** наприклад `gpt-4.1` (якісніше) або `gpt-4.1-mini` (дешевше). Перевірте, як модель тримає сценарій українською.
5. **Global Prompt:** вставте повний текст `prompts/olena_system_prompt.md`.
6. **Welcome message / Begin message:** «Вітаю, це Клініка флебології. Розмова записується. Мене звати Олена, я віртуальний асистент. Чим можу допомогти?» Хто говорить першим: агент. Юридичне формулювання про запис має погодити юрист.

## 3. Tools (Functions)

### End Call
Додайте **End Call** і назвіть його точно `endCall`, бо саме цю назву використовує промт Олени.

### submit_booking_request
Додайте **Custom Function**:

| Поле | Значення |
|---|---|
| Name | `submit_booking_request` |
| Description | з `retell/submit_booking_request.tool.json` |
| URL | `https://<host>/retell/function` |
| Method | POST |
| Payload: args only | **вимкнено** (backend чекає `{"name", "call", "args"}`) |
| Parameters (JSON) | поле `parameters` з `retell/submit_booking_request.tool.json` |
| Speak during execution | вимкнено (промт каже мовчати) |
| Speak after execution | увімкнено |
| Timeout | 10000 ms |
| Max retry | 1 (endpoint ідемпотентний) |

Окремий заголовок авторизації не потрібен: backend перевіряє підпис `X-Retell-Signature` вашим `RETELL_API_KEY`.

## 4. Webhook подій

У налаштуваннях агента (**Webhook Settings**):
- **Agent Level Webhook URL:** `https://<host>/retell/webhook`
- **Events:** достатньо `call_ended`.

## 5. Зберігання даних

- **Data storage:** для демо підійде `everything`. Якщо пересилання записів не потрібне, можна обрати суворіший варіант, але тоді транскрипт/запис можуть не прийти.
- Максимальна тривалість дзвінка: 15 хв. Завершення після тиші: 30 с (див. `retell/agent.template.json`).

## 6. Перевірка

1. Натисніть **Test** (web call) в агенті, проведіть розмову з вигаданими даними.
2. У логах backend має з'явитись `booking #N created`, а в PostgreSQL з'явиться рядок у `booking_requests`.
3. У Telegram-групі має прийти повідомлення.
4. Після завершення дзвінка в `call_logs` з'являється запис із транскриптом.
5. Відповідь `401` у логах означає, що в `.env` не той ключ (потрібен саме ключ з позначкою webhook) або на сервері розсинхронізований годинник (допуск підпису 5 хв).

## Шаблони для API

Якщо зручніше створювати через API, а не через Dashboard:
1. `POST https://api.retellai.com/create-retell-llm` з тілом із `retell/llm.template.json` (підставте промт, модель і `SERVER_URL`; поле `_comment` видаліть).
2. `POST https://api.retellai.com/create-agent` з тілом із `retell/agent.template.json` і `llm_id` з попередньої відповіді.
