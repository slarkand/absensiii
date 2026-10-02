import os
import logging
import requests
from datetime import date
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

USERNAME = os.getenv("ABSENSI_USERNAME")
PASSWORD = os.getenv("ABSENSI_PASSWORD")
BASE_URL  = "https://absensi.kejaksaan.go.id"
LOGIN_URL = f"{BASE_URL}/login"

logger = logging.getLogger(__name__)

STATUS_MAP = {
    "undangan":   "8",
    "isoman":     "7",
    "sakit":      "6",
    "cuti":       "5",
    "ijin":       "4",
    "wfh":        "3",
    "dinas luar": "2",
    "wfo":        "1",
}

def _abs_url(href: str) -> str:
    """Pastikan URL selalu absolute."""
    if href.startswith("http"):
        return href
    return f"{BASE_URL}/{href.lstrip('/')}"


class AbsensiAPI:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        })
        self.login_token = ""
        self._logged_in  = False

    # ------------------------------------------------------------------ #
    #  CAPTCHA                                                             #
    # ------------------------------------------------------------------ #
    def get_captcha(self) -> bytes:
        res = self.session.get(LOGIN_URL, timeout=30)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")

        t = soup.find("input", {"name": "_token"})
        if t:
            self.csrf_token = t["value"]
            self.login_token = self.csrf_token

        img = soup.find("img", src=lambda s: s and "captcha" in s.lower())
        if not img:
            raise Exception("Captcha tidak ditemukan di halaman login")

        cap_url = _abs_url(img["src"])
        cap_res = self.session.get(cap_url, timeout=30)
        cap_res.raise_for_status()
        return cap_res.content

    # ------------------------------------------------------------------ #
    #  LOGIN                                                               #
    # ------------------------------------------------------------------ #
    def login(self, captcha_text: str) -> bool:
        payload = {
            "_token":   self.login_token,
            "username": USERNAME,
            "password": PASSWORD,
            "captcha":  captcha_text.strip(),
        }
        res = self.session.post(LOGIN_URL, data=payload, timeout=30, allow_redirects=True)

        # Cek apakah sudah masuk dashboard
        success_keywords = ["logout", "dashboard", "berhasil", "absensi/create", "data absensi"]
        html_lower = res.text.lower()
        self._logged_in = any(k in html_lower for k in success_keywords)

        if not self._logged_in:
            # Coba ambil pesan error dari halaman
            soup = BeautifulSoup(res.text, "html.parser")
            alert = soup.find(class_=lambda c: c and "alert" in c)
            err_msg = alert.get_text(strip=True) if alert else "Periksa username/password/captcha"
            logger.warning(f"Login gagal. Resp URL: {res.url} | Pesan: {err_msg}")

        return self._logged_in

    def _refresh_csrf(self):
        """Ambil CSRF token terbaru dari halaman create."""
        try:
            res = self.session.get(f"{BASE_URL}/absensi/create", timeout=30)
            soup = BeautifulSoup(res.text, "html.parser")
            form = soup.find("form", {"id": "form-add-absensi"})
            t = form.find("input", {"name": "_token"}) if form else soup.find("input", {"name": "_token"})
            if t:
                self.csrf_token = t["value"]
                logger.info(f"CSRF token diperbarui: {self.csrf_token[:10]}...")
        except Exception as e:
            logger.warning(f"Gagal refresh CSRF: {e}")

    def logout(self):
        """Logout dari sistem absensi."""
        if not self._logged_in:
            return True, "Belum login."
        try:
            self._refresh_csrf()
            payload = {"_token": self.csrf_token}
            res = self.session.post(f"{BASE_URL}/logout", data=payload, timeout=30, allow_redirects=False)
            self._logged_in = False
            self.session.cookies.clear()
            return True, "Berhasil logout."
        except Exception as e:
            return False, f"Gagal logout: {e}"

    # ------------------------------------------------------------------ #
    #  SUBMIT                                                              #
    # ------------------------------------------------------------------ #
    def submit_data(self, tipe: str, tanggal: str, nip: str,
                    keterangan: str = "", kategori_cuti: str = "",
                    surat_path: str = None,
                    lokasi: str = "-7.4308395,111.0041885",
                    waktu_in: str = "", waktu_out: str = "") -> tuple[bool, str]:

        if not self._logged_in:
            raise Exception("Belum login. Panggil login() terlebih dahulu.")

        create_url = f"{BASE_URL}/absensi/create"

        # -- Ambil form page --
        res = self.session.get(create_url, timeout=30)
        res.raise_for_status()

        # Cek apakah masih login (redirect ke halaman login = sesi expired)
        if "login" in res.url.lower() and "absensi" not in res.url.lower():
            self._logged_in = False
            raise Exception("Sesi login habis. Mulai ulang dengan /start")

        soup = BeautifulSoup(res.text, "html.parser")

        # -- Ambil CSRF token dari form yang id-nya form-add-absensi --
        form = soup.find("form", {"id": "form-add-absensi"})
        if not form:
            form = soup.find("form", action=lambda x: x and "absensi" in x.lower())

        if form and form.get("action"):
            post_url = _abs_url(form["action"])
        else:
            post_url = f"{BASE_URL}/absensi"

        t = form.find("input", {"name": "_token"}) if form else soup.find("input", {"name": "_token"})
        if not t:
            raise Exception("CSRF token tidak ditemukan di form absensi")
        token = t["value"]

        status_val = STATUS_MAP.get(tipe.lower(), "8")
        logger.info(f"Submit: tipe={tipe} status={status_val} nip={nip} tgl={tanggal} post_url={post_url}")

        today = date.today().strftime("%Y-%m-%d")

        data = {
            "_token":           token,
            "tipe":             "per_nip",
            "nip[]":            nip.strip(),
            "dari_tgl":         today,
            "sampai_tgl":       today,
            "pilih_tgl":        tanggal.strip(),
            "status":           status_val,
            "keterangan":       keterangan,
            "menimpa":          "1",
            "waktu_clockin":    waktu_in if waktu_in else "08:00",
            "waktu_clockout":   waktu_out if waktu_out else "",
            "lokasi_clockin":   lokasi,
            "lokasi_clockout":  lokasi,
        }

        if tipe.lower() == "cuti" and kategori_cuti:
            data["kategori_cuti"] = kategori_cuti

        headers = {
            "X-CSRF-TOKEN":     token,
            "X-Requested-With": "XMLHttpRequest",
            "Accept":           "application/json, text/javascript, */*; q=0.01",
            "Referer":          f"{BASE_URL}/absensi/create",
        }

        # -- Kirim dengan atau tanpa file --
        try:
            if surat_path and os.path.exists(surat_path):
                with open(surat_path, "rb") as f:
                    files = {"surat-keterangan": f}
                    res = self.session.post(post_url, data=data, files=files,
                                           headers=headers, timeout=60, allow_redirects=False)
            else:
                res = self.session.post(post_url, data=data,
                                        headers=headers, timeout=60, allow_redirects=False)
        except requests.exceptions.RequestException as e:
            raise Exception(f"Koneksi error saat submit: {e}")

        logger.info(f"Submit response: HTTP {res.status_code} | URL: {res.url}")

        # 302 redirect ke /absensi = data berhasil disimpan (POST-redirect-GET pattern)
        if res.status_code == 302:
            location = res.headers.get("Location", "")
            logger.info(f"Redirect ke: {location}")
            return True, "Data berhasil disimpan ke web absensi"

        # Cek apakah responnya JSON
        try:
            json_res = res.json()
            logger.info(f"JSON response: {json_res}")
            if json_res.get("status") in ("success", True, 1, "1") or json_res.get("success"):
                return True, json_res.get("message") or "Data berhasil disimpan"
            if json_res.get("status") in ("error", False, 0, "0"):
                return False, json_res.get("message") or "Gagal disimpan"
            return True, f"Sukses: {json_res}"
        except Exception:
            pass

        # -- Parse response --
        html_lower = res.text.lower()
        soup_res   = BeautifulSoup(res.text, "html.parser")

        # Ambil pesan alert dari halaman response
        alert_el = soup_res.find(class_=lambda c: c and ("alert" in c or "success" in c or "error" in c or "danger" in c))
        alert_msg = alert_el.get_text(strip=True) if alert_el else ""

        # Log 500 karakter pertama response untuk debug
        logger.debug(f"Response snippet: {res.text[:500]}")

        # Keyword sukses
        sukses_kw = ["berhasil", "sukses", "saved", "success", "data absensi berhasil", "tersimpan"]
        # Keyword error
        error_kw  = ["gagal", "error", "invalid", "tidak valid", "unauthorized", "unauthenticated",
                     "expired", "failed", "wrong", "salah"]

        if any(k in html_lower for k in sukses_kw):
            pesan = alert_msg if alert_msg else "Data berhasil disimpan ke website"
            return True, pesan

        if any(k in html_lower for k in error_kw):
            pesan = alert_msg if alert_msg else "Website menolak data. Periksa NIP/tanggal/format."
            return False, pesan

        if res.status_code in (200, 302):
            # Tidak ketemu keyword apapun — kembalikan info untuk cek manual
            snippet = res.text[:300].replace("\n", " ").strip()
            return False, (
                f"Form dikirim (HTTP {res.status_code}) tapi respons tidak jelas.\n"
                f"URL akhir: {res.url}\n"
                f"Pesan website: {alert_msg or snippet}"
            )

        # HTTP error (termasuk 500) — log body dan kembalikan info
        snippet = res.text[:500].replace("\n", " ").strip()
        logger.error(f"HTTP {res.status_code} response: {snippet}")
        return False, (
            f"Server error HTTP {res.status_code}.\n"
            f"Detail: {snippet[:300]}"
        )
