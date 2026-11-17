# Автопубликация в Instagram и Facebook (без Metricool)

Публикатор — `automation/publish_queue.py`, запускает его `.github/workflows/publish.yml`:
каждые 15 минут и сразу после того, как в `captions/` появился новый файл. Публикует напрямую через
официальный Graph API Meta. Репозиторий публичный, поэтому минуты GitHub Actions не расходуются.

## Что публикуется

1. **Недельные очереди** `captions/ГГГГ-ММ-ДД-week/queue.json`, если в файле есть строка
   `"publisher": "github"`. Формат тот же, что раньше для Metricool. Картинки и видео лежат в
   `images/ГГГГ/ММ/week-ДД/`, либо путь задаётся полем `"media_dir"`.
   - `REEL` — видео mp4;
   - `POST` — одна картинка или карусель (до 10);
   - `STORY` — картинка или видео.

   Для Facebook то же самое, но видео-истории не поддерживаются.
2. **Посты бота.** После публикации в Telegram бот сам кладёт картинку и задачу в
   `captions/auto/ГГГГ-ММ/ГГГГ-ММ-ДД.json`. Что куда идёт, задаёт `social` в `config.json` бота:
   - Instagram: «Статья дня» — пост с картинкой, «Луна дня» — история;
   - Facebook: Луна, Статья, Нумерология, прогноз на неделю.

   Ссылки из текста для Instagram убираются, вместо них добавляется «ссылка в шапке профиля» и хэштеги.

Что уже опубликовано — `automation/published.json`. Неудачная задача повторяется до 3 раз, потом
пропускается. Задачи, опоздавшие больше чем на 12 часов, не публикуются, чтобы не выкладывать устаревшее.
Об ошибках админ получает сообщение в Telegram, если заданы секреты `TELEGRAM_BOT_TOKEN` и `ADMIN_CHAT_ID`.

> **Важно:** если неделя уже стоит в Metricool, не ставьте ей `"publisher": "github"`, иначе посты выйдут дважды.

## Настройка (один раз)

### 1. Instagram и страница Facebook

- Instagram @kamila_astrolog должен быть **бизнес-аккаунтом**, а не «автором»: Reels и истории через API
  публикуются только с бизнес-аккаунта. Проверить: Instagram → Настройки → Тип аккаунта и инструменты.
- Instagram привязан к странице Facebook Камилы: Meta Business Suite → Настройки → Аккаунты Instagram,
  или в Instagram: Центр аккаунтов.

### 2. Приложение Meta и бессрочный токен страницы

1. Откройте https://developers.facebook.com → «Мои приложения» → «Создать приложение».
   Тип — «Другое» → «Бизнес». Название любое, например «Kamila publisher».
   Режим разработки оставить: для своих аккаунтов проверка Meta не нужна.
2. Откройте Graph API Explorer: https://developers.facebook.com/tools/explorer/.
   - Справа выберите своё приложение и «User Token».
   - Добавьте разрешения: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`,
     `pages_manage_engagement`, `instagram_basic`, `instagram_content_publish`,
     `instagram_manage_comments`, `business_management`.
   - Нажмите «Generate Access Token» и разрешите доступ к странице Камилы и её Instagram.
3. Скопируйте токен и откройте Access Token Debugger: https://developers.facebook.com/tools/debug/accesstoken/.
   Вставьте токен, нажмите «Debug», затем «Extend Access Token». Получите токен на 60 дней.
4. Вернитесь в Graph API Explorer, вставьте продлённый токен в поле токена и выполните запрос `me/accounts`.
   В ответе у страницы Камилы будет `access_token` — это **токен страницы**.
5. Проверьте его в Access Token Debugger: должно быть «Expires: Never».

### 3. Секреты GitHub

- В **kamila-astrology-content** (Settings → Secrets and variables → Actions → New repository secret):
  - `META_PAGE_TOKEN` — токен страницы из шага 2;
  - по желанию `TELEGRAM_BOT_TOKEN` и `ADMIN_CHAT_ID` — те же, что у бота, для сообщений об ошибках.
- В **astro-bot** — `CONTENT_REPO_TOKEN`. Создать: GitHub → Settings → Developer settings →
  Fine-grained tokens → Generate:
  - Repository access: только `kamila-astrology-content`;
  - Permissions: Contents — Read and write;
  - срок — год (поставьте напоминание).

### 4. Проверка

1. Actions → «Публикация в Instagram и Facebook» → Run workflow.
   Тестовый режим включён по умолчанию: в логе будет список того, что публикатор собирается опубликовать.
2. Чтобы опубликовать одну задачу прямо сейчас, снимите галочку тестового режима и укажите `only_key`,
   например `2026-11-23-week/story-23-instagram`.
3. Если что-то не так, сообщение об ошибке Meta будет в логе и в Telegram админу.

## Ограничения Meta

- До 100 публикаций через API за 24 часа на аккаунт; карусель считается за одну.
- Картинки в Instagram — только JPEG по публичной ссылке. Публикатор сам делает JPEG-копии
  в `automation/jpg/` и даёт ссылку на raw.githubusercontent.com.
- Видео загружается файлом, ссылка не нужна.
- Удалить пост через API нельзя, только вручную в приложении.
- Если сменить пароль Facebook или отозвать доступ приложения, токен страницы перестанет работать —
  повторите шаг 2.
