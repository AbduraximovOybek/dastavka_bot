
"""
Yetkazib berish boti (Telegram, aiogram 3) — kengaytirilgan versiya
 
O'rnatish:        pip install aiogram
Ishga tushirish:  python bot.py
 
Yangi imkoniyatlar:
- Mijoz nima buyurtma qilayotganini, manzilini (matn yoki lokatsiya) va telefonini kiritadi
- Admin buyurtmani rad etishi mumkin
- Mijoz buyurtmani bekor qilishi mumkin (kuryer yo'lga chiqquncha)
- Faqat tayinlangan kuryer o'z tugmalarini bosa oladi (xavfsizlik)
- Kuryerga mijoz telefoni va lokatsiyasi yuboriladi
- Vaqt tugaganda mijozga ham, kuryerga ham eslatma ketadi
- /orders (admin), /myorders (mijoz), /cancel (jarayonni to'xtatish)
- Buyurtmalar orders.json fayliga saqlanadi (bot qayta ishga tushsa ham yo'qolmaydi)
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
 
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, KeyboardButton, Message,
                           ReplyKeyboardMarkup, ReplyKeyboardRemove)
 
# ================== SOZLAMALAR ==================
TOKEN = "8610775349:AAF8H6bSHibN4TtV_USHQtJbdnBk1XUC4C8"   # @BotFather dan olasiz
ADMIN_ID = 8821105309                          # admin Telegram ID (@userinfobot dan bilib oling)
 
COURIERS = {
    222222222: {"name": "Ali Valiyev", "phone": "+998901234567"},
    333333333: {"name": "Sardor Karimov", "phone": "+998931112233"},
}
 
TZ = timezone(timedelta(hours=5))  # O'zbekiston vaqti
DB_FILE = Path("orders.json")
# =================================================
 
# status: new -> assigned -> on_way -> done   (yoki cancelled)
STATUS_TEXT = {
    "new": "🆕 Yangi",
    "assigned": "👤 Kuryer tayinlandi",
    "on_way": "🚀 Yo'lda",
    "done": "✅ Yetkazildi",
    "cancelled": "❌ Bekor qilingan",
}
 
ORDERS: dict[int, dict] = {}
order_counter = 0
 
router = Router()
 
 
# ---------- Saqlash ----------
def save():
    data = {"counter": order_counter, "orders": ORDERS}
    DB_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
 
 
def load():
    global order_counter
    if DB_FILE.exists():
        data = json.loads(DB_FILE.read_text(encoding="utf-8"))
        order_counter = data.get("counter", 0)
        ORDERS.update({int(k): v for k, v in data.get("orders", {}).items()})
 
 
# ---------- Yordamchi funksiyalar ----------
class OrderForm(StatesGroup):
    items = State()
    address = State()
    phone = State()
 
 
def now() -> datetime:
    return datetime.now(TZ)
 
 
def fmt(dt) -> str:
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    return dt.strftime("%H:%M")
 
 
def kb(*rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows]
    )
 
 
def reply_kb(*buttons: KeyboardButton):
    return ReplyKeyboardMarkup(keyboard=[[b] for b in buttons], resize_keyboard=True, one_time_keyboard=True)
 
 
def order_text(oid: int) -> str:
    o = ORDERS[oid]
    return (f"📦 Buyurtma #{oid}\n"
            f"🛍 {o['items']}\n"
            f"👤 {o['client_name']}\n"
            f"📞 {o['phone']}\n"
            f"📍 {o['address']}")
 
 
# ---------- /start, /cancel ----------
@router.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    if m.from_user.id == ADMIN_ID:
        await m.answer("Salom, admin! Yangi buyurtmalar shu yerga keladi.\n"
                       "/orders — faol buyurtmalar ro'yxati")
    elif m.from_user.id in COURIERS:
        await m.answer("Salom, kuryer! Sizga buyurtma tayinlansa, shu yerga keladi.")
    else:
        await m.answer("Xush kelibsiz! Buyurtma berish uchun tugmani bosing.\n"
                       "/myorders — mening buyurtmalarim",
                       reply_markup=kb([("🛒 Buyurtma berish", "new")]))
 
 
@router.message(Command("cancel"))
async def cancel_form(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Bekor qilindi. Qaytadan boshlash uchun /start ni bosing.",
                   reply_markup=ReplyKeyboardRemove())
 
 
# ---------- MIJOZ: buyurtma berish (3 qadam) ----------
@router.callback_query(F.data == "new")
async def new_order(c: CallbackQuery, state: FSMContext):
    await state.set_state(OrderForm.items)
    await c.message.answer("🛍 Nima buyurtma qilmoqchisiz? Yozib yuboring.\n(To'xtatish: /cancel)")
    await c.answer()
 
 
@router.message(OrderForm.items, F.text)
async def got_items(m: Message, state: FSMContext):
    await state.update_data(items=m.text)
    await state.set_state(OrderForm.address)
    await m.answer("📍 Yetkazib berish manzilini yozing yoki lokatsiyani yuboring:",
                   reply_markup=reply_kb(KeyboardButton(text="📍 Lokatsiyamni yuborish", request_location=True)))
 
 
@router.message(OrderForm.address, F.location)
async def got_location(m: Message, state: FSMContext):
    lat, lon = m.location.latitude, m.location.longitude
    await state.update_data(address=f"Lokatsiya ({lat:.5f}, {lon:.5f})", lat=lat, lon=lon)
    await ask_phone(m, state)
 
 
@router.message(OrderForm.address, F.text)
async def got_address(m: Message, state: FSMContext):
    await state.update_data(address=m.text, lat=None, lon=None)
    await ask_phone(m, state)
 
 
async def ask_phone(m: Message, state: FSMContext):
    await state.set_state(OrderForm.phone)
    await m.answer("📞 Telefon raqamingizni yuboring (tugma orqali yoki yozib):",
                   reply_markup=reply_kb(KeyboardButton(text="📞 Raqamimni yuborish", request_contact=True)))
 
 
@router.message(OrderForm.phone, F.contact)
async def got_contact(m: Message, state: FSMContext, bot: Bot):
    await finish_order(m, state, bot, m.contact.phone_number)
 
 
@router.message(OrderForm.phone, F.text)
async def got_phone(m: Message, state: FSMContext, bot: Bot):
    phone = m.text.strip()
    digits = [ch for ch in phone if ch.isdigit()]
    if len(digits) < 9:
        return await m.answer("❗ Raqam noto'g'ri ko'rinadi. Qaytadan yozing (masalan: +998901234567):")
    await finish_order(m, state, bot, phone)
 
 
async def finish_order(m: Message, state: FSMContext, bot: Bot, phone: str):
    global order_counter
    data = await state.get_data()
    await state.clear()
 
    order_counter += 1
    oid = order_counter
    ORDERS[oid] = {
        "client_id": m.from_user.id,
        "client_name": m.from_user.full_name,
        "phone": phone,
        "items": data["items"],
        "address": data["address"],
        "lat": data.get("lat"),
        "lon": data.get("lon"),
        "status": "new",
        "courier_id": None,
        "created_at": now().isoformat(),
        "left_at": None,
        "eta_min": None,
        "done_at": None,
    }
    save()
 
    await m.answer(f"✅ Buyurtma #{oid} qabul qilindi. Tez orada kuryer tayinlanadi.",
                   reply_markup=ReplyKeyboardRemove())
    await m.answer("Kerak bo'lsa, buyurtmani bekor qilishingiz mumkin:",
                   reply_markup=kb([("❌ Buyurtmani bekor qilish", f"cancel:{oid}")]))
 
    buttons = [[(f"🚴 {v['name']}", f"assign:{oid}:{cid}")] for cid, v in COURIERS.items()]
    buttons.append([("🚫 Rad etish", f"reject:{oid}")])
    await bot.send_message(ADMIN_ID, f"{order_text(oid)}\n\nKuryerni tanlang:", reply_markup=kb(*buttons))
    if ORDERS[oid]["lat"] is not None:
        await bot.send_location(ADMIN_ID, ORDERS[oid]["lat"], ORDERS[oid]["lon"])
 
 
# ---------- MIJOZ: bekor qilish ----------
@router.callback_query(F.data.startswith("cancel:"))
async def cancel_order(c: CallbackQuery, bot: Bot):
    oid = int(c.data.split(":")[1])
    order = ORDERS.get(oid)
    if not order or order["client_id"] != c.from_user.id:
        return await c.answer("Ruxsat yo'q", show_alert=True)
    if order["status"] not in ("new", "assigned"):
        return await c.answer("Bu buyurtmani endi bekor qilib bo'lmaydi.", show_alert=True)
 
    order["status"] = "cancelled"
    save()
    await c.message.edit_text(f"❌ Buyurtma #{oid} bekor qilindi.")
    await bot.send_message(ADMIN_ID, f"❌ Mijoz buyurtma #{oid} ni bekor qildi.")
    if order["courier_id"]:
        await bot.send_message(order["courier_id"], f"❌ Buyurtma #{oid} mijoz tomonidan bekor qilindi.")
    await c.answer()
 
 
# ---------- ADMIN: kuryer tayinlash / rad etish ----------
@router.callback_query(F.data.startswith("assign:"))
async def assign(c: CallbackQuery, bot: Bot):
    if c.from_user.id != ADMIN_ID:
        return await c.answer("Ruxsat yo'q", show_alert=True)
    _, oid, cid = c.data.split(":")
    oid, cid = int(oid), int(cid)
    order = ORDERS.get(oid)
    if not order or order["status"] != "new":
        return await c.answer("Bu buyurtma allaqachon ko'rib chiqilgan yoki bekor qilingan.", show_alert=True)
 
    courier = COURIERS[cid]
    order["courier_id"] = cid
    order["status"] = "assigned"
    save()
 
    await c.message.edit_text(f"✅ Buyurtma #{oid} → {courier['name']} ga tayinlandi.")
 
    await bot.send_message(
        order["client_id"],
        f"🚴 Buyurtma #{oid} uchun kuryer tayinlandi:\n\n"
        f"👤 Ismi: {courier['name']}\n"
        f"📞 Telefon: {courier['phone']}\n\n"
        f"Kuryer yo'lga chiqqach, sizga xabar beramiz.",
    )
    await bot.send_message(cid, order_text(oid), reply_markup=kb([("🚀 Yo'lga chiqdim", f"go:{oid}")]))
    if order["lat"] is not None:
        await bot.send_location(cid, order["lat"], order["lon"])
    await c.answer()
 
 
@router.callback_query(F.data.startswith("reject:"))
async def reject(c: CallbackQuery, bot: Bot):
    if c.from_user.id != ADMIN_ID:
        return await c.answer("Ruxsat yo'q", show_alert=True)
    oid = int(c.data.split(":")[1])
    order = ORDERS.get(oid)
    if not order or order["status"] != "new":
        return await c.answer("Bu buyurtma allaqachon ko'rib chiqilgan.", show_alert=True)
 
    order["status"] = "cancelled"
    save()
    await c.message.edit_text(f"🚫 Buyurtma #{oid} rad etildi.")
    await bot.send_message(order["client_id"],
                           f"😔 Afsuski, buyurtma #{oid} hozircha qabul qilinmadi. Keyinroq urinib ko'ring.")
    await c.answer()
 
 
# ---------- KURYER: yo'lga chiqdi ----------
def courier_guard(c: CallbackQuery, order: dict | None, need_status: str) -> str | None:
    """Xatolik matnini qaytaradi, hammasi joyida bo'lsa None."""
    if not order or order["courier_id"] != c.from_user.id:
        return "Bu buyurtma sizga tegishli emas."
    if order["status"] == "cancelled":
        return "Bu buyurtma bekor qilingan."
    if order["status"] != need_status:
        return "Bu amal allaqachon bajarilgan."
    return None
 
 
@router.callback_query(F.data.startswith("go:"))
async def go(c: CallbackQuery):
    oid = int(c.data.split(":")[1])
    err = courier_guard(c, ORDERS.get(oid), "assigned")
    if err:
        return await c.answer(err, show_alert=True)
 
    await c.message.edit_text(
        f"Buyurtma #{oid}: necha daqiqada yetib borasiz?",
        reply_markup=kb(
            [("5 daq", f"eta:{oid}:5"), ("10 daq", f"eta:{oid}:10"), ("15 daq", f"eta:{oid}:15")],
            [("20 daq", f"eta:{oid}:20"), ("30 daq", f"eta:{oid}:30"), ("45 daq", f"eta:{oid}:45")],
        ),
    )
    await c.answer()
 
 
@router.callback_query(F.data.startswith("eta:"))
async def eta(c: CallbackQuery, bot: Bot):
    _, oid, minutes = c.data.split(":")
    oid, minutes = int(oid), int(minutes)
    order = ORDERS.get(oid)
    err = courier_guard(c, order, "assigned")
    if err:
        return await c.answer(err, show_alert=True)
 
    courier = COURIERS[order["courier_id"]]
    left = now()
    arrive = left + timedelta(minutes=minutes)
    order.update(status="on_way", left_at=left.isoformat(), eta_min=minutes)
    save()
 
    await c.message.edit_text(
        f"🚀 Buyurtma #{oid}: yo'lga chiqdingiz ({fmt(left)}). {minutes} daqiqada yetasiz.",
        reply_markup=kb([("✅ Yetkazdim", f"done:{oid}")]),
    )
    await bot.send_message(
        order["client_id"],
        f"🚀 Kuryer yo'lga chiqdi!\n\n"
        f"👤 Kuryer: {courier['name']}\n"
        f"📞 Telefon: {courier['phone']}\n"
        f"🕒 Chiqqan vaqti: {fmt(left)}\n"
        f"⏱ Yetib borish: {minutes} daqiqada\n"
        f"📍 Taxminiy kelish vaqti: {fmt(arrive)}",
    )
    await bot.send_message(ADMIN_ID, f"🚀 Buyurtma #{oid}: {courier['name']} yo'lga chiqdi ({minutes} daq).")
    await c.answer()
 
    asyncio.create_task(remind(bot, oid, minutes))
 
 
async def remind(bot: Bot, oid: int, minutes: int):
    await asyncio.sleep(minutes * 60)
    order = ORDERS.get(oid)
    if order and order["status"] == "on_way":
        await bot.send_message(order["client_id"],
                               f"⏰ Buyurtma #{oid}: kuryer yetib kelishi kerak bo'lgan vaqt bo'ldi.")
        await bot.send_message(order["courier_id"],
                               f"⏰ Buyurtma #{oid}: belgilangan vaqt tugadi. Mijoz kutmoqda: {order['phone']}")
 
 
# ---------- KURYER: yetkazdi ----------
@router.callback_query(F.data.startswith("done:"))
async def done(c: CallbackQuery, bot: Bot):
    oid = int(c.data.split(":")[1])
    order = ORDERS.get(oid)
    err = courier_guard(c, order, "on_way")
    if err:
        return await c.answer(err, show_alert=True)
 
    t = now()
    spent = int((t - datetime.fromisoformat(order["left_at"])).total_seconds() // 60)
    order.update(status="done", done_at=t.isoformat())
    save()
 
    await c.message.edit_text(f"✅ Buyurtma #{oid} yetkazildi ({fmt(t)}).")
    await bot.send_message(
        order["client_id"],
        f"✅ Buyurtma #{oid} yetkazildi!\n"
        f"🕒 Yetkazilgan vaqt: {fmt(t)}\n"
        f"⏱ Yo'lda: {spent} daqiqa\n\nRahmat! 🙏",
    )
    await bot.send_message(ADMIN_ID, f"✅ Buyurtma #{oid} yetkazildi ({fmt(t)}), yo'lda: {spent} daq.")
    await c.answer()
 
 
# ---------- Ro'yxatlar ----------
@router.message(Command("orders"))
async def list_orders(m: Message):
    if m.from_user.id != ADMIN_ID:
        return
    active = [(oid, o) for oid, o in ORDERS.items() if o["status"] in ("new", "assigned", "on_way")]
    if not active:
        return await m.answer("Faol buyurtmalar yo'q.")
    lines = []
    for oid, o in active:
        courier = COURIERS[o["courier_id"]]["name"] if o["courier_id"] else "—"
        lines.append(f"#{oid} | {STATUS_TEXT[o['status']]} | {o['client_name']} | kuryer: {courier}")
    await m.answer("📋 Faol buyurtmalar:\n\n" + "\n".join(lines))
 
 
@router.message(Command("myorders"))
async def my_orders(m: Message):
    mine = [(oid, o) for oid, o in ORDERS.items() if o["client_id"] == m.from_user.id][-5:]
    if not mine:
        return await m.answer("Sizda hali buyurtmalar yo'q.")
    lines = [f"#{oid} | {STATUS_TEXT[o['status']]} | {o['items'][:30]}" for oid, o in mine]
    await m.answer("🧾 Oxirgi buyurtmalaringiz:\n\n" + "\n".join(lines))
 
 
async def main():
    logging.basicConfig(level=logging.INFO)
    load()
    bot = Bot(TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await dp.start_polling(bot)
 
 
if __name__ == "__main__":
    asyncio.run(main())
