# captcha-bot

Telegram-бот-капча для групп. Новый участник получает мут и сообщение с 6 эмодзи-кнопками. Нужно нажать указанный эмодзи:

- верно: ограничения снимаются;
- неверно: кик с баном на `COOLDOWN_WRONG` секунд;
- не успел за `CAPTCHA_TIMEOUT`: кик с баном на `COOLDOWN_TIMEOUT` секунд.

Сервисные сообщения о входе и выходе удаляются.

## Требования

- Python 3.10+
- Бот должен быть админом группы с правами на бан, ограничение участников и удаление сообщений.

## Запуск

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env   # вписать BOT_TOKEN
set -a; . ./.env; set +a
venv/bin/python captcha_bot.py
```

## Деплой (systemd)

```bash
sudo useradd -r -m -d /opt/captcha-bot captchabot
sudo -u captchabot git clone <repo> /opt/captcha-bot   # или скопировать файлы
cd /opt/captcha-bot
sudo -u captchabot python3 -m venv venv
sudo -u captchabot venv/bin/pip install -r requirements.txt
sudo -u captchabot cp .env.example .env && sudo chmod 600 .env   # вписать BOT_TOKEN
sudo cp deploy/captcha-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now captcha-bot
```

Логи: `journalctl -u captcha-bot -f`
