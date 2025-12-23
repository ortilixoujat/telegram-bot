import os, json, io
from pathlib import Path

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
)
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

from PIL import Image
import imagehash

# ========= إعداداتك =========
TOKEN = os.getenv("8238079714:AAGb-G4FTgF--cPMwJbXd1W19w-4y_zPZy8")  # ضع التوكن في Railway Variables باسم BOT_TOKEN
ADMIN_CODE = os.getenv("ADMIN_CODE", "1235812358")  # اختياري: تقدر تغيّره من Variables

WELCOME_TEXT_DEFAULT = """مرحبا بك انا كلوفر و مساعد في مجموعة الفرسان مجموعة بطولات و رومات بين الاعضاء ون بيس فايتينغ باث
https://t.me/KNIGTHSOPFP
"""

ADMIN_PANEL_TEXT = """اهلا بك في لوحة التحكم الأدمن الخاصة بالبوت 🤖
يمكنك التحكم في البوت الخاص بك من هنا
@RUDO_RD
"""

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Please set BOT_TOKEN in Railway Variables (or environment).")

# ========= تخزين =========
DATA_DIR = Path("./bot_data")
DATA_DIR.mkdir(exist_ok=True)
STATE_FILE = DATA_DIR / "state.json"

def default_state():
    return {
        "auto_reply_enabled": True,
        "welcome_text": WELCOME_TEXT_DEFAULT,
        # {name, phash, threshold, reply_text, reply_photos[]}
        "image_replies": []
    }

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    s = default_state()
    save_state(s)
    return s

def save_state(s):
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")

state = load_state()

# ✅ حسب طلبك: بدون تقييد أدمن بالآيدي
def is_admin(_uid: int) -> bool:
    return True

# ========= Keyboards =========
def kb_admin_home():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1) الرد على الرسائل", callback_data="menu_auto")],
        [InlineKeyboardButton("2) ردود الصور", callback_data="menu_images")],
    ])

def kb_auto():
    status = "✅ شغال" if state["auto_reply_enabled"] else "⛔️ متوقف"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"الحالة: {status}", callback_data="noop")],
        [InlineKeyboardButton("تبديل تشغيل/إيقاف", callback_data="toggle_auto")],
        [InlineKeyboardButton("تعديل رسالة الترحيب", callback_data="set_welcome")],
        [InlineKeyboardButton("رجوع", callback_data="back")],
    ])

def kb_images():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة رد بصورة", callback_data="img_add")],
        [InlineKeyboardButton("📋 عرض الردود", callback_data="img_list")],
        [InlineKeyboardButton("🗑️ حذف رد", callback_data="img_del")],
        [InlineKeyboardButton("⚙️ تعديل الحساسية (Threshold)", callback_data="img_thr")],
        [InlineKeyboardButton("رجوع", callback_data="back")],
    ])

# ========= Image hash helpers =========
def phash_from_bytes(b: bytes):
    img = Image.open(io.BytesIO(b)).convert("RGB")
    return imagehash.phash(img)

def distance(phash_hex: str, incoming_hash):
    return imagehash.hex_to_hash(phash_hex) - incoming_hash

async def match_image_reply(photo_bytes: bytes):
    if not state["image_replies"]:
        return None

    inc = phash_from_bytes(photo_bytes)
    best = None
    best_dist = 10**9

    for r in state["image_replies"]:
        d = distance(r["phash"], inc)
        if d < best_dist:
            best_dist = d
            best = r

    if best and best_dist <= int(best.get("threshold", 10)):
        return best
    return None

# ========= Handlers =========
async def on_private_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = (update.message.text or "").strip()

    if not is_admin(uid):
        if state["auto_reply_enabled"]:
            await update.message.reply_text(state["welcome_text"])
        return

    # ✅ منع أي أوامر تبدأ بـ /
    if text.startswith("/"):
        await update.message.reply_text("⚠️ الأوامر (/) غير مقبولة هنا. أرسل نص فقط.")
        return

    # 1) تعديل الترحيب
    if context.user_data.get("waiting_welcome"):
        state["welcome_text"] = update.message.text
        save_state(state)
        context.user_data["waiting_welcome"] = False
        await update.message.reply_text(
            "✅ تم تحديث رسالة الترحيب إلى:\n\n" + state["welcome_text"],
            reply_markup=kb_auto()
        )
        return

    # 2) وضع إضافة رد: تجميع ردود (صور متعددة + نص اختياري)
    if context.user_data.get("waiting_reply_content"):
        if text == "تم":
            photos = context.user_data.get("reply_photos", [])
            reply_text = context.user_data.get("reply_text", None)
            if not photos and not reply_text:
                await update.message.reply_text("❌ لم ترسل أي صور أو نص. أرسل صور/نص ثم اكتب (تم).")
                return
            context.user_data["waiting_reply_content"] = False
            context.user_data["waiting_trigger_photo"] = True
            await update.message.reply_text("تمام ✅ الآن أرسل صورة الكنز المرجعية (الصورة التي سيتم التطابق عليها).")
            return

        # حفظ نص الرد
        context.user_data["reply_text"] = update.message.text
        await update.message.reply_text("✅ تم حفظ نص الرد.\nأرسل صور الرد (اختياري) ثم اكتب (تم) للمتابعة.")
        return

    # 3) حذف: ينتظر رقم
    if context.user_data.get("waiting_delete_index"):
        try:
            idx = int(text) - 1
            if idx < 0 or idx >= len(state["image_replies"]):
                raise ValueError
            removed = state["image_replies"].pop(idx)
            save_state(state)
            await update.message.reply_text(f"✅ تم حذف: {removed.get('name','رد صورة')}", reply_markup=kb_images())
        except:
            await update.message.reply_text("❌ ارسل رقم صحيح من القائمة (مثال: 1).")
        finally:
            context.user_data["waiting_delete_index"] = False
        return

    # 4) تعديل threshold: رقم الرد
    if context.user_data.get("waiting_thr_index"):
        try:
            idx = int(text) - 1
            if idx < 0 or idx >= len(state["image_replies"]):
                raise ValueError
            context.user_data["thr_target_idx"] = idx
            context.user_data["waiting_thr_index"] = False
            context.user_data["waiting_thr_value"] = True
            await update.message.reply_text("تمام ✅ الآن أرسل قيمة الحساسية Threshold (مثال: 10).")
        except:
            await update.message.reply_text("❌ ارسل رقم صحيح من القائمة (مثال: 1).")
        return

    # 5) تعديل threshold: القيمة
    if context.user_data.get("waiting_thr_value"):
        try:
            val = int(text)
            if val < 1 or val > 40:
                raise ValueError
            idx = context.user_data["thr_target_idx"]
            state["image_replies"][idx]["threshold"] = val
            save_state(state)
            await update.message.reply_text("✅ تم تحديث الحساسية.", reply_markup=kb_images())
        except:
            await update.message.reply_text("❌ ارسل رقم صحيح بين 1 و 40 (مثال: 10).")
        finally:
            context.user_data["waiting_thr_value"] = False
            context.user_data.pop("thr_target_idx", None)
        return

    # 6) فتح لوحة التحكم
    if text == ADMIN_CODE:
        await update.message.reply_text(ADMIN_PANEL_TEXT, reply_markup=kb_admin_home())
        return

    # 7) رد ترحيبي عادي في الخاص
    if state["auto_reply_enabled"]:
        await update.message.reply_text(state["welcome_text"])

async def on_private_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1) تجميع صور الرد (يمكن إرسال أكثر من صورة)
    if context.user_data.get("waiting_reply_content"):
        photo = update.message.photo[-1]
        context.user_data.setdefault("reply_photos", [])
        if len(context.user_data["reply_photos"]) >= 10:
            await update.message.reply_text("⚠️ الحد الأقصى 10 صور في الرد. اكتب (تم) للمتابعة.")
            return
        context.user_data["reply_photos"].append(photo.file_id)
        await update.message.reply_text("✅ تم حفظ صورة للرد.\nارسل صورة أخرى أو اكتب (تم) للمتابعة.")
        return

    # 2) استقبال صورة المرجع (Trigger)
    if context.user_data.get("waiting_trigger_photo"):
        photo = update.message.photo[-1]
        f = await photo.get_file()
        b = await f.download_as_bytearray()
        ph = phash_from_bytes(bytes(b))

        item = {
            "name": f"رد صورة #{len(state['image_replies'])+1}",
            "phash": str(ph),
            "threshold": 10,
            "reply_text": context.user_data.get("reply_text", None),
            "reply_photos": context.user_data.get("reply_photos", []),
        }

        state["image_replies"].append(item)
        save_state(state)

        # تنظيف
        context.user_data["waiting_trigger_photo"] = False
        context.user_data.pop("reply_text", None)
        context.user_data.pop("reply_photos", None)

        await update.message.reply_text(
            "✅ تم إضافة الرد بنجاح!\nأي صورة مشابهة في الجروب سيأتيها نفس الرد كـ Reply على رسالة العضو.",
            reply_markup=kb_images()
        )

async def on_group_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # مطابقة صور الكنوز في الجروب
    photo = update.message.photo[-1]
    f = await photo.get_file()
    b = await f.download_as_bytearray()

    matched = await match_image_reply(bytes(b))
    if not matched:
        return

    reply_text = matched.get("reply_text")
    reply_photos = matched.get("reply_photos", [])
    reply_to_id = update.message.message_id  # ✅ Reply على نفس رسالة العضو

    # ألبوم (>=2)
    if len(reply_photos) >= 2:
        media = []
        for i, fid in enumerate(reply_photos[:10]):
            cap = reply_text if (i == 0 and reply_text) else None
            media.append(InputMediaPhoto(media=fid, caption=cap))

        await update.effective_chat.send_media_group(
            media=media,
            reply_to_message_id=reply_to_id
        )
        return

    # صورة واحدة
    if len(reply_photos) == 1:
        await update.message.reply_photo(photo=reply_photos[0], caption=reply_text)
        return

    # نص فقط
    if reply_text:
        await update.message.reply_text(reply_text)

async def on_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "back":
        await q.edit_message_text(ADMIN_PANEL_TEXT, reply_markup=kb_admin_home())
        return

    if data == "menu_auto":
        await q.edit_message_text("إعدادات الرد على الرسائل:", reply_markup=kb_auto())
        return

    if data == "toggle_auto":
        state["auto_reply_enabled"] = not state["auto_reply_enabled"]
        save_state(state)
        await q.edit_message_text("إعدادات الرد على الرسائل:", reply_markup=kb_auto())
        return

    if data == "set_welcome":
        context.user_data["waiting_welcome"] = True
        await q.edit_message_text("✍️ أرسل الآن رسالة الترحيب الجديدة (كنص فقط، بدون /).")
        return

    if data == "menu_images":
        await q.edit_message_text("إدارة ردود الصور:", reply_markup=kb_images())
        return

    if data == "img_add":
        context.user_data["waiting_reply_content"] = True
        context.user_data.pop("reply_text", None)
        context.user_data.pop("reply_photos", None)
        await q.edit_message_text(
            "📝 أرسل الآن (ردك) كالتالي:\n"
            "✅ يمكنك إرسال نص\n"
            "✅ ويمكنك إرسال عدة صور (حتى 10)\n\n"
            "بعد ما تخلص اكتب كلمة: تم\n"
            "ثم سأطلب منك صورة الكنز المرجعية.\n\n"
            "⚠️ ملاحظة: لا ترسل أوامر تبدأ بـ /"
        )
        return

    if data == "img_list":
        if not state["image_replies"]:
            await q.edit_message_text("لا يوجد ردود صور محفوظة.", reply_markup=kb_images())
            return

        lines = []
        for i, r in enumerate(state["image_replies"], start=1):
            thr = r.get("threshold", 10)
            pcount = len(r.get("reply_photos", []))
            has_text = "نعم" if r.get("reply_text") else "لا"
            lines.append(f"{i}) {r.get('name','رد')} — صور={pcount} — نص={has_text} — thr={thr}")
        await q.edit_message_text("📋 ردود الصور:\n" + "\n".join(lines), reply_markup=kb_images())
        return

    if data == "img_del":
        if not state["image_replies"]:
            await q.edit_message_text("لا يوجد شيء للحذف.", reply_markup=kb_images())
            return
        context.user_data["waiting_delete_index"] = True
        await q.edit_message_text("🗑️ أرسل رقم الرد الذي تريد حذفه (مثال: 1).")
        return

    if data == "img_thr":
        if not state["image_replies"]:
            await q.edit_message_text("لا يوجد ردود لتعديلها.", reply_markup=kb_images())
            return
        context.user_data["waiting_thr_index"] = True
        await q.edit_message_text("⚙️ أرسل رقم الرد الذي تريد تعديل حساسيته (مثال: 1).")
        return

    if data == "noop":
        return

# ========= تشغيل =========
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CallbackQueryHandler(on_buttons))

# ✅ الخاص: نصوص بدون أوامر
app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, on_private_text))
app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.PHOTO, on_private_photo))

# الجروبات: صور للبحث عن التطابق
app.add_handler(MessageHandler(
    (filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP) & filters.PHOTO,
    on_group_photo
))

if __name__ == "__main__":
    app.run_polling()
