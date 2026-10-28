from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, g
from sqlalchemy import or_, func
from app.extensions import db
from app.models import (
    Urun,
    Musteri,
    Tedarikci,
    Islem,
    IslemKalemi,
    StokHareketi,
    KasaHareketi,
    Kullanici,
)
from app.auth import login_required, patron_required
from app.routes_stok import akilli_urun_sorgusu_uygula

main_bp = Blueprint("main", __name__)


def yeni_fis_no_uret(prefix="SNL"):
    bugun_str = datetime.now().strftime("%Y%m%d")
    bugun_bas = datetime.combine(date.today(), datetime.min.time())
    sayac = Islem.query.filter(Islem.tarih >= bugun_bas).count() + 1
    aday = f"{prefix}-{bugun_str}-{sayac:03d}"
    while Islem.query.filter_by(fis_no=aday).first():
        sayac += 1
        aday = f"{prefix}-{bugun_str}-{sayac:03d}"
    return aday


@main_bp.route("/")
@login_required
def dashboard():
    bugun_bas = datetime.combine(date.today(), datetime.min.time())

    toplam_urun_cesidi = Urun.query.filter_by(aktif=True).count()
    kritik_urunler = (
        Urun.query.filter(Urun.aktif == True, Urun.stok_miktari <= Urun.kritik_stok)
        .order_by(Urun.stok_miktari.asc())
        .limit(12)
        .all()
    )
    kritik_stok_sayisi = Urun.query.filter(
        Urun.aktif == True, Urun.stok_miktari <= Urun.kritik_stok
    ).count()

    bugun_islemler = Islem.query.filter(
        Islem.tarih >= bugun_bas, Islem.islem_tipi.in_(["satis", "montaj"])
    ).all()

    bugun_ciro = sum(i.genel_toplam for i in bugun_islemler)
    bugun_kar = sum(i.net_kar for i in bugun_islemler)
    bugun_satis_adedi = sum(1 for i in bugun_islemler if i.islem_tipi == "satis")
    bugun_montaj_adedi = sum(1 for i in bugun_islemler if i.islem_tipi == "montaj")

    toplam_alacak = db.session.query(func.sum(Musteri.bakiye)).filter(Musteri.bakiye > 0).scalar() or 0.0
    toplam_borc = db.session.query(func.sum(Tedarikci.bakiye)).filter(Tedarikci.bakiye > 0).scalar() or 0.0

    son_montajlar = (
        Islem.query.filter_by(islem_tipi="montaj")
        .order_by(Islem.tarih.desc())
        .limit(8)
        .all()
    )
    son_satislar = (
        Islem.query.filter(Islem.islem_tipi.in_(["satis", "montaj"]))
        .order_by(Islem.tarih.desc())
        .limit(10)
        .all()
    )

    # Toplam envanter değeri (Patron için)
    tum_urunler = Urun.query.filter_by(aktif=True).all()
    dolar_kuru = g.ayarlar.dolar_kuru if g.ayarlar else 35.0
    envanter_maliyet = sum(
        max(0.0, u.stok_miktari) * u.aktif_maliyet_tl(dolar_kuru) for u in tum_urunler
    )
    envanter_satis_degeri = sum(
        max(0.0, u.stok_miktari) * (u.satis_fiyati or 0.0) for u in tum_urunler
    )

    return render_template(
        "dashboard.html",
        toplam_urun_cesidi=toplam_urun_cesidi,
        kritik_urunler=kritik_urunler,
        kritik_stok_sayisi=kritik_stok_sayisi,
        bugun_ciro=bugun_ciro,
        bugun_kar=bugun_kar,
        bugun_satis_adedi=bugun_satis_adedi,
        bugun_montaj_adedi=bugun_montaj_adedi,
        toplam_alacak=toplam_alacak,
        toplam_borc=toplam_borc,
        son_montajlar=son_montajlar,
        son_satislar=son_satislar,
        envanter_maliyet=envanter_maliyet,
        envanter_satis_degeri=envanter_satis_degeri,
    )


@main_bp.route("/pos")
@login_required
def pos_ekrani():
    musteriler = Musteri.query.order_by(Musteri.ad_soyad.asc()).all()
    gruplar = [
        r[0]
        for r in db.session.query(Urun.grup)
        .filter(Urun.aktif == True, Urun.grup != None, Urun.grup != "")
        .distinct()
        .order_by(Urun.grup.asc())
        .all()
    ]
    secili_musteri_id = request.args.get("musteri_id", "")
    islem_modu = request.args.get("mod", "satis")  # 'satis' veya 'montaj'
    return render_template(
        "pos.html",
        musteriler=musteriler,
        gruplar=gruplar,
        secili_musteri_id=secili_musteri_id,
        islem_modu=islem_modu,
    )


@main_bp.route("/api/urun-ara")
@login_required
def api_urun_ara():
    q = request.args.get("q", "").strip()
    grup = request.args.get("grup", "").strip()
    limit = min(int(request.args.get("limit", 60)), 200)

    sorgu = Urun.query.filter_by(aktif=True)
    if grup and grup != "Tümü":
        sorgu = sorgu.filter(Urun.grup == grup)

    if q:
        sorgu = akilli_urun_sorgusu_uygula(sorgu, q)

    urunler = sorgu.order_by(Urun.ad.asc(), Urun.kod.asc()).limit(limit).all()
    dolar_kuru = g.ayarlar.dolar_kuru if g.ayarlar else 35.0
    maliyet_izni = g.user.is_patron or g.user.yetki_maliyet_gor

    sonuc = []
    for u in urunler:
        item = {
            "id": u.id,
            "barkod": u.barkod or "",
            "kod": u.kod or "",
            "ad": u.ad,
            "marka": u.marka or "",
            "grup": u.grup or "Genel",
            "birim": u.birim or "Adet",
            "satis_fiyati": round(u.satis_fiyati or 0.0, 2),
            "satis_fiyati_2": round(u.satis_fiyati_2 or 0.0, 2),
            "stok_miktari": u.stok_miktari,
            "kritik_stok": u.kritik_stok,
            "kdv_orani": u.kdv_orani,
        }
        if maliyet_izni:
            item["alis_fiyati_tl"] = round(u.alis_fiyati_tl or 0.0, 2)
            item["alis_fiyati_usd"] = round(u.alis_fiyati_usd or 0.0, 2)
            item["aktif_maliyet_tl"] = u.aktif_maliyet_tl(dolar_kuru)
        sonuc.append(item)

    return jsonify(sonuc)


@main_bp.route("/api/barkod/<path:barkod>")
@login_required
def api_barkod_sorgula(barkod):
    barkod = barkod.strip()
    temiz = barkod.lower().replace("-", "").replace(" ", "")
    norm_kod = func.replace(func.replace(func.lower(func.coalesce(Urun.kod, "")), "-", ""), " ", "")
    u = Urun.query.filter(
        Urun.aktif == True,
        or_(
            Urun.barkod == barkod,
            Urun.kod.ilike(barkod),
            norm_kod == temiz,
        ),
    ).first()
    if not u:
        # Tek sonuçlu akıllı model kodu eşleşmesi dene (Ör: TC32GN -> TC-C32GN)
        adaylar = akilli_urun_sorgusu_uygula(Urun.query.filter_by(aktif=True), barkod).limit(2).all()
        if len(adaylar) == 1:
            u = adaylar[0]
    if not u:
        return jsonify({"bulundu": False}), 404

    dolar_kuru = g.ayarlar.dolar_kuru if g.ayarlar else 35.0
    maliyet_izni = g.user.is_patron or g.user.yetki_maliyet_gor
    veri = {
        "bulundu": True,
        "id": u.id,
        "barkod": u.barkod or "",
        "kod": u.kod or "",
        "ad": u.ad,
        "marka": u.marka or "",
        "grup": u.grup or "Genel",
        "birim": u.birim or "Adet",
        "satis_fiyati": round(u.satis_fiyati or 0.0, 2),
        "satis_fiyati_2": round(u.satis_fiyati_2 or 0.0, 2),
        "stok_miktari": u.stok_miktari,
        "kdv_orani": u.kdv_orani,
    }
    if maliyet_izni:
        veri["alis_fiyati_tl"] = round(u.alis_fiyati_tl or 0.0, 2)
        veri["alis_fiyati_usd"] = round(u.alis_fiyati_usd or 0.0, 2)
        veri["aktif_maliyet_tl"] = u.aktif_maliyet_tl(dolar_kuru)
    return jsonify(veri)


@main_bp.route("/api/islem-kaydet", methods=["POST"])
@login_required
def api_islem_kaydet():
    veri = request.get_json(silent=True) or {}
    kalemler = veri.get("kalemler", [])
    if not kalemler:
        return jsonify({"basarili": False, "mesaj": "Sepette hiç ürün yok!"}), 400

    islem_tipi = veri.get("islem_tipi", "satis")  # 'satis' veya 'montaj'
    musteri_id = veri.get("musteri_id")
    yeni_musteri = veri.get("yeni_musteri") or {}

    # Eğer anlık yeni müşteri girildiyse oluştur
    musteri = None
    if musteri_id:
        musteri = db.session.get(Musteri, int(musteri_id))
    elif yeni_musteri.get("ad_soyad", "").strip():
        musteri = Musteri(
            ad_soyad=yeni_musteri.get("ad_soyad", "").strip(),
            telefon=yeni_musteri.get("telefon", "").strip(),
            adres=yeni_musteri.get("adres", "").strip(),
            notlar=yeni_musteri.get("notlar", "").strip(),
        )
        db.session.add(musteri)
        db.session.flush()

    odeme_yontemi = veri.get("odeme_yontemi", "nakit")  # nakit, kart, havale, veresiye, parcali
    if odeme_yontemi == "veresiye" and not musteri:
        return jsonify({
            "basarili": False,
            "mesaj": "Açık hesap (veresiye) veya cari montaj kaydı için lütfen bir Müşteri seçin veya yeni müşteri adı girin!",
        }), 400

    prefix = "MNT" if islem_tipi == "montaj" else "SNL"
    fis_no = yeni_fis_no_uret(prefix)

    dolar_kuru = g.ayarlar.dolar_kuru if g.ayarlar else 35.0
    ara_toplam = 0.0
    toplam_maliyet = 0.0

    montaj_basligi = (veri.get("montaj_basligi") or "").strip()
    montaj_adresi = (veri.get("montaj_adresi") or "").strip()
    if not montaj_adresi and musteri and musteri.adres:
        montaj_adresi = musteri.adres

    yeni_islem = Islem(
        fis_no=fis_no,
        islem_tipi=islem_tipi,
        musteri_id=musteri.id if musteri else None,
        kullanici_id=g.user.id,
        montaj_basligi=montaj_basligi,
        montaj_adresi=montaj_adresi,
        montaj_durumu=veri.get("montaj_durumu", "tamamlandi"),
        odeme_yontemi=odeme_yontemi,
        aciklama=(veri.get("aciklama") or "").strip(),
    )
    db.session.add(yeni_islem)
    db.session.flush()

    for k in kalemler:
        urun_id = k.get("urun_id")
        miktar = float(k.get("miktar") or 1.0)
        if miktar <= 0:
            continue

        urun = db.session.get(Urun, int(urun_id)) if urun_id else None
        if urun:
            if not (g.user.is_patron or g.user.yetki_fiyat_degistir):
                birim_fiyat = float(urun.satis_fiyati or 0.0)
            else:
                birim_fiyat = float(k.get("birim_fiyat", urun.satis_fiyati) or 0.0)
            birim_maliyet = urun.aktif_maliyet_tl(dolar_kuru)
            barkod = urun.barkod or ""
            urun_adi = k.get("urun_adi") or urun.ad
            marka_model = f"{urun.marka or ''} {urun.kod or ''}".strip()
            birim = urun.birim or "Adet"

            # Stoktan düş
            onceki_stok = urun.stok_miktari
            urun.stok_miktari = round(onceki_stok - miktar, 3)
            db.session.add(
                StokHareketi(
                    urun_id=urun.id,
                    kullanici_id=g.user.id,
                    islem_id=yeni_islem.id,
                    hareket_tipi=islem_tipi,
                    miktar_degisimi=-miktar,
                    onceki_stok=onceki_stok,
                    sonraki_stok=urun.stok_miktari,
                    aciklama=f"{fis_no} ({'Montaj: ' + (musteri.ad_soyad if musteri else montaj_basligi) if islem_tipi == 'montaj' else 'POS Satış'})",
                )
            )
        else:
            # Serbest kalem (Ör. Montaj İşçiliği, Format Ücreti, Servis Ücreti)
            birim_fiyat = float(k.get("birim_fiyat") or 0.0)
            birim_maliyet = 0.0
            barkod = ""
            urun_adi = k.get("urun_adi") or "Servis / İşçilik Hizmeti"
            marka_model = "Hizmet"
            birim = k.get("birim") or "Adet"

        kalem_iskonto = float(k.get("iskonto") or 0.0)
        satir_toplam = round((miktar * birim_fiyat) - kalem_iskonto, 2)
        ara_toplam += satir_toplam
        toplam_maliyet += round(miktar * birim_maliyet, 2)

        db.session.add(
            IslemKalemi(
                islem_id=yeni_islem.id,
                urun_id=urun.id if urun else None,
                barkod=barkod,
                urun_adi=urun_adi,
                marka_model=marka_model,
                birim=birim,
                miktar=miktar,
                birim_maliyet_tl=birim_maliyet,
                birim_fiyat=birim_fiyat,
                iskonto=kalem_iskonto,
                toplam_tutar=satir_toplam,
            )
        )

    genel_iskonto = float(veri.get("iskonto_tutari") or 0.0)
    genel_toplam = max(0.0, round(ara_toplam - genel_iskonto, 2))

    yeni_islem.ara_toplam = round(ara_toplam, 2)
    yeni_islem.iskonto_tutari = round(genel_iskonto, 2)
    yeni_islem.genel_toplam = genel_toplam
    yeni_islem.toplam_maliyet = round(toplam_maliyet, 2)

    # Ödeme dağılımı hesapla
    if odeme_yontemi == "nakit":
        yeni_islem.odenen_nakit = genel_toplam
    elif odeme_yontemi == "kart":
        yeni_islem.odenen_kart = genel_toplam
    elif odeme_yontemi == "havale":
        yeni_islem.odenen_havale = genel_toplam
    elif odeme_yontemi == "veresiye":
        yeni_islem.kalan_veresiye = genel_toplam
    elif odeme_yontemi == "parcali":
        o_nakit = float(veri.get("odenen_nakit") or 0.0)
        o_kart = float(veri.get("odenen_kart") or 0.0)
        o_havale = float(veri.get("odenen_havale") or 0.0)
        kalan = max(0.0, round(genel_toplam - (o_nakit + o_kart + o_havale), 2))
        if kalan > 0 and not musteri:
            db.session.rollback()
            return jsonify({
                "basarili": False,
                "mesaj": "Parçalı ödemede kalan bakiye (veresiye) var; lütfen bir Müşteri seçin!",
            }), 400
        yeni_islem.odenen_nakit = o_nakit
        yeni_islem.odenen_kart = o_kart
        yeni_islem.odenen_havale = o_havale
        yeni_islem.kalan_veresiye = kalan

    # Müşteri cari bakiyesini güncelle (kalan_veresiye kadar borç ekle)
    if musteri and yeni_islem.kalan_veresiye > 0:
        musteri.bakiye = round((musteri.bakiye or 0.0) + yeni_islem.kalan_veresiye, 2)

    # Kasaya giren peşin tutarları kaydet
    for yontem, tutar in [
        ("nakit", yeni_islem.odenen_nakit),
        ("kart", yeni_islem.odenen_kart),
        ("havale", yeni_islem.odenen_havale),
    ]:
        if tutar > 0:
            db.session.add(
                KasaHareketi(
                    tip="tahsilat",
                    kategori="Montaj Tahsilatı" if islem_tipi == "montaj" else "POS Satış",
                    tutar=tutar,
                    odeme_yontemi=yontem,
                    musteri_id=musteri.id if musteri else None,
                    kullanici_id=g.user.id,
                    islem_id=yeni_islem.id,
                    aciklama=f"{fis_no} nolu {'montaj' if islem_tipi == 'montaj' else 'satış'} tahsilatı",
                )
            )

    db.session.commit()
    return jsonify({
        "basarili": True,
        "islem_id": yeni_islem.id,
        "fis_no": yeni_islem.fis_no,
        "genel_toplam": yeni_islem.genel_toplam,
        "detay_url": url_for("main.islem_detay", id=yeni_islem.id),
    })


@main_bp.route("/islemler")
@login_required
def islemler_listesi():
    tip = request.args.get("tip", "")  # '', 'montaj', 'satis', 'alis'
    q = request.args.get("q", "").strip()
    personel_id = request.args.get("personel_id", "")
    bas_tarih = request.args.get("bas_tarih", "")
    bit_tarih = request.args.get("bit_tarih", "")

    sorgu = Islem.query
    if tip:
        sorgu = sorgu.filter(Islem.islem_tipi == tip)

    if personel_id:
        sorgu = sorgu.filter(Islem.kullanici_id == int(personel_id))

    if bas_tarih:
        try:
            dt_bas = datetime.strptime(bas_tarih, "%Y-%m-%d")
            sorgu = sorgu.filter(Islem.tarih >= dt_bas)
        except ValueError:
            pass

    if bit_tarih:
        try:
            dt_bit = datetime.strptime(bit_tarih, "%Y-%m-%d") + timedelta(days=1)
            sorgu = sorgu.filter(Islem.tarih < dt_bit)
        except ValueError:
            pass

    if q:
        arama = f"%{q}%"
        sorgu = sorgu.outerjoin(Musteri).filter(
            or_(
                Islem.fis_no.ilike(arama),
                Islem.montaj_basligi.ilike(arama),
                Islem.montaj_adresi.ilike(arama),
                Islem.aciklama.ilike(arama),
                Musteri.ad_soyad.ilike(arama),
                Musteri.telefon.ilike(arama),
            )
        )

    islemler = sorgu.order_by(Islem.tarih.desc()).limit(250).all()
    personeller = Kullanici.query.order_by(Kullanici.ad_soyad.asc()).all()

    return render_template(
        "islemler.html",
        islemler=islemler,
        personeller=personeller,
        secili_tip=tip,
        q=q,
        secili_personel=personel_id,
        bas_tarih=bas_tarih,
        bit_tarih=bit_tarih,
    )


@main_bp.route("/islem/<int:id>")
@login_required
def islem_detay(id):
    islem = db.session.get(Islem, id)
    if not islem:
        flash("İşlem fişi bulunamadı.", "danger")
        return redirect(url_for("main.islemler_listesi"))
    return render_template("islem_detay.html", islem=islem)


@main_bp.route("/islem/<int:id>/sil", methods=["POST"])
@login_required
def islem_sil(id):
    if not (g.user.is_patron or g.user.yetki_urun_sil):
        flash("Fiş iptal/silme yetkiniz bulunmuyor.", "danger")
        return redirect(url_for("main.islem_detay", id=id))

    islem = db.session.get(Islem, id)
    if not islem:
        return redirect(url_for("main.islemler_listesi"))

    # Stokları geri iade et
    for k in islem.kalemler:
        if k.urun:
            if islem.islem_tipi in ("satis", "montaj"):
                k.urun.stok_miktari = round((k.urun.stok_miktari or 0.0) + k.miktar, 3)
            elif islem.islem_tipi == "alis":
                k.urun.stok_miktari = round((k.urun.stok_miktari or 0.0) - k.miktar, 3)

    # Cari bakiyeyi geri al
    if islem.musteri and islem.kalan_veresiye > 0:
        islem.musteri.bakiye = round((islem.musteri.bakiye or 0.0) - islem.kalan_veresiye, 2)
    if islem.tedarikci and islem.islem_tipi == "alis" and islem.kalan_veresiye > 0:
        islem.tedarikci.bakiye = round((islem.tedarikci.bakiye or 0.0) - islem.kalan_veresiye, 2)

    # Bağlı kasa ve stok hareketlerini temizle
    KasaHareketi.query.filter_by(islem_id=islem.id).delete()
    StokHareketi.query.filter_by(islem_id=islem.id).delete()

    fis_no = islem.fis_no
    db.session.delete(islem)
    db.session.commit()
    flash(f"{fis_no} numaralı fiş iptal edildi, stoklar ve cari bakiye geri alındı.", "warning")
    return redirect(url_for("main.islemler_listesi"))


@main_bp.route("/raporlar", methods=["GET", "POST"])
@login_required
def raporlar():
    if not (g.user.is_patron or g.user.yetki_rapor_gor):
        flash("Raporlar ve Kasa ekranına erişim yetkiniz yok.", "danger")
        return redirect(url_for("main.pos_ekrani"))

    if request.method == "POST":
        # Yeni Gelir veya Gider (Masraf/Yakıt/Fatura) kaydı
        tip = request.form.get("tip", "gider")
        kategori = request.form.get("kategori", "Genel Gider").strip()
        try:
            tutar = float(str(request.form.get("tutar", "0")).replace(",", "."))
        except ValueError:
            tutar = 0.0
        odeme_yontemi = request.form.get("odeme_yontemi", "nakit")
        aciklama = request.form.get("aciklama", "").strip()

        if tutar > 0:
            db.session.add(
                KasaHareketi(
                    tip=tip,
                    kategori=kategori,
                    tutar=tutar,
                    odeme_yontemi=odeme_yontemi,
                    kullanici_id=g.user.id,
                    aciklama=aciklama,
                )
            )
            db.session.commit()
            flash(f"Kasa hareketi ({kategori}: {tutar:.2f} TL) kaydedildi.", "success")
        return redirect(url_for("main.raporlar"))

    bas_str = request.args.get("bas_tarih", date.today().replace(day=1).strftime("%Y-%m-%d"))
    bit_str = request.args.get("bit_tarih", date.today().strftime("%Y-%m-%d"))

    try:
        dt_bas = datetime.strptime(bas_str, "%Y-%m-%d")
    except ValueError:
        dt_bas = datetime.combine(date.today().replace(day=1), datetime.min.time())

    try:
        dt_bit = datetime.strptime(bit_str, "%Y-%m-%d") + timedelta(days=1)
    except ValueError:
        dt_bit = datetime.combine(date.today() + timedelta(days=1), datetime.min.time())

    islemler = Islem.query.filter(
        Islem.tarih >= dt_bas,
        Islem.tarih < dt_bit,
        Islem.islem_tipi.in_(["satis", "montaj"]),
    ).all()

    toplam_ciro = sum(i.genel_toplam for i in islemler)
    toplam_maliyet = sum(i.toplam_maliyet for i in islemler)
    brut_kar = round(toplam_ciro - toplam_maliyet, 2)

    satis_ciro = sum(i.genel_toplam for i in islemler if i.islem_tipi == "satis")
    montaj_ciro = sum(i.genel_toplam for i in islemler if i.islem_tipi == "montaj")

    kasa_hareketleri = (
        KasaHareketi.query.filter(KasaHareketi.tarih >= dt_bas, KasaHareketi.tarih < dt_bit)
        .order_by(KasaHareketi.tarih.desc())
        .all()
    )

    toplam_gider = sum(k.tutar for k in kasa_hareketleri if k.tip in ("gider", "tediye"))
    toplam_tahsilat = sum(k.tutar for k in kasa_hareketleri if k.tip in ("tahsilat", "gelir"))
    net_kar = round(brut_kar - sum(k.tutar for k in kasa_hareketleri if k.tip == "gider"), 2)

    # Personel bazlı performans özeti
    personel_ozet = {}
    for i in islemler:
        p_ad = i.kullanici.ad_soyad if i.kullanici else "Belirsiz"
        if p_ad not in personel_ozet:
            personel_ozet[p_ad] = {"satis_adet": 0, "montaj_adet": 0, "ciro": 0.0, "kar": 0.0}
        if i.islem_tipi == "montaj":
            personel_ozet[p_ad]["montaj_adet"] += 1
        else:
            personel_ozet[p_ad]["satis_adet"] += 1
        personel_ozet[p_ad]["ciro"] += i.genel_toplam
        personel_ozet[p_ad]["kar"] += i.net_kar

    # En çok satılan / montajda kullanılan ürünler
    urun_performans = (
        db.session.query(
            IslemKalemi.urun_adi,
            IslemKalemi.birim,
            func.sum(IslemKalemi.miktar).label("toplam_miktar"),
            func.sum(IslemKalemi.toplam_tutar).label("toplam_tutar"),
        )
        .join(Islem, Islem.id == IslemKalemi.islem_id)
        .filter(
            Islem.tarih >= dt_bas,
            Islem.tarih < dt_bit,
            Islem.islem_tipi.in_(["satis", "montaj"]),
        )
        .group_by(IslemKalemi.urun_adi, IslemKalemi.birim)
        .order_by(func.sum(IslemKalemi.toplam_tutar).desc())
        .limit(15)
        .all()
    )

    return render_template(
        "raporlar.html",
        bas_tarih=bas_str,
        bit_tarih=bit_str,
        toplam_ciro=toplam_ciro,
        toplam_maliyet=toplam_maliyet,
        brut_kar=brut_kar,
        net_kar=net_kar,
        satis_ciro=satis_ciro,
        montaj_ciro=montaj_ciro,
        toplam_gider=toplam_gider,
        toplam_tahsilat=toplam_tahsilat,
        kasa_hareketleri=kasa_hareketleri,
        personel_ozet=personel_ozet,
        urun_performans=urun_performans,
    )
