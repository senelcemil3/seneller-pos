from flask import Blueprint, render_template, request, redirect, url_for, flash, g
from sqlalchemy import or_
from app.extensions import db
from app.models import (
    Musteri,
    Tedarikci,
    Islem,
    IslemKalemi,
    Urun,
    StokHareketi,
    KasaHareketi,
)
from app.auth import login_required
from app.routes_main import yeni_fis_no_uret
from app.routes_stok import _temiz_float

cari_bp = Blueprint("cari", __name__)


@cari_bp.route("/musteriler", methods=["GET", "POST"])
@login_required
def musteriler_listesi():
    if request.method == "POST":
        ad_soyad = request.form.get("ad_soyad", "").strip()
        telefon = request.form.get("telefon", "").strip()
        adres = request.form.get("adres", "").strip()
        notlar = request.form.get("notlar", "").strip()
        acilis_bakiye = _temiz_float(request.form.get("acilis_bakiye"), 0.0)

        if not ad_soyad:
            flash("Müşteri Ad Soyad / Ünvan zorunludur!", "danger")
        else:
            m = Musteri(
                ad_soyad=ad_soyad,
                telefon=telefon,
                adres=adres,
                notlar=notlar,
                bakiye=acilis_bakiye,
            )
            db.session.add(m)
            db.session.commit()
            flash(f"'{ad_soyad}' müşteri/montaj carisi oluşturuldu.", "success")
            return redirect(url_for("cari.musteri_detay", id=m.id))

    q = request.args.get("q", "").strip()
    filtre = request.args.get("filtre", "")  # 'borclu'

    sorgu = Musteri.query
    if filtre == "borclu":
        sorgu = sorgu.filter(Musteri.bakiye > 0)
    if q:
        arama = f"%{q}%"
        sorgu = sorgu.filter(
            or_(
                Musteri.ad_soyad.ilike(arama),
                Musteri.telefon.ilike(arama),
                Musteri.adres.ilike(arama),
                Musteri.notlar.ilike(arama),
            )
        )

    musteriler = sorgu.order_by(Musteri.bakiye.desc(), Musteri.ad_soyad.asc()).all()
    return render_template("musteriler.html", musteriler=musteriler, q=q, filtre=filtre)


@cari_bp.route("/musteri/<int:id>", methods=["GET", "POST"])
@login_required
def musteri_detay(id):
    musteri = db.session.get(Musteri, id)
    if not musteri:
        flash("Müşteri bulunamadı.", "danger")
        return redirect(url_for("cari.musteriler_listesi"))

    if request.method == "POST":
        form_islem = request.form.get("form_islem", "")
        if form_islem == "tahsilat":
            tutar = _temiz_float(request.form.get("tutar"), 0.0)
            yontem = request.form.get("odeme_yontemi", "nakit")
            aciklama = request.form.get("aciklama", "").strip() or f"{musteri.ad_soyad} cari tahsilat"
            if tutar > 0:
                musteri.bakiye = round((musteri.bakiye or 0.0) - tutar, 2)
                db.session.add(
                    KasaHareketi(
                        tip="tahsilat",
                        kategori="Cari Tahsilat",
                        tutar=tutar,
                        odeme_yontemi=yontem,
                        musteri_id=musteri.id,
                        kullanici_id=g.user.id,
                        aciklama=aciklama,
                    )
                )
                db.session.commit()
                flash(f"{musteri.ad_soyad} hesabından {tutar:.2f} TL tahsilat alındı.", "success")

        elif form_islem == "duzenle":
            musteri.ad_soyad = request.form.get("ad_soyad", musteri.ad_soyad).strip()
            musteri.telefon = request.form.get("telefon", "").strip()
            musteri.adres = request.form.get("adres", "").strip()
            musteri.notlar = request.form.get("notlar", "").strip()
            db.session.commit()
            flash("Müşteri bilgileri güncellendi.", "success")

        return redirect(url_for("cari.musteri_detay", id=musteri.id))

    islemler = (
        Islem.query.filter_by(musteri_id=musteri.id)
        .order_by(Islem.tarih.desc())
        .all()
    )
    tahsilatlar = (
        KasaHareketi.query.filter_by(musteri_id=musteri.id)
        .order_by(KasaHareketi.tarih.desc())
        .all()
    )

    return render_template(
        "musteri_detay.html",
        musteri=musteri,
        islemler=islemler,
        tahsilatlar=tahsilatlar,
    )


@cari_bp.route("/tedarikciler", methods=["GET", "POST"])
@login_required
def tedarikciler_listesi():
    if request.method == "POST":
        firma_adi = request.form.get("firma_adi", "").strip()
        yetkili = request.form.get("yetkili", "").strip()
        telefon = request.form.get("telefon", "").strip()
        adres = request.form.get("adres", "").strip()
        notlar = request.form.get("notlar", "").strip()
        acilis_bakiye = _temiz_float(request.form.get("acilis_bakiye"), 0.0)

        if not firma_adi:
            flash("Toptancı / Firma adı zorunludur!", "danger")
        else:
            t = Tedarikci(
                firma_adi=firma_adi,
                yetkili=yetkili,
                telefon=telefon,
                adres=adres,
                notlar=notlar,
                bakiye=acilis_bakiye,
            )
            db.session.add(t)
            db.session.commit()
            flash(f"'{firma_adi}' toptancı/firma kartı açıldı.", "success")
            return redirect(url_for("cari.tedarikci_detay", id=t.id))

    tedarikciler = Tedarikci.query.order_by(Tedarikci.bakiye.desc(), Tedarikci.firma_adi.asc()).all()
    return render_template("tedarikciler.html", tedarikciler=tedarikciler)


@cari_bp.route("/tedarikci/<int:id>", methods=["GET", "POST"])
@login_required
def tedarikci_detay(id):
    tedarikci = db.session.get(Tedarikci, id)
    if not tedarikci:
        flash("Toptancı bulunamadı.", "danger")
        return redirect(url_for("cari.tedarikciler_listesi"))

    if request.method == "POST":
        form_islem = request.form.get("form_islem", "")

        if form_islem == "tediye":
            tutar = _temiz_float(request.form.get("tutar"), 0.0)
            yontem = request.form.get("odeme_yontemi", "nakit")
            aciklama = request.form.get("aciklama", "").strip() or f"{tedarikci.firma_adi} ödeme"
            if tutar > 0:
                tedarikci.bakiye = round((tedarikci.bakiye or 0.0) - tutar, 2)
                db.session.add(
                    KasaHareketi(
                        tip="tediye",
                        kategori="Toptancı Ödemesi",
                        tutar=tutar,
                        odeme_yontemi=yontem,
                        tedarikci_id=tedarikci.id,
                        kullanici_id=g.user.id,
                        aciklama=aciklama,
                    )
                )
                db.session.commit()
                flash(f"{tedarikci.firma_adi} firmasına {tutar:.2f} TL ödeme işlendi.", "success")

        elif form_islem == "alis_faturasi":
            urun_id = int(request.form.get("urun_id", 0))
            miktar = _temiz_float(request.form.get("miktar"), 1.0)
            birim_alis_tl = _temiz_float(request.form.get("birim_alis_tl"), 0.0)
            yeni_satis_fiyati = _temiz_float(request.form.get("yeni_satis_fiyati"), 0.0)
            odeme_durumu = request.form.get("odeme_durumu", "veresiye")  # veresiye, nakit, kart, havale

            urun = db.session.get(Urun, urun_id)
            if urun and miktar > 0:
                satir_toplam = round(miktar * birim_alis_tl, 2)
                fis_no = yeni_fis_no_uret("ALS")
                fatura = Islem(
                    fis_no=fis_no,
                    islem_tipi="alis",
                    tedarikci_id=tedarikci.id,
                    kullanici_id=g.user.id,
                    ara_toplam=satir_toplam,
                    genel_toplam=satir_toplam,
                    toplam_maliyet=satir_toplam,
                    odeme_yontemi=odeme_durumu,
                    kalan_veresiye=satir_toplam if odeme_durumu == "veresiye" else 0.0,
                    odenen_nakit=satir_toplam if odeme_durumu == "nakit" else 0.0,
                    odenen_kart=satir_toplam if odeme_durumu == "kart" else 0.0,
                    odenen_havale=satir_toplam if odeme_durumu == "havale" else 0.0,
                    aciklama=request.form.get("aciklama", "").strip(),
                )
                db.session.add(fatura)
                db.session.flush()

                db.session.add(
                    IslemKalemi(
                        islem_id=fatura.id,
                        urun_id=urun.id,
                        barkod=urun.barkod or "",
                        urun_adi=urun.ad,
                        marka_model=f"{urun.marka or ''} {urun.kod or ''}".strip(),
                        birim=urun.birim,
                        miktar=miktar,
                        birim_maliyet_tl=birim_alis_tl,
                        birim_fiyat=birim_alis_tl,
                        toplam_tutar=satir_toplam,
                    )
                )

                # Stoğu artır ve alış fiyatını güncelle
                onceki = urun.stok_miktari
                urun.stok_miktari = round(onceki + miktar, 3)
                if birim_alis_tl > 0:
                    urun.alis_fiyati_tl = birim_alis_tl
                if yeni_satis_fiyati > 0:
                    urun.satis_fiyati = yeni_satis_fiyati

                db.session.add(
                    StokHareketi(
                        urun_id=urun.id,
                        kullanici_id=g.user.id,
                        islem_id=fatura.id,
                        hareket_tipi="alis",
                        miktar_degisimi=miktar,
                        onceki_stok=onceki,
                        sonraki_stok=urun.stok_miktari,
                        aciklama=f"{tedarikci.firma_adi} Alış Faturası ({fis_no})",
                    )
                )

                if odeme_durumu == "veresiye":
                    tedarikci.bakiye = round((tedarikci.bakiye or 0.0) + satir_toplam, 2)
                else:
                    db.session.add(
                        KasaHareketi(
                            tip="tediye",
                            kategori="Mal Alımı (Peşin)",
                            tutar=satir_toplam,
                            odeme_yontemi=odeme_durumu,
                            tedarikci_id=tedarikci.id,
                            kullanici_id=g.user.id,
                            islem_id=fatura.id,
                            aciklama=f"{fis_no} peşin mal alımı",
                        )
                    )

                db.session.commit()
                flash(f"Alış faturası işlendi! '{urun.ad}' stoğuna +{miktar} eklendi.", "success")

        return redirect(url_for("cari.tedarikci_detay", id=tedarikci.id))

    islemler = (
        Islem.query.filter_by(tedarikci_id=tedarikci.id)
        .order_by(Islem.tarih.desc())
        .all()
    )
    odemeler = (
        KasaHareketi.query.filter_by(tedarikci_id=tedarikci.id)
        .order_by(KasaHareketi.tarih.desc())
        .all()
    )
    urunler = Urun.query.filter_by(aktif=True).order_by(Urun.ad.asc()).all()

    return render_template(
        "tedarikci_detay.html",
        tedarikci=tedarikci,
        islemler=islemler,
        odemeler=odemeler,
        urunler=urunler,
    )
