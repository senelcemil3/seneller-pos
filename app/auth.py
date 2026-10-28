import io
import os
import base64
import shutil
from functools import wraps
import qrcode
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    g,
    jsonify,
    send_file,
    current_app,
)
from config import BASE_DIR
from app.extensions import db
from app.models import Kullanici, Ayarlar
from app import BAGLANTI_DURUMU, otomatik_yedek_al

auth_bp = Blueprint("auth", __name__)


def _qr_base64_uret(metin):
    if not metin:
        return ""
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(metin)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.url))
        return f(*args, **kwargs)

    return decorated_function


def patron_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login"))
        if not g.user.is_patron:
            flash("Bu ekrana sadece Patron (Yönetici) erişebilir.", "danger")
            return redirect(url_for("main.pos_ekrani"))
        return f(*args, **kwargs)

    return decorated_function


@auth_bp.before_app_request
def load_logged_in_user():
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
    else:
        g.user = db.session.get(Kullanici, user_id)
        if g.user and not g.user.aktif:
            session.clear()
            g.user = None

    ayar = Ayarlar.query.first()
    if not ayar:
        ayar = Ayarlar()
        db.session.add(ayar)
        db.session.commit()
    g.ayarlar = ayar


@auth_bp.route("/api/mobil-baglanti-qr")
def api_mobil_baglanti_qr():
    sabit = BAGLANTI_DURUMU.get("sabit_url") or "https://files.catbox.moe/eaalrw.html"
    sabit_patron = f"{sabit}?hesap=admin"
    sabit_eleman = f"{sabit}?hesap=eleman"
    yerel = BAGLANTI_DURUMU.get("yerel_url") or "http://127.0.0.1:5000"
    dis = BAGLANTI_DURUMU.get("dis_url")
    return jsonify({
        "sabit_url": sabit,
        "sabit_patron_url": sabit_patron,
        "sabit_patron_qr": _qr_base64_uret(sabit_patron),
        "sabit_eleman_url": sabit_eleman,
        "sabit_eleman_qr": _qr_base64_uret(sabit_eleman),
        "yerel_url": yerel,
        "yerel_qr": _qr_base64_uret(yerel),
        "dis_url": dis,
        "dis_qr": _qr_base64_uret(dis) if dis else "",
    })


@auth_bp.route("/oto-giris")
def oto_giris():
    """
    Sabit mobil giriş kapısından veya masaüstü kısayolundan gelen kullanıcıyı
    tekrar şifre sormadan doğrudan aynı uygulamaya sokar.
    """
    anahtar = request.args.get("k", "")
    hesap = request.args.get("hesap", "admin").strip()
    if anahtar == "snl2026pos":
        user = Kullanici.query.filter_by(kullanici_adi=hesap, aktif=True).first()
        if not user:
            user = Kullanici.query.filter_by(aktif=True).first()
        if user:
            session.permanent = True
            session["user_id"] = user.id
            return redirect(url_for("main.dashboard" if user.is_patron else "main.pos_ekrani"))
    return redirect(url_for("auth.login"))


@auth_bp.route("/giris", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        kullanici_adi = request.form.get("kullanici_adi", "").strip()
        sifre = request.form.get("sifre", "").strip()

        user = Kullanici.query.filter_by(kullanici_adi=kullanici_adi).first()
        if user and user.aktif and user.check_password(sifre):
            session.clear()
            session.permanent = True  # Telefonda 30 gün oturumu açık tutar
            session["user_id"] = user.id
            flash(f"Hoş geldiniz, {user.ad_soyad}!", "success")
            next_page = request.args.get("next")
            if next_page:
                return redirect(next_page)
            return redirect(url_for("main.dashboard" if user.is_patron else "main.pos_ekrani"))
        else:
            flash("Hatalı kullanıcı adı veya şifre!", "danger")

    tum_kullanicilar = Kullanici.query.filter_by(aktif=True).all()
    return render_template("login.html", kullanicilar=tum_kullanicilar)


@auth_bp.route("/cikis")
def logout():
    session.clear()
    flash("Oturum kapatıldı.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/personel", methods=["GET", "POST"])
@login_required
@patron_required
def personel_yonetimi():
    if request.method == "POST":
        islem = request.form.get("form_islem", "ekle")
        if islem == "ekle":
            ad_soyad = request.form.get("ad_soyad", "").strip()
            kullanici_adi = request.form.get("kullanici_adi", "").strip()
            sifre = request.form.get("sifre", "").strip()
            rol = request.form.get("rol", "personel")

            if not ad_soyad or not kullanici_adi or not sifre:
                flash("Ad Soyad, Kullanıcı Adı ve Şifre zorunludur.", "danger")
            elif Kullanici.query.filter_by(kullanici_adi=kullanici_adi).first():
                flash("Bu kullanıcı adı zaten kayıtlı.", "danger")
            else:
                yeni = Kullanici(
                    ad_soyad=ad_soyad,
                    kullanici_adi=kullanici_adi,
                    rol=rol,
                    yetki_maliyet_gor=(rol == "patron") or ("yetki_maliyet_gor" in request.form),
                    yetki_rapor_gor=(rol == "patron") or ("yetki_rapor_gor" in request.form),
                    yetki_stok_duzenle=(rol == "patron") or ("yetki_stok_duzenle" in request.form),
                    yetki_fiyat_degistir=(rol == "patron") or ("yetki_fiyat_degistir" in request.form),
                    yetki_urun_sil=(rol == "patron") or ("yetki_urun_sil" in request.form),
                )
                yeni.set_password(sifre)
                db.session.add(yeni)
                db.session.commit()
                flash(f"{ad_soyad} ({kullanici_adi}) personeli eklendi.", "success")

        elif islem == "guncelle":
            p_id = int(request.form.get("personel_id", 0))
            personel = db.session.get(Kullanici, p_id)
            if personel:
                personel.ad_soyad = request.form.get("ad_soyad", personel.ad_soyad).strip()
                rol = request.form.get("rol", personel.rol)
                personel.rol = rol
                yeni_sifre = request.form.get("yeni_sifre", "").strip()
                if yeni_sifre:
                    personel.set_password(yeni_sifre)
                if rol == "patron":
                    personel.yetki_maliyet_gor = True
                    personel.yetki_rapor_gor = True
                    personel.yetki_stok_duzenle = True
                    personel.yetki_fiyat_degistir = True
                    personel.yetki_urun_sil = True
                else:
                    personel.yetki_maliyet_gor = "yetki_maliyet_gor" in request.form
                    personel.yetki_rapor_gor = "yetki_rapor_gor" in request.form
                    personel.yetki_stok_duzenle = "yetki_stok_duzenle" in request.form
                    personel.yetki_fiyat_degistir = "yetki_fiyat_degistir" in request.form
                    personel.yetki_urun_sil = "yetki_urun_sil" in request.form
                personel.aktif = "aktif" in request.form or personel.id == g.user.id
                db.session.commit()
                flash(f"{personel.ad_soyad} yetkileri güncellendi.", "success")

        elif islem == "ayarlar":
            ayar = g.ayarlar
            ayar.sirket_adi = request.form.get("sirket_adi", ayar.sirket_adi).strip()
            ayar.alt_baslik = request.form.get("alt_baslik", ayar.alt_baslik).strip()
            ayar.telefon = request.form.get("telefon", ayar.telefon).strip()
            ayar.adres = request.form.get("adres", ayar.adres).strip()
            try:
                ayar.dolar_kuru = float(str(request.form.get("dolar_kuru", ayar.dolar_kuru)).replace(",", "."))
            except ValueError:
                pass
            try:
                ayar.varsayilan_kdv = float(str(request.form.get("varsayilan_kdv", ayar.varsayilan_kdv)).replace(",", "."))
            except ValueError:
                pass
            ayar.fis_alt_notu = request.form.get("fis_alt_notu", ayar.fis_alt_notu).strip()
            db.session.commit()
            flash("Şirket ve döviz kuru ayarları kaydedildi.", "success")

        elif islem == "simdi_yedekle":
            hedef = otomatik_yedek_al(current_app, etiket="manuel")
            if hedef:
                flash(f"Veritabanı yedeği başarıyla alındı: {os.path.basename(hedef)}", "success")
            else:
                flash("Yedek alınırken hata oluştu.", "danger")

        return redirect(url_for("auth.personel_yonetimi"))

    personeller = Kullanici.query.order_by(Kullanici.id.asc()).all()

    yedek_klasoru = os.path.join(BASE_DIR, "yedekler")
    os.makedirs(yedek_klasoru, exist_ok=True)
    yedekler = []
    for f in sorted(os.listdir(yedek_klasoru), reverse=True):
        if f.endswith(".db"):
            tam_yol = os.path.join(yedek_klasoru, f)
            boyut_kb = round(os.path.getsize(tam_yol) / 1024, 1)
            yedekler.append({"ad": f, "boyut_kb": boyut_kb})

    return render_template("personel.html", personeller=personeller, yedekler=yedekler[:12])


@auth_bp.route("/yedek-indir/<path:dosya_adi>")
@login_required
@patron_required
def yedek_indir(dosya_adi):
    guvenli_ad = os.path.basename(dosya_adi)
    tam_yol = os.path.join(BASE_DIR, "yedekler", guvenli_ad)
    if not os.path.exists(tam_yol):
        flash("Yedek dosyası bulunamadı.", "danger")
        return redirect(url_for("auth.personel_yonetimi"))
    return send_file(tam_yol, as_attachment=True, download_name=guvenli_ad)


def _bulut_ayar_oku():
    import json
    ayar_yolu = os.path.join(BASE_DIR, "bulut_ayar.json")
    if os.path.exists(ayar_yolu):
        try:
            with open(ayar_yolu, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "bulut_url": BAGLANTI_DURUMU.get("bulut_url", ""),
        "aktif_mod": "bulut" if BAGLANTI_DURUMU.get("bulut_aktif") else "yerel",
        "github_repo": "https://github.com/senelcemil3/seneller-pos",
    }


@auth_bp.route("/bulut", methods=["GET", "POST"])
@login_required
@patron_required
def bulut_yonetimi():
    import json
    import urllib.request

    ayar_yolu = os.path.join(BASE_DIR, "bulut_ayar.json")
    mevcut = _bulut_ayar_oku()

    if request.method == "POST":
        islem = request.form.get("islem", "sabitle")
        if islem == "sabitle":
            girilen_url = request.form.get("bulut_url", "").strip().rstrip("/")
            if girilen_url and not girilen_url.startswith("http"):
                girilen_url = "https://" + girilen_url
            if not girilen_url:
                flash("Lütfen geçerli bir Bulut Sunucu adresi (ör. https://seneller-pos.onrender.com) girin.", "danger")
            else:
                mevcut["bulut_url"] = girilen_url
                mevcut["aktif_mod"] = "bulut"
                with open(ayar_yolu, "w", encoding="utf-8") as f:
                    json.dump(mevcut, f, ensure_ascii=False, indent=2)
                BAGLANTI_DURUMU["bulut_url"] = girilen_url
                BAGLANTI_DURUMU["bulut_aktif"] = True
                BAGLANTI_DURUMU["dis_url"] = girilen_url
                try:
                    req = urllib.request.Request(
                        "https://ntfy.sh/seneller_pos_kapi_88421",
                        data=girilen_url.encode("utf-8"),
                        method="PUT",
                    )
                    urllib.request.urlopen(req, timeout=5)
                    flash(
                        f"Sabit Telefon Kapısı 7/24 Bulut Sunucusuna ({girilen_url}) sabitlendi! Bilgisayarınız kapalı olsa bile telefonlar bu adrese bağlanacak.",
                        "success",
                    )
                except Exception as e:
                    flash(f"Bulut adresi kaydedildi ancak kapı güncellenemedi: {e}", "warning")
        elif islem == "yerel_moda_don":
            mevcut["aktif_mod"] = "yerel"
            with open(ayar_yolu, "w", encoding="utf-8") as f:
                json.dump(mevcut, f, ensure_ascii=False, indent=2)
            BAGLANTI_DURUMU["bulut_aktif"] = False
            flash("Sistem tekrar Dükkân Bilgisayarı (Yerel Tünel) moduna alındı.", "info")

        return redirect(url_for("auth.bulut_yonetimi"))

    sabit = BAGLANTI_DURUMU.get("sabit_url") or "https://files.catbox.moe/eaalrw.html"
    return render_template(
        "bulut.html",
        bulut_ayar=mevcut,
        sabit_patron_url=f"{sabit}?hesap=admin",
        sabit_eleman_url=f"{sabit}?hesap=eleman",
        sabit_patron_qr=_qr_base64_uret(f"{sabit}?hesap=admin"),
        sabit_eleman_qr=_qr_base64_uret(f"{sabit}?hesap=eleman"),
    )


@auth_bp.route("/bulut/paket-indir")
@login_required
@patron_required
def bulut_paket_indir():
    zip_yolu = r"C:\Users\senel\Desktop\dükkan\seneller_pos_bulut_paketi.zip"
    if not os.path.exists(zip_yolu):
        flash("Bulut kurulum paketi hazırlanıyor, lütfen tekrar deneyin.", "warning")
        return redirect(url_for("auth.bulut_yonetimi"))
    return send_file(zip_yolu, as_attachment=True, download_name="seneller_pos_bulut_paketi.zip")
