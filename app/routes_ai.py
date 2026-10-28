import os
import re
import json
import urllib.request
import pymupdf
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, g, flash, redirect, url_for
from app.extensions import db
from app.models import Urun, Musteri, Islem, IslemKalemi, StokHareketi
from app.auth import login_required
from app.routes_stok import akilli_urun_sorgusu_uygula, _temiz_float
from app.routes_main import yeni_fis_no_uret

ai_bp = Blueprint("ai", __name__)


def _stokta_urun_eslestir(ham_ad, ham_marka=""):
    """
    PDF satırındaki ürün adını/model kodunu (ör. 'TC-C34GS tiandy 4MP IP bulled kamera',
    'VP-4P-2UP videopark 4lü poe switch', 'RG-EST100-E rujie acces point')
    veritabanındaki gerçek stok kartıyla eşleştirir.
    """
    tam_metin = f"{ham_marka} {ham_ad}".strip()
    if not tam_metin:
        return None

    # 1. Model kodu adaylarını bul (Ör: TC-C34GS, VP-4P-2UP, RG-EST100-E, Piko-502HD, PL-8012, DS-2CD104162, LEO800AP)
    kelimeler = tam_metin.split()
    for kel in kelimeler:
        temiz_kel = kel.strip(",.;:()[]")
        if len(temiz_kel) >= 4 and any(c.isdigit() for c in temiz_kel) and any(c.isalpha() for c in temiz_kel):
            # Önce tam model kodu eşleşmesi ara
            u = Urun.query.filter(
                Urun.aktif == True,
                Urun.kod.ilike(temiz_kel)
            ).first()
            if u:
                return u
            # Tireleri kaldırarak ara
            norm_kel = temiz_kel.lower().replace("-", "")
            for aday in Urun.query.filter(Urun.aktif == True, Urun.kod != None).all():
                if aday.kod.lower().replace("-", "").replace(" ", "") == norm_kel:
                    return aday

    # 2. Akıllı ürün sorgusuyla tam metni dene
    adaylar = akilli_urun_sorgusu_uygula(Urun.query.filter_by(aktif=True), tam_metin).all()
    if len(adaylar) == 1:
        return adaylar[0]

    # 3. İlk 2-3 anlamlı kelime ile dene
    anlamli = [k for k in kelimeler if len(k) > 2 and k.lower() not in ("adet", "ad", "pcs", "metre")]
    if anlamli:
        adaylar2 = akilli_urun_sorgusu_uygula(Urun.query.filter_by(aktif=True), " ".join(anlamli[:2])).all()
        if len(adaylar2) == 1:
            return adaylar2[0]

    return None


def pdf_metnini_ayristir(metin, dosya_adi=""):
    """
    Hem Aronium Fatura PDF'lerini, hem Fiyat Teklifi / Montaj Listesi PDF'lerini,
    hem de Toptancı Ekstre PDF'lerini akıllıca analiz edip yapılandırılmış
    Montaj/Satış formuna dönüştürür.
    """
    satirlar = [s.strip() for s in metin.splitlines() if s.strip()]
    dosya_temiz = os.path.splitext(os.path.basename(dosya_adi))[0] if dosya_adi else ""

    sonuc = {
        "belge_turu": "montaj",
        "musteri_adi": "",
        "fatura_no": "",
        "tarih": datetime.now().strftime("%Y-%m-%d"),
        "montaj_basligi": "",
        "montaj_adresi": "",
        "kalemler": [],
        "ham_metin": metin,
    }

    # 1. Müşteri Adı, Tarih ve Başlık Tespiti
    for idx, s in enumerate(satirlar):
        s_low = s.lower()
        if s_low in ("faturalanan", "faturalanan:", "müşteri", "müşteri:", "cari:") and idx + 1 < len(satirlar):
            aday_musteri = satirlar[idx + 1]
            if aday_musteri.lower() not in ("fatura no.:", "tarih:"):
                sonuc["musteri_adi"] = aday_musteri

        if s_low in ("fatura no.:", "fatura no:", "fiş no:") and idx + 1 < len(satirlar):
            sonuc["fatura_no"] = satirlar[idx + 1]

        if s_low in ("tarih:", "tarih") and idx + 1 < len(satirlar):
            t_str = satirlar[idx + 1]
            m_t = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", t_str)
            if m_t:
                gun, ay, yil = int(m_t.group(1)), int(m_t.group(2)), int(m_t.group(3))
                sonuc["tarih"] = f"{yil:04d}-{ay:02d}-{gun:02d}"

        if "fiyat listesi" in s_low or "kurulum" in s_low or "teklif" in s_low or "montaj" in s_low:
            if not sonuc["montaj_basligi"] and len(s) < 120:
                sonuc["montaj_basligi"] = s
                if "," in s and not sonuc["musteri_adi"]:
                    sonuc["musteri_adi"] = s.split(",")[0].strip()

    if not sonuc["musteri_adi"] and dosya_temiz:
        # Dosya adından müşteri adını çıkar (Ör: 'avukat cafer yılmaz.pdf' -> 'Avukat Cafer Yılmaz')
        if not dosya_temiz.isdigit():
            sonuc["musteri_adi"] = dosya_temiz.title()

    if not sonuc["montaj_basligi"]:
        sonuc["montaj_basligi"] = f"{sonuc['musteri_adi'] or 'Saha'} Montaj / Malzeme Listesi"

    # 2. Kalemleri (Ürünleri) Çıkar
    kalemler_ham = []

    # Desen A: Aronium Fatura formatı (#, Öğe, Adet, Birim Fiyat, Vergi, İndirim)
    # Örn:
    # 1
    # TC-C32GN tiandy 2MB IP bulled kamera
    # 1
    # 0.00
    # 0.00%
    if "Öğe" in satirlar or "Created with Aronium" in metin:
        try:
            bas_idx = satirlar.index("İndirim") + 1 if "İndirim" in satirlar else (satirlar.index("Öğe") + 5)
        except ValueError:
            bas_idx = 0

        i = bas_idx
        while i < len(satirlar):
            s = satirlar[i]
            if s.startswith("₺") or s.lower().startswith("aratoplam") or s.lower().startswith("toplam"):
                break
            if s.isdigit() and i + 2 < len(satirlar):
                urun_adi = satirlar[i + 1]
                adet_str = satirlar[i + 2]
                fiyat_str = satirlar[i + 3] if i + 3 < len(satirlar) else "0"
                if re.match(r"^\d+([.,]\d+)?$", adet_str):
                    kalemler_ham.append({
                        "marka": "",
                        "urun_adi": urun_adi,
                        "miktar": _temiz_float(adet_str, 1.0),
                        "birim_fiyat": _temiz_float(fiyat_str, 0.0),
                    })
                    # Sonraki sıra numarasına kadar ilerle
                    i += 4
                    while i < len(satirlar) and not (satirlar[i].isdigit() and i + 1 < len(satirlar) and not satirlar[i + 1].endswith("%")):
                        if satirlar[i].startswith("₺") or satirlar[i].lower().startswith("aratoplam"):
                            break
                        i += 1
                    continue
            i += 1

    # Desen B: Tablo / Teklif / Liste Formatı (Sıra | Marka/Ürün | Açıklama | Adet | Birim Fiyat | Toplam)
    if not kalemler_ham:
        # "Toplam Fiyat" veya "Birim Fiyat" başlığından sonrasına bak
        bas_idx = 0
        has_marka_col = any(x.lower() == "marka" for x in satirlar[:15]) and any(x.lower() == "açıklama" for x in satirlar[:15])
        for idx, s in enumerate(satirlar[:20]):
            if s.lower() in ("toplam fiyat", "birim fiyat", "adet"):
                bas_idx = idx + 1

        i = bas_idx
        while i < len(satirlar):
            s = satirlar[i]
            if "genel toplam" in s.lower() or "aratoplam" in s.lower():
                break

            # Ekstre formatı kontrolü: örn '20 Ad' veya '5 Pk'
            m_ekstre = re.match(r"^(\d+(?:[.,]\d+)?)\s*(Ad|Adet|Pk|Paket|Mt|Metre)$", s, re.IGNORECASE)
            if m_ekstre and i >= 1:
                miktar = _temiz_float(m_ekstre.group(1), 1.0)
                urun_adi = satirlar[i - 1]
                fiyat = _temiz_float(satirlar[i + 1], 0.0) if i + 1 < len(satirlar) else 0.0
                kalemler_ham.append({
                    "marka": "",
                    "urun_adi": urun_adi,
                    "miktar": miktar,
                    "birim_fiyat": fiyat,
                })
                i += 2
                continue

            if s.isdigit() and int(s) < 200 and i + 2 < len(satirlar):
                if has_marka_col and i + 3 < len(satirlar) and re.match(r"^\d+([.,]\d+)?$", satirlar[i + 3]):
                    marka = satirlar[i + 1]
                    aciklama = satirlar[i + 2]
                    miktar = _temiz_float(satirlar[i + 3], 1.0)
                    fiyat = 0.0
                    if i + 4 < len(satirlar) and re.match(r"^[\d.,]+$", satirlar[i + 4]):
                        fiyat = _temiz_float(satirlar[i + 4], 0.0)
                    birlesik_ad = f"{marka} {aciklama}".strip() if marka.lower() != aciklama.lower() else marka
                    kalemler_ham.append({
                        "marka": marka,
                        "urun_adi": birlesik_ad,
                        "miktar": miktar,
                        "birim_fiyat": fiyat,
                    })
                    i += 6 if (i + 5 < len(satirlar) and re.match(r"^[\d.,]+$", satirlar[i + 5])) else 4
                    continue
                elif re.match(r"^\d+([.,]\d+)?$", satirlar[i + 2]):
                    urun_adi = satirlar[i + 1]
                    miktar = _temiz_float(satirlar[i + 2], 1.0)
                    fiyat = 0.0
                    # Eğer sonraki satır yeni sıra numarası değilse ve fiyat gibiyse
                    if i + 3 < len(satirlar) and re.match(r"^[\d.,]+$", satirlar[i + 3]) and int(float(satirlar[i + 3].replace(".", "").replace(",", "."))) != int(s) + 1:
                        fiyat = _temiz_float(satirlar[i + 3], 0.0)
                        i += 5
                    else:
                        i += 3
                    kalemler_ham.append({
                        "marka": "",
                        "urun_adi": urun_adi,
                        "miktar": miktar,
                        "birim_fiyat": fiyat,
                    })
                    continue
            i += 1

    # 3. Her kalemi veritabanındaki Stok Kartlarıyla eşleştir
    dolar_kuru = g.ayarlar.dolar_kuru if g.get("ayarlar") else 35.0
    for kh in kalemler_ham:
        eslesen_urun = _stokta_urun_eslestir(kh["urun_adi"], kh.get("marka", ""))
        birim = "Metre" if "metre" in kh["urun_adi"].lower() else "Adet"
        fiyat = kh["birim_fiyat"]

        if eslesen_urun:
            if fiyat <= 0 and eslesen_urun.satis_fiyati > 0:
                fiyat = eslesen_urun.satis_fiyati
            elif fiyat <= 0 and eslesen_urun.aktif_maliyet_tl(dolar_kuru) > 0:
                fiyat = eslesen_urun.aktif_maliyet_tl(dolar_kuru)

            sonuc["kalemler"].append({
                "eslesti": True,
                "urun_id": eslesen_urun.id,
                "barkod": eslesen_urun.barkod or "",
                "kod": eslesen_urun.kod or "",
                "pdf_urun_adi": kh["urun_adi"],
                "urun_adi": f"{eslesen_urun.ad} [{eslesen_urun.kod}]" if eslesen_urun.kod else eslesen_urun.ad,
                "stok_miktari": eslesen_urun.stok_miktari,
                "birim": eslesen_urun.birim or birim,
                "miktar": kh["miktar"],
                "birim_fiyat": round(fiyat, 2),
            })
        else:
            sonuc["kalemler"].append({
                "eslesti": False,
                "urun_id": None,
                "barkod": "",
                "kod": "",
                "pdf_urun_adi": kh["urun_adi"],
                "urun_adi": kh["urun_adi"],
                "stok_miktari": 0,
                "birim": birim,
                "miktar": kh["miktar"],
                "birim_fiyat": round(fiyat, 2),
            })

    # Müşteri veritabanında kayıtlı mı kontrol et
    eslesen_musteri = None
    if sonuc["musteri_adi"]:
        eslesen_musteri = Musteri.query.filter(
            Musteri.ad_soyad.ilike(f"%{sonuc['musteri_adi']}%")
        ).first()
    sonuc["eslesen_musteri_id"] = eslesen_musteri.id if eslesen_musteri else ""

    return sonuc


def _ornek_pdf_klasorunu_bul():
    yerel = r"C:\Users\senel\Desktop\dükkan\satışlar"
    if os.path.exists(yerel):
        return yerel
    return os.path.join(os.path.dirname(__file__), "ornek_pdfler")


@ai_bp.route("/ai-pdf")
@login_required
def ai_pdf_ekrani():
    # Masaüstündeki 'satışlar' veya buluttaki 'ornek_pdfler' klasöründeki örnek PDF'leri listele
    satislar_klasoru = _ornek_pdf_klasorunu_bul()
    hazir_pdfler = []
    if os.path.exists(satislar_klasoru):
        for f in sorted(os.listdir(satislar_klasoru)):
            if f.lower().endswith(".pdf"):
                hazir_pdfler.append(f)

    musteriler = Musteri.query.order_by(Musteri.ad_soyad.asc()).all()
    return render_template("ai_pdf.html", hazir_pdfler=hazir_pdfler, musteriler=musteriler)


@ai_bp.route("/api/ai-pdf-cozumle", methods=["POST"])
@login_required
def api_ai_pdf_cozumle():
    try:
        hazir_dosya = request.form.get("hazir_dosya", "").strip()
        if hazir_dosya:
            guvenli_ad = os.path.basename(hazir_dosya)
            tam_yol = os.path.join(_ornek_pdf_klasorunu_bul(), guvenli_ad)
            if not os.path.exists(tam_yol):
                return jsonify({"basarili": False, "mesaj": "PDF dosyası bulunamadı."}), 404
            doc = pymupdf.open(tam_yol)
            dosya_adi = guvenli_ad
        else:
            dosya = request.files.get("pdf_dosyasi")
            if not dosya or not dosya.filename:
                return jsonify({"basarili": False, "mesaj": "Lütfen bir PDF dosyası seçin."}), 400
            pdf_bytes = dosya.read()
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            dosya_adi = dosya.filename

        tum_metin = "\n".join(page.get_text("text") for page in doc)
        doc.close()

        cozum = pdf_metnini_ayristir(tum_metin, dosya_adi=dosya_adi)
        cozum["basarili"] = True
        return jsonify(cozum)
    except Exception as e:
        return jsonify({"basarili": False, "mesaj": f"PDF çözümleme hatası: {e}"}), 500
