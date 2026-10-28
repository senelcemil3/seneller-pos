from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db


class Ayarlar(db.Model):
    __tablename__ = "ayarlar"

    id = db.Column(db.Integer, primary_key=True)
    sirket_adi = db.Column(db.String(150), nullable=False, default="Şeneller Spot Group")
    alt_baslik = db.Column(
        db.String(250),
        nullable=True,
        default="Kamera Güvenlik • Alarm Sistemleri • Anten Uydu • Bilgisayar Toplama & Format • Elektrik Elektronik",
    )
    telefon = db.Column(db.String(50), nullable=True, default="")
    adres = db.Column(db.String(250), nullable=True, default="")
    dolar_kuru = db.Column(db.Float, nullable=False, default=35.0)
    varsayilan_kdv = db.Column(db.Float, nullable=False, default=20.0)
    fis_alt_notu = db.Column(
        db.String(250),
        nullable=True,
        default="Bizi tercih ettiğiniz için teşekkür ederiz. - Şeneller Spot Group",
    )


class Kullanici(db.Model):
    __tablename__ = "kullanicilar"

    id = db.Column(db.Integer, primary_key=True)
    ad_soyad = db.Column(db.String(100), nullable=False)
    kullanici_adi = db.Column(db.String(50), unique=True, nullable=False)
    sifre_hash = db.Column(db.String(255), nullable=False)
    rol = db.Column(db.String(20), nullable=False, default="personel")  # 'patron' veya 'personel'
    aktif = db.Column(db.Boolean, nullable=False, default=True)

    # BenimPOS tarzı detaylı personel yetki bayrakları
    yetki_maliyet_gor = db.Column(db.Boolean, nullable=False, default=False)
    yetki_rapor_gor = db.Column(db.Boolean, nullable=False, default=False)
    yetki_stok_duzenle = db.Column(db.Boolean, nullable=False, default=True)
    yetki_fiyat_degistir = db.Column(db.Boolean, nullable=False, default=True)
    yetki_urun_sil = db.Column(db.Boolean, nullable=False, default=False)

    olusturma_tarihi = db.Column(db.DateTime, nullable=False, default=datetime.now)

    def set_password(self, sifre):
        self.sifre_hash = generate_password_hash(sifre)

    def check_password(self, sifre):
        return check_password_hash(self.sifre_hash, sifre)

    @property
    def is_patron(self):
        return self.rol == "patron"


class Urun(db.Model):
    __tablename__ = "urunler"

    id = db.Column(db.Integer, primary_key=True)
    barkod = db.Column(db.String(64), index=True, nullable=True)
    kod = db.Column(db.String(64), index=True, nullable=True)  # Model / Stok Kodu (ör. PL-1866, M-171)
    ad = db.Column(db.String(250), nullable=False)  # Ürün Adı / Açıklaması
    marka = db.Column(db.String(100), nullable=True, default="")
    grup = db.Column(db.String(100), index=True, nullable=True, default="Genel")
    birim = db.Column(db.String(20), nullable=False, default="Adet")  # Adet, Metre, Paket, Set, Servis

    alis_fiyati_tl = db.Column(db.Float, nullable=False, default=0.0)
    alis_fiyati_usd = db.Column(db.Float, nullable=False, default=0.0)
    satis_fiyati = db.Column(db.Float, nullable=False, default=0.0)
    satis_fiyati_2 = db.Column(db.Float, nullable=False, default=0.0)  # Montaj / Esnaf Özel Fiyatı
    kdv_orani = db.Column(db.Float, nullable=False, default=20.0)

    stok_miktari = db.Column(db.Float, nullable=False, default=0.0)
    kritik_stok = db.Column(db.Float, nullable=False, default=3.0)
    hizli_satis_butonu = db.Column(db.Boolean, nullable=False, default=False)
    aktif = db.Column(db.Boolean, nullable=False, default=True)
    olusturma_tarihi = db.Column(db.DateTime, nullable=False, default=datetime.now)

    def aktif_maliyet_tl(self, dolar_kuru=35.0):
        if self.alis_fiyati_tl and self.alis_fiyati_tl > 0:
            return round(self.alis_fiyati_tl, 2)
        if self.alis_fiyati_usd and self.alis_fiyati_usd > 0:
            return round(self.alis_fiyati_usd * dolar_kuru, 2)
        return 0.0


class Musteri(db.Model):
    __tablename__ = "musteriler"

    id = db.Column(db.Integer, primary_key=True)
    ad_soyad = db.Column(db.String(150), nullable=False)
    telefon = db.Column(db.String(30), nullable=True, default="")
    adres = db.Column(db.String(300), nullable=True, default="")  # Montaj / İletişim Adresi
    vergi_no = db.Column(db.String(50), nullable=True, default="")
    notlar = db.Column(db.Text, nullable=True, default="")
    bakiye = db.Column(db.Float, nullable=False, default=0.0)  # + ise müşterinin bize borcu (Açık Hesap)
    olusturma_tarihi = db.Column(db.DateTime, nullable=False, default=datetime.now)

    islemler = db.relationship("Islem", backref="musteri", lazy=True)
    kasa_hareketleri = db.relationship("KasaHareketi", backref="musteri", lazy=True)


class Tedarikci(db.Model):
    __tablename__ = "tedarikciler"

    id = db.Column(db.Integer, primary_key=True)
    firma_adi = db.Column(db.String(150), nullable=False)
    yetkili = db.Column(db.String(100), nullable=True, default="")
    telefon = db.Column(db.String(30), nullable=True, default="")
    adres = db.Column(db.String(300), nullable=True, default="")
    notlar = db.Column(db.Text, nullable=True, default="")
    bakiye = db.Column(db.Float, nullable=False, default=0.0)  # + ise bizim toptancıya borcumuz
    olusturma_tarihi = db.Column(db.DateTime, nullable=False, default=datetime.now)

    islemler = db.relationship("Islem", backref="tedarikci", lazy=True)
    kasa_hareketleri = db.relationship("KasaHareketi", backref="tedarikci", lazy=True)


class Islem(db.Model):
    """
    Hem Tezgâh Satışı (POS), hem Saha Montaj Kaydı, hem de Toptancı Alış Faturasını
    tek ve güçlü bir BenimPOS/Aronium fiş mimarisinde tutar.
    """
    __tablename__ = "islemler"

    id = db.Column(db.Integer, primary_key=True)
    fis_no = db.Column(db.String(40), unique=True, nullable=False, index=True)
    # islem_tipi: 'satis' (Tezgah POS), 'montaj' (Saha Montaj/Servis), 'alis' (Alış Faturası), 'iade'
    islem_tipi = db.Column(db.String(20), nullable=False, default="satis", index=True)

    musteri_id = db.Column(db.Integer, db.ForeignKey("musteriler.id"), nullable=True)
    tedarikci_id = db.Column(db.Integer, db.ForeignKey("tedarikciler.id"), nullable=True)
    kullanici_id = db.Column(db.Integer, db.ForeignKey("kullanicilar.id"), nullable=True)

    # Montaj / Saha İşlemlerine Özel Alanlar
    montaj_basligi = db.Column(db.String(200), nullable=True, default="")  # Ör: Kamera Kurulumu, Uydu, PC Toplama
    montaj_adresi = db.Column(db.String(300), nullable=True, default="")  # Nereye kurulduğu
    montaj_durumu = db.Column(db.String(30), nullable=True, default="tamamlandi")  # tamamlandi / devam_ediyor / teklif

    ara_toplam = db.Column(db.Float, nullable=False, default=0.0)
    iskonto_tutari = db.Column(db.Float, nullable=False, default=0.0)
    genel_toplam = db.Column(db.Float, nullable=False, default=0.0)
    toplam_maliyet = db.Column(db.Float, nullable=False, default=0.0)

    # Ödeme dağılımı (Nakit, Kart, Havale, Açık Hesap/Veresiye ve Parçalı Ödeme desteği)
    odeme_yontemi = db.Column(db.String(30), nullable=False, default="nakit")  # nakit, kart, havale, veresiye, parcali
    odenen_nakit = db.Column(db.Float, nullable=False, default=0.0)
    odenen_kart = db.Column(db.Float, nullable=False, default=0.0)
    odenen_havale = db.Column(db.Float, nullable=False, default=0.0)
    kalan_veresiye = db.Column(db.Float, nullable=False, default=0.0)

    aciklama = db.Column(db.Text, nullable=True, default="")
    tarih = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)

    kullanici = db.relationship("Kullanici", backref="islemler", lazy=True)
    kalemler = db.relationship(
        "IslemKalemi", backref="islem", lazy=True, cascade="all, delete-orphan"
    )

    @property
    def net_kar(self):
        if self.islem_tipi in ("satis", "montaj"):
            return round(self.genel_toplam - self.toplam_maliyet, 2)
        return 0.0


class IslemKalemi(db.Model):
    __tablename__ = "islem_kalemleri"

    id = db.Column(db.Integer, primary_key=True)
    islem_id = db.Column(db.Integer, db.ForeignKey("islemler.id"), nullable=False)
    urun_id = db.Column(db.Integer, db.ForeignKey("urunler.id"), nullable=True)

    barkod = db.Column(db.String(64), nullable=True, default="")
    urun_adi = db.Column(db.String(250), nullable=False)
    marka_model = db.Column(db.String(150), nullable=True, default="")
    birim = db.Column(db.String(20), nullable=False, default="Adet")

    miktar = db.Column(db.Float, nullable=False, default=1.0)
    birim_maliyet_tl = db.Column(db.Float, nullable=False, default=0.0)
    birim_fiyat = db.Column(db.Float, nullable=False, default=0.0)
    iskonto = db.Column(db.Float, nullable=False, default=0.0)
    kdv_orani = db.Column(db.Float, nullable=False, default=20.0)
    toplam_tutar = db.Column(db.Float, nullable=False, default=0.0)

    urun = db.relationship("Urun", lazy=True)


class StokHareketi(db.Model):
    __tablename__ = "stok_hareketleri"

    id = db.Column(db.Integer, primary_key=True)
    urun_id = db.Column(db.Integer, db.ForeignKey("urunler.id"), nullable=False)
    kullanici_id = db.Column(db.Integer, db.ForeignKey("kullanicilar.id"), nullable=True)
    islem_id = db.Column(db.Integer, db.ForeignKey("islemler.id"), nullable=True)

    hareket_tipi = db.Column(db.String(30), nullable=False)  # satis, montaj, alis, sayim, manuel_giris, manuel_cikis
    miktar_degisimi = db.Column(db.Float, nullable=False, default=0.0)
    onceki_stok = db.Column(db.Float, nullable=False, default=0.0)
    sonraki_stok = db.Column(db.Float, nullable=False, default=0.0)
    aciklama = db.Column(db.String(255), nullable=True, default="")
    tarih = db.Column(db.DateTime, nullable=False, default=datetime.now)

    urun = db.relationship("Urun", backref="stok_hareketleri", lazy=True)
    kullanici = db.relationship("Kullanici", lazy=True)


class KasaHareketi(db.Model):
    __tablename__ = "kasa_hareketleri"

    id = db.Column(db.Integer, primary_key=True)
    # tip: 'tahsilat' (müşteriden alınan), 'tediye' (toptancıya ödenen), 'gelir' (ek gelir), 'gider' (masraf/yakıt/kira)
    tip = db.Column(db.String(20), nullable=False)
    kategori = db.Column(db.String(100), nullable=False, default="Genel")
    tutar = db.Column(db.Float, nullable=False, default=0.0)
    odeme_yontemi = db.Column(db.String(30), nullable=False, default="nakit")  # nakit, kart, havale

    musteri_id = db.Column(db.Integer, db.ForeignKey("musteriler.id"), nullable=True)
    tedarikci_id = db.Column(db.Integer, db.ForeignKey("tedarikciler.id"), nullable=True)
    kullanici_id = db.Column(db.Integer, db.ForeignKey("kullanicilar.id"), nullable=True)
    islem_id = db.Column(db.Integer, db.ForeignKey("islemler.id"), nullable=True)

    aciklama = db.Column(db.String(255), nullable=True, default="")
    tarih = db.Column(db.DateTime, nullable=False, default=datetime.now)

    kullanici = db.relationship("Kullanici", lazy=True)
