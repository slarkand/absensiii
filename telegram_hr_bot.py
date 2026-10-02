import os
import asyncio
import logging
import datetime
from functools import partial
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler,
    MessageHandler, ConversationHandler, filters
)
import absensi_api

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# States
(
    STATE_CAPTCHA,
    STATE_TIPE,
    STATE_NIP,
    STATE_TANGGAL,
    STATE_KETERANGAN,
    STATE_KATEGORI_CUTI,
    STATE_FILE,
    STATE_KONFIRMASI,
) = range(8)

api = absensi_api.AbsensiAPI()

TIPE_MAP = {
    "✅ wfo / hadir":  "wfo",
    "🚗 dinas luar":   "dinas luar",
    "🏠 wfh":          "wfh",
    "📝 ijin":         "ijin",
    "🌴 cuti":         "cuti",
    "🏥 sakit":        "sakit",
    "😷 isoman":       "isoman",
    "📨 undangan":     "undangan",
}

STATUS_EMOJI = {
    "wfo":        "✅", "hadir":      "✅",
    "dinas luar": "🚗", "wfh":        "🏠",
    "ijin":       "📝", "cuti":       "🌴",
    "sakit":      "🏥", "isoman":     "😷",
    "undangan":   "📨",
}

async def run_sync(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))

# ------------------------------------------------------------------ #
#  /start                                                              #
# ------------------------------------------------------------------ #
MENU_KEYBOARD = ReplyKeyboardMarkup(
    [["🔐 Login Absensi", "🚪 Logout"]],
    resize_keyboard=True,
    is_persistent=True,
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    try:
        img_bytes = await run_sync(api.get_captcha)
        await update.message.reply_photo(
            photo=img_bytes,
            caption=(
                "🔐 *Bot Absensi Kejaksaan*\n\n"
                "Ketik angka/huruf CAPTCHA pada gambar di atas untuk login:"
            ),
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        return STATE_CAPTCHA
    except Exception as e:
        logger.error(f"Captcha error: {e}")
        await update.message.reply_text(
            f"⚠️ Gagal memuat captcha.\n{e}\n\nTekan tombol Login Absensi untuk coba lagi.",
            reply_markup=MENU_KEYBOARD,
        )
        return ConversationHandler.END

# ------------------------------------------------------------------ #
#  CAPTCHA → login                                                     #
# ------------------------------------------------------------------ #
async def proses_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    captcha_text = update.message.text.strip()
    msg = await update.message.reply_text("⏳ Sedang login...")
    try:
        success = await run_sync(api.login, captcha_text)
    except Exception as e:
        await msg.edit_text(f"❌ Login error: {e}\n\nKetik /start untuk ulang.")
        return ConversationHandler.END

    if success:
        keyboard = [
            ["✅ WFO / Hadir", "🚗 Dinas Luar"],
            ["🏠 WFH", "📝 Ijin"],
            ["🌴 Cuti", "🏥 Sakit"],
            ["😷 Isoman", "📨 Undangan"],
            ["❌ Batal"],
        ]
        await msg.edit_text("✅ Login berhasil!")
        await update.message.reply_text(
            "Pilih kategori absensi:",
            reply_markup=ReplyKeyboardMarkup(
                keyboard, resize_keyboard=True, one_time_keyboard=True
            ),
        )
        return STATE_TIPE
    else:
        await msg.edit_text(
            "❌ Login gagal (captcha/kredensial salah).\nKetik /start untuk ulang."
        )
        return ConversationHandler.END

# ------------------------------------------------------------------ #
#  Pilih tipe                                                          #
# ------------------------------------------------------------------ #
async def pilih_tipe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.lower().strip()
    if "batal" in raw:
        await update.message.reply_text("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    tipe = TIPE_MAP.get(raw)
    if not tipe:
        await update.message.reply_text("⚠️ Pilihan tidak valid. Gunakan tombol di bawah.")
        return STATE_TIPE

    context.user_data["tipe"] = tipe
    await update.message.reply_text(
        f"Kategori: {STATUS_EMOJI.get(tipe,'')} *{tipe.title()}*\n\n"
        "Masukkan *NIP* pegawai (18 digit):",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return STATE_NIP

# ------------------------------------------------------------------ #
#  Input NIP                                                           #
# ------------------------------------------------------------------ #
async def proses_nip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    nip = update.message.text.strip()
    if not nip.isdigit() or len(nip) != 18:
        await update.message.reply_text("⚠️ NIP harus 18 digit angka. Coba lagi:")
        return STATE_NIP

    context.user_data["nip"] = nip

    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    keyboard = [
        [f"📅 Hari ini ({today.strftime('%Y-%m-%d')})",
         f"📅 Kemarin ({yesterday.strftime('%Y-%m-%d')})"],
        ["❌ Batal"],
    ]
    await update.message.reply_text(
        "Pilih tanggal atau ketik manual (format: YYYY-MM-DD):",
        reply_markup=ReplyKeyboardMarkup(
            keyboard, resize_keyboard=True, one_time_keyboard=True
        ),
    )
    return STATE_TANGGAL

# ------------------------------------------------------------------ #
#  Input tanggal                                                       #
# ------------------------------------------------------------------ #
async def proses_tanggal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip().lower()
    if "batal" in raw:
        await update.message.reply_text("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    if "hari ini" in raw:
        tgl = datetime.date.today().strftime("%Y-%m-%d")
    elif "kemarin" in raw:
        tgl = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        tgl = raw
        # Validasi format
        try:
            datetime.datetime.strptime(tgl, "%Y-%m-%d")
        except ValueError:
            await update.message.reply_text(
                "⚠️ Format tanggal salah. Gunakan YYYY-MM-DD (contoh: 2026-09-28):"
            )
            return STATE_TANGGAL

    context.user_data["tanggal"] = tgl
    await update.message.reply_text(
        "✍️ Masukkan *keterangan*:\n"
        "(Contoh: Rapat Koordinasi Wilayah)",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return STATE_KETERANGAN

# ------------------------------------------------------------------ #
#  Input keterangan                                                    #
# ------------------------------------------------------------------ #
async def proses_keterangan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["keterangan"] = update.message.text.strip()
    tipe = context.user_data["tipe"]

    if tipe == "cuti":
        keyboard = [
            ["Cuti Tahunan", "Cuti Besar"],
            ["Melahirkan", "Alasan Penting"],
            ["Diluar Tanggungan Negara"],
            ["Penangguhan Tahun Lalu"],
        ]
        await update.message.reply_text(
            "🌴 Pilih *kategori cuti*:",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(
                keyboard, resize_keyboard=True, one_time_keyboard=True
            ),
        )
        return STATE_KATEGORI_CUTI

    # Non-cuti → langsung ke file
    return await _tanya_file(update, context)

# ------------------------------------------------------------------ #
#  Kategori cuti                                                       #
# ------------------------------------------------------------------ #
KATEGORI_MAP = {
    "cuti tahunan": "cuti tahunan",
    "cuti besar": "cuti besar",
    "melahirkan": "melahirkan",
    "alasan penting": "alasan penting",
    "diluar tanggungan negara": "cuti diluar tanggungan negara",
    "penangguhan tahun lalu": "cuti penangguhan tahun lalu",
}

async def proses_kategori_cuti(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip().lower()
    kategori = KATEGORI_MAP.get(raw, "cuti tahunan")
    context.user_data["kategori_cuti"] = kategori
    return await _tanya_file(update, context)

# ------------------------------------------------------------------ #
#  Tanya file lampiran                                                 #
# ------------------------------------------------------------------ #
async def _tanya_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Tampilkan ringkasan dulu
    ud = context.user_data
    tipe = ud["tipe"]
    emoji = STATUS_EMOJI.get(tipe, "")
    lines = [
        "📋 *Ringkasan Data:*",
        f"  Kategori : {emoji} {tipe.title()}",
        f"  NIP      : `{ud['nip']}`",
        f"  Tanggal  : {ud['tanggal']}",
        f"  Keterangan: {ud['keterangan']}",
    ]
    if tipe == "cuti":
        lines.append(f"  Jenis Cuti: {ud.get('kategori_cuti','')}")

    lines.append("\n📎 Kirim file *Surat Keterangan* (foto/pdf)")
    lines.append("atau tekan tombol Lewati jika tidak ada lampiran.")

    keyboard = [["⏩ Lewati (Tanpa File)"]]
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            keyboard, resize_keyboard=True, one_time_keyboard=True
        ),
    )
    return STATE_FILE

# ------------------------------------------------------------------ #
#  Proses file & submit                                                #
# ------------------------------------------------------------------ #
async def proses_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    file_path = None

    if update.message.photo:
        f = await update.message.photo[-1].get_file()
        file_path = "lampiran.jpg"
        await f.download_to_drive(file_path)
    elif update.message.document:
        f = await update.message.document.get_file()
        file_path = update.message.document.file_name or "lampiran.pdf"
        await f.download_to_drive(file_path)
    elif update.message.text and (
        "lewati" in update.message.text.lower() or "skip" in update.message.text.lower()
    ):
        pass
    else:
        await update.message.reply_text("⚠️ Kirim file atau klik tombol Lewati.")
        return STATE_FILE

    msg = await update.message.reply_text(
        "⏳ Menyimpan ke website absensi...", reply_markup=ReplyKeyboardRemove()
    )

    ud = context.user_data
    try:
        ok, result_msg = await run_sync(
            api.submit_data,
            tipe=ud["tipe"],
            nip=ud["nip"],
            tanggal=ud["tanggal"],
            keterangan=ud["keterangan"],
            kategori_cuti=ud.get("kategori_cuti", ""),
            surat_path=file_path,
        )
        if ok:
            await update.message.reply_text(
                f"✅ *BERHASIL DISIMPAN*\n\n{result_msg}\n\n"
                "Ketik /start untuk input data lain.",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                f"❌ *GAGAL*\n\n{result_msg}\n\n"
                "Ketik /start untuk coba lagi.",
                parse_mode="Markdown",
            )
    except Exception as e:
        logger.error(f"Submit error: {e}")
        await update.message.reply_text(f"❌ *ERROR*\n\n{e}", parse_mode="Markdown")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

    context.user_data.clear()
    return ConversationHandler.END

# ------------------------------------------------------------------ #
#  /cancel & /logout                                                   #
# ------------------------------------------------------------------ #
async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ok, msg_text = await run_sync(api.logout)
    if ok:
        await update.message.reply_text(
            "✅ Logout berhasil. Sesi dihapus.",
            reply_markup=MENU_KEYBOARD
        )
    else:
        await update.message.reply_text(f"❌ Gagal logout: {msg_text}", reply_markup=MENU_KEYBOARD)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Dibatalkan.", reply_markup=MENU_KEYBOARD)
    context.user_data.clear()
    return ConversationHandler.END

# ------------------------------------------------------------------ #
#  main                                                                #
# ------------------------------------------------------------------ #
def main():
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .build()
    )
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("(?i).*login absensi.*"), start),
        ],
        states={
            STATE_CAPTCHA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, proses_captcha)
            ],
            STATE_TIPE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, pilih_tipe)
            ],
            STATE_NIP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, proses_nip)
            ],
            STATE_TANGGAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, proses_tanggal)
            ],
            STATE_KETERANGAN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, proses_keterangan)
            ],
            STATE_KATEGORI_CUTI: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, proses_kategori_cuti)
            ],
            STATE_FILE: [
                MessageHandler(filters.PHOTO, proses_file),
                MessageHandler(filters.Document.ALL, proses_file),
                MessageHandler(filters.TEXT & ~filters.COMMAND, proses_file),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(MessageHandler(filters.Regex("(?i).*logout.*"), logout))

    # Tampilkan menu utama saat user kirim pesan apapun ke bot baru
    async def post_init(application):
        await application.bot.set_my_commands([
            ("start", "Login & Input Absensi"),
            ("logout", "Logout dari sistem"),
            ("cancel", "Batalkan proses"),
        ])

    app.post_init = post_init

    logger.info("Bot berjalan...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
