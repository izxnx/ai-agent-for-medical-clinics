# Підключення Vapi Assistant до Verika

Інструкція для синтетичної демонстрації. Не прив'язуйте номер клініки та не надсилайте реальні персональні/медичні дані, доки клініка не погодила договори, обробку, запис і зберігання.

## 1. Запустіть backend

1. Запустіть PostgreSQL і FastAPI за головним [README](../README.md).
2. Переконайтеся, що `http://localhost:8000/health` відповідає `{"ok":true}`.
3. Vapi працює поза вашим комп'ютером, тому `localhost` для нього недоступний. Для короткого тесту створіть HTTPS tunnel до `127.0.0.1:8000` або використайте staging URL із TLS. Зупиніть tunnel після демонстрації. Не відкривайте назовні PostgreSQL чи порт 8000 без reverse proxy/TLS.

## 2. Створіть правильний секрет

1. У локальному `.env` задайте випадковий довгий `VAPI_SECRET`; для тестового tunnel використовуйте окреме значення.
2. У Vapi Dashboard відкрийте Integrations → Server Configuration → Credentials (назви пунктів можуть відрізнятися у версії Dashboard) і створіть Custom Credential типу **Bearer Token**.
3. Найпростіший варіант: Header Name `Authorization`, Include Bearer Prefix увімкнено. Тоді backend отримає `Authorization: Bearer <VAPI_SECRET>`.
4. Альтернатива: Header Name `X-Vapi-Secret`, Include Bearer Prefix вимкнено.
5. В обох випадках token має збігатися з `VAPI_SECRET` у `.env`.

**Не вставляйте сюди Vapi Private API key.** Він дає доступ до API акаунта, а webhook-secret — це окремий випадковий рядок для перевірки запитів до цього backend. [Документація Vapi про Custom Credentials](https://docs.vapi.ai/server-url/server-authentication).

## 3. Створіть Function tool

1. У Vapi Dashboard створіть Assistant та окремий Function tool.
2. Назва функції — `submit_booking_request`. Параметри перенесіть з [`tools/submit_booking_request.json`](tools/submit_booking_request.json); вони мають збігатися з усіма полями, які Олена перевіряє з людиною перед збереженням. Якщо людина не знає послугу, промт дозволяє лише обмежену рекомендацію консультації або передзвін.
3. У Server Settings інструмента задайте `https://<ваш-public-host>/vapi/webhook` і створений Bearer Token Credential.
4. У Messages → Request Failed задайте саме цю фразу: «Вибачте, сталася технічна помилка. Будь ласка, зателефонуйте нам зранку.» Backend повертає поле `error` при збої; Vapi за наявності `error` запускає налаштоване повідомлення Request Failed. [Формат Function tool і помилок](https://docs.vapi.ai/tools/custom-tools).
5. Переконайтеся, що успішний виклик інструмента повертає `results` з відповідним `toolCallId` і рядком `result`. Backend це формує автоматично.

Не копіюйте секрет у URL, опис функції або системний промт.

## 4. Налаштуйте Assistant

1. Вставте повний текст [`prompts/olena_system_prompt.md`](../prompts/olena_system_prompt.md) у System message. Самостійно Vapi файл із диска не читає.
2. First Message перенесіть з [`assistant.template.json`](assistant.template.json). Попередження «Розмова записується» поки є технічним заповнювачем; перед реальними дзвінками його формулювання має погодити юрист і клініка.
3. Додайте інструмент `submit_booking_request` і штатний `endCall`.
4. У Webhook Server Assistant задайте той самий URL і Credential. У Server Messages залиште/увімкніть `tool-calls` та `end-of-call-report`. URL інструмента обробляє виклик функції; URL Assistant отримує звіт про дзвінок. Vapi має різні рівні Server URL; URL Function tool має пріоритет для подій цього інструмента. [Налаштування server URL](https://docs.vapi.ai/server-url/setting-server-urls), [Server events](https://docs.vapi.ai/server-url/events).
5. Увімкніть запис і транскрипт лише для синтетичної демонстрації. Переконайтеся, що `maxDurationSeconds` і `silenceTimeoutSeconds` відповідають плану дзвінка; актуальні допустимі межі перевірте у Vapi Dashboard. [Таймаути дзвінка](https://docs.vapi.ai/documentation/assistants/conversation-behavior/call-timeout-settings).
6. Виберіть модель, голос і транскрайбер та зробіть короткий web-call, перевіряючи українську вимову й розпізнавання. Конкретні доступні комбінації залежать від вашого акаунта; у шаблоні вони позначені `{{...}}`.
7. Збережіть і опублікуйте Assistant.

`assistant.template.json` — карта налаштувань для ручного перенесення, а не готовий API payload: у ній навмисно залишені плейсхолдери.

## 5. Перевірте результат

1. Відкрийте Vapi web-call з Dashboard; номер телефонії для цього не потрібен.
2. Використайте лише синтетичне ім'я, тестове побажання й вигаданий опис скарги. Не використовуйте справжній номер.
3. У Vapi Logs → Calls перевірте, що `submit_booking_request` викликано, його назва/поля коректні та інструмент завершився без помилки.
4. Перевірте рядок у локальній БД і текст у приватній Telegram-групі, якщо вона підключена.
5. Після дзвінка перевірте `end-of-call-report` і транскрипт. Пересилання аудіо у Telegram вимкнене за замовчуванням; signed URL не надсилається у webhook-лог і не зберігається backend-ом.

## 6. Увімкніть пересилання аудіо в Telegram (лише для синтетичного демо)

1. Спершу перевірте, що політики Vapi, доступи адміністраторів і сценарій демонстрації дозволяють передавати аудіо до тестової Telegram-групи. Для звичайної перевірки заявки запис не потрібен.
2. Збережіть окремий Vapi Private API key у `.env` як `VAPI_PRIVATE_API_KEY`; не використовуйте його як webhook `VAPI_SECRET` і не надсилайте в чат.
3. Зробіть один синтетичний дзвінок, не копіюючи signed URL. У Vapi приватний запис отримується backend-ом через `GET https://api.vapi.ai/call/{call_id}/mono-recording` з Bearer key; Vapi повертає redirect на тимчасове посилання.
4. Якщо хочете дозволити пересилання, додайте в `VAPI_RECORDING_HOSTS` лише точний hostname цього redirect (без схеми, шляху та query) і встановіть `FORWARD_RECORDINGS_TO_TELEGRAM=true`. Перезапустіть app. Backend надсилає ключ тільки до `api.vapi.ai`, перевіряє HTTPS redirect, обмежує аудіо 45 MiB і не зберігає signed URL.
5. Після демонстрації поверніть `FORWARD_RECORDINGS_TO_TELEGRAM=false`, видаліть/ротувайте ключ за потреби й очистіть тестові записи відповідно до плану.

## 7. Телефонний номер — окремий наступний етап

Для презентації директора вистачає web-call. Безкоштовні Vapi numbers мають американський код і підтримують вхідні дзвінки; це не український номер клініки. [Номери Vapi](https://docs.vapi.ai/phone-calling).

Коли клініка письмово дозволить тестувати телефонію:

1. Запитайте її поточного оператора про SIP trunk/переадресацію, підтримку вхідного маршруту до Vapi, тарифи та власника номера.
2. Порівняйте це з офіційними інструкціями Vapi для SIP/імпорту номера.
3. Telnyx підтримує українські номери, але просить бізнес-документи та адресу; перевірка може займати близько 72 годин. Vapi також описує можливе спотворення аудіо на деяких міжнародних Telnyx викликах. Перевірте ціну, наявність, документи та кодеки з підтримкою до оплати. [Vapi + Telnyx](https://docs.vapi.ai/telnyx), [вимоги Telnyx для України](https://support-v2.telnyx.com/en/articles/3739745-ukraine-did-requirements).
4. Спершу проведіть вхідний тест на власний/узгоджений тестовий маршрут, а вже після цього обговорюйте номер клініки.

## Після демонстрації

- Зупиніть HTTPS tunnel або staging deployment, якщо він більше не потрібен.
- Відкличте demo webhook credential, якщо він був опублікований/переданий не тим людям.
- Видаліть синтетичні заявки, транскрипти й записи згідно з планом демонстрації.
- Не починайте реальні дзвінки, поки не виконано пункт «Не готово до реальних даних» у головному README.
