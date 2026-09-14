import asyncio
import logging
import os
import random
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
 
# === НАСТРОЙКИ ===
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Переменная окружения BOT_TOKEN не задана")
 
CAPTCHA_TIMEOUT = int(os.environ.get("CAPTCHA_TIMEOUT", 5 * 60))  # секунд
 
# Кулдауны при кике (в секундах): сколько человек не сможет зайти обратно
COOLDOWN_TIMEOUT = int(os.environ.get("COOLDOWN_TIMEOUT", 5 * 60))  # игнор капчи → 5 мин
COOLDOWN_WRONG = int(os.environ.get("COOLDOWN_WRONG", 2 * 60))     # неверный эмодзи → 2 мин
 
# Пул эмодзи для капчи. Из них случайно выбирается 6 штук на каждого юзера,
# один из них — правильный, остальные — обманки.
EMOJI_POOL = [
    "🍎", "🍌", "🍇", "🍒", "🥝", "🍊", "🍓", "🍍",
    "🥑", "🥕", "🌽", "🍄", "🌶", "🥦", "🍑", "🍉",
]
BUTTONS_COUNT = 6  # 2 ряда по 3
 
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
 
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
 
# (chat_id, user_id) -> (captcha_message_id, kick_task, correct_emoji)
pending_captchas: dict[tuple[int, int], tuple[int, asyncio.Task, str]] = {}
 
MUTED_PERMISSIONS = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
)
 
UNMUTED_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_invite_users=True,
)
 
 
def build_mention(user) -> str:
    if user.username:
        return f"@{user.username}"
    safe_name = (user.full_name or "друг").replace("<", "&lt;").replace(">", "&gt;")
    return f'<a href="tg://user?id={user.id}">{safe_name}</a>'
 
 
async def kick_with_cooldown(chat_id: int, user_id: int, cooldown_seconds: int, reason: str):
    """
    Кик с кулдауном: юзер вылетает и не может зайти обратно N секунд.
    Реализовано через ban_chat_member с until_date — Telegram сам снимет бан.
    """
    import time
    until = int(time.time()) + cooldown_seconds
    try:
        await bot.ban_chat_member(chat_id, user_id, until_date=until)
        logging.info(
            f"Кикнут user_id={user_id} из chat_id={chat_id} "
            f"на {cooldown_seconds} сек ({reason})"
        )
    except Exception as e:
        logging.error(f"Не удалось кикнуть {user_id}: {e}")
 
 
def build_captcha_keyboard(user_id: int, emojis: list[str]) -> InlineKeyboardMarkup:
    """Сетка кнопок 2x3 с эмодзи. callback_data: verify:<user_id>:<emoji>"""
    rows = []
    for i in range(0, len(emojis), 3):
        row = [
            InlineKeyboardButton(
                text=e,
                callback_data=f"verify:{user_id}:{e}",
            )
            for e in emojis[i:i + 3]
        ]
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)
 
 
@dp.message(F.new_chat_members)
async def on_new_members_service_message(message):
    """Удаляем сервисное сообщение 'X теперь в группе'."""
    try:
        await message.delete()
    except Exception as e:
        logging.debug(f"Не удалось удалить сервисное сообщение о входе: {e}")
 
 
@dp.message(F.left_chat_member)
async def on_left_member_service_message(message):
    """Удаляем сервисное сообщение 'X покинул группу' (в т.ч. после кика)."""
    try:
        await message.delete()
    except Exception as e:
        logging.debug(f"Не удалось удалить сервисное сообщение о выходе: {e}")
 
 
@dp.chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION))
async def on_user_join(event: ChatMemberUpdated):
    user = event.new_chat_member.user
    chat_id = event.chat.id
    user_id = user.id
 
    if user.is_bot:
        return
 
    # Если у этого юзера уже висит капча — отменим старую
    old = pending_captchas.pop((chat_id, user_id), None)
    if old is not None:
        _, old_task, _ = old
        old_task.cancel()
        try:
            await bot.delete_message(chat_id, old[0])
        except Exception:
            pass
 
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=MUTED_PERMISSIONS,
        )
    except Exception as e:
        logging.error(f"Не удалось ограничить пользователя {user_id}: {e}")
        return
 
    # Выбираем 6 разных эмодзи, один из них — правильный
    emojis = random.sample(EMOJI_POOL, BUTTONS_COUNT)
    correct_emoji = random.choice(emojis)
 
    keyboard = build_captcha_keyboard(user_id, emojis)
    mention = build_mention(user)
    minutes = CAPTCHA_TIMEOUT // 60
    text = (
        f"🐒 привет, {mention}! чтобы подтвердить, что ты не бот, "
        f"нажми {correct_emoji} в течение {minutes} минут или будешь кикнут"
    )
 
    try:
        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
        )
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение капчи: {e}")
        return
 
    task = asyncio.create_task(kick_after_timeout(chat_id, user_id, msg.message_id))
    pending_captchas[(chat_id, user_id)] = (msg.message_id, task, correct_emoji)
    logging.info(
        f"Капча отправлена для user_id={user_id} в chat_id={chat_id} "
        f"(правильный эмодзи: {correct_emoji})"
    )
 
 
async def kick_after_timeout(chat_id: int, user_id: int, message_id: int):
    try:
        await asyncio.sleep(CAPTCHA_TIMEOUT)
    except asyncio.CancelledError:
        return
 
    if (chat_id, user_id) not in pending_captchas:
        return
    pending_captchas.pop((chat_id, user_id), None)
 
    await kick_with_cooldown(chat_id, user_id, COOLDOWN_TIMEOUT, "таймаут капчи")
 
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        logging.error(f"Не удалось удалить сообщение капчи: {e}")
 
 
@dp.callback_query(F.data.startswith("verify:"))
async def on_verify(callback: CallbackQuery):
    parts = callback.data.split(":", 2)
    if len(parts) != 3:
        await callback.answer()
        return
 
    try:
        expected_user_id = int(parts[1])
    except ValueError:
        await callback.answer()
        return
    pressed_emoji = parts[2]
 
    # Кнопка работает только для того, кому она предназначена
    if callback.from_user.id != expected_user_id:
        await callback.answer("Эта кнопка не для тебя 🙃", show_alert=True)
        return
 
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
 
    pending = pending_captchas.get((chat_id, user_id))
    if pending is None:
        # Капчи уже нет — например, уже сработал таймаут
        await callback.answer()
        return
 
    message_id, task, correct_emoji = pending
 
    # Неправильная кнопка — кик сразу
    if pressed_emoji != correct_emoji:
        pending_captchas.pop((chat_id, user_id), None)
        task.cancel()
        await callback.answer("Неверно ❌")
        await kick_with_cooldown(chat_id, user_id, COOLDOWN_WRONG, f"неверный эмодзи: {pressed_emoji}")
        try:
            await callback.message.delete()
        except Exception as e:
            logging.error(f"Не удалось удалить сообщение капчи: {e}")
        return
 
    # Правильная кнопка — снимаем ограничения
    pending_captchas.pop((chat_id, user_id), None)
    task.cancel()
 
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=UNMUTED_PERMISSIONS,
        )
    except Exception as e:
        logging.error(f"Не удалось вернуть права {user_id}: {e}")
 
    try:
        await callback.message.delete()
    except Exception as e:
        logging.error(f"Не удалось удалить сообщение капчи: {e}")
 
    await callback.answer("Добро пожаловать! ✅")
    logging.info(f"Верифицирован user_id={user_id} в chat_id={chat_id}")
 
 
async def main():
    await dp.start_polling(
        bot,
        allowed_updates=["chat_member", "callback_query", "message"],
    )
 
 
if __name__ == "__main__":
    asyncio.run(main())
 
