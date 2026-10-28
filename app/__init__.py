import os
import shutil
from datetime import datetime
from flask import Flask, Response, jsonify, g
from sqlalchemy import event
from sqlalchemy.engine import Engine
from config import Config, BASE_DIR
from app.extensions import db

# Canlı bağlantı adreslerini (Sabit Kapı, Yerel Wi-Fi ve 4.5G Cloudflare HTTPS Tüneli) tutar
BAGLANTI_DURUMU = {
    "sabit_url": "https://files.catbox.moe/eaalrw.html",
    "yerel_url": "http://127.0.0.1:5000",
    "dis_url": None,
}


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """
    SQLite veritabanını çoklu kullanıcı (Patron + Saha Elemanları) için zırhlı hale getirir:
    - WAL (Write-Ahead Logging): Okuma ve yazma işlemleri birbirini kilitlemez.
    - busy_timeout=15000: Aynı saniyede iki kişi kayıt girerse hata vermek yerine sıraya sokar.
    - synchronous=NORMAL & foreign_keys=ON: Veri bütünlüğünü korur.
    """
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=15000;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()
    except Exception:
        pass


def otomatik_yedek_al(app, etiket="otomatik"):
    """Veritabanının tarihli bir kopyasını yedekler/ klasörüne alır (en son 25 yedeği tutar)."""
    try:
        db_yolu = os.path.join(app.instance_path, "seneller_pos.db")
        if not os.path.exists(db_yolu) or os.path.getsize(db_yolu) == 0:
            return None
        yedek_klasoru = os.path.join(BASE_DIR, "yedekler")
        os.makedirs(yedek_klasoru, exist_ok=True)
        zaman = datetime.now().strftime("%Y%m%d_%H%M%S")
        hedef = os.path.join(yedek_klasoru, f"seneller_pos_{etiket}_{zaman}.db")
        shutil.copy2(db_yolu, hedef)

        # Eski yedekleri temizle (son 25 tanesini koru)
        dosyalar = sorted(
            [os.path.join(yedek_klasoru, f) for f in os.listdir(yedek_klasoru) if f.endswith(".db")],
            key=os.path.getmtime,
            reverse=True,
        )
        for eski in dosyalar[25:]:
            try:
                os.remove(eski)
            except OSError:
                pass
        return hedef
    except Exception:
        return None


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, "yedekler"), exist_ok=True)
    db.init_app(app)

    @app.template_filter("para")
    def para_format(deger):
        try:
            val = float(deger or 0)
            return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            return "0,00"

    @app.template_filter("miktar_fmt")
    def miktar_format(deger):
        try:
            val = float(deger or 0)
            if val.is_integer():
                return str(int(val))
            return f"{val:.2f}".rstrip("0").rstrip(".")
        except Exception:
            return "0"

    @app.context_processor
    def inject_baglanti():
        return {"baglanti_durumu": BAGLANTI_DURUMU}

    # PWA (Telefona Uygulama Olarak Kurulum) rotaları
    @app.route("/manifest.json")
    def pwa_manifest():
        return jsonify({
            "name": "Şeneller POS - Satış, Stok & Montaj",
            "short_name": "Şeneller POS",
            "description": "Şeneller Spot Group Barkodlu Satış, Stok ve Saha Montaj Takip Uygulaması",
            "start_url": "/pos",
            "display": "standalone",
            "background_color": "#0f172a",
            "theme_color": "#0f172a",
            "orientation": "any",
            "icons": [
                {
                    "src": "/app-icon.svg",
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "any maskable"
                }
            ]
        })

    @app.route("/app-icon.svg")
    def pwa_icon():
        svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
        <rect width="512" height="512" rx="108" fill="#0f172a"/>
        <rect x="36" y="36" width="440" height="440" rx="84" fill="none" stroke="#f59e0b" stroke-width="16"/>
        <path d="M292 96L152 284h108l-40 132 140-188H252z" fill="#f59e0b"/>
        <text x="256" y="458" font-family="Arial, sans-serif" font-size="54" font-weight="900" fill="#ffffff" text-anchor="middle">ŞENELLER</text>
        </svg>"""
        return Response(svg, mimetype="image/svg+xml")

    @app.route("/sw.js")
    def service_worker():
        js = """
        self.addEventListener('install', (e) => { self.skipWaiting(); });
        self.addEventListener('activate', (e) => { e.waitUntil(self.clients.claim()); });
        self.addEventListener('fetch', (e) => {
            e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
        });
        """
        return Response(js, mimetype="application/javascript")

    with app.app_context():
        import json
        from app.models import Kullanici, Ayarlar, Urun  # noqa: F401
        db.create_all()

        if not Ayarlar.query.first():
            db.session.add(Ayarlar(
                sirket_adi="Şeneller Spot Group",
                alt_baslik="Kamera Güvenlik • Alarm Sistemleri • Anten Uydu • Bilgisayar Toplama & Format • Elektrik Elektronik",
                dolar_kuru=35.0,
                varsayilan_kdv=20.0,
            ))
            db.session.commit()

        if not Kullanici.query.first():
            patron = Kullanici(
                ad_soyad="Şeneller Patron (Yönetici)",
                kullanici_adi="admin",
                rol="patron",
                yetki_maliyet_gor=True,
                yetki_rapor_gor=True,
                yetki_stok_duzenle=True,
                yetki_fiyat_degistir=True,
                yetki_urun_sil=True,
            )
            patron.set_password("1234")

            eleman = Kullanici(
                ad_soyad="Saha & Montaj Personeli",
                kullanici_adi="eleman",
                rol="personel",
                yetki_maliyet_gor=False,
                yetki_rapor_gor=False,
                yetki_stok_duzenle=True,
                yetki_fiyat_degistir=True,
                yetki_urun_sil=False,
            )
            eleman.set_password("1234")

            db.session.add_all([patron, eleman])
            db.session.commit()

        # Bulut sunucuda (Render / PythonAnywhere) ilk açılışta 342 ürünü otomatik yükle
        if Urun.query.count() == 0:
            seed_yolu = os.path.join(os.path.dirname(__file__), "seed_stok.json")
            if os.path.exists(seed_yolu):
                try:
                    with open(seed_yolu, "r", encoding="utf-8") as sf:
                        seed_verisi = json.load(sf)
                    yeni_urunler = []
                    for item in seed_verisi:
                        yeni_urunler.append(Urun(
                            barkod=item.get("barkod"),
                            kod=item.get("kod"),
                            ad=item.get("ad") or "İsimsiz Ürün",
                            marka=item.get("marka") or "",
                            grup=item.get("grup") or "Genel",
                            birim=item.get("birim") or "Adet",
                            alis_fiyati_tl=float(item.get("alis_fiyati_tl") or 0.0),
                            alis_fiyati_usd=float(item.get("alis_fiyati_usd") or 0.0),
                            satis_fiyati=float(item.get("satis_fiyati") or 0.0),
                            satis_fiyati_2=float(item.get("satis_fiyati_2") or 0.0),
                            kdv_orani=float(item.get("kdv_orani") or 20.0),
                            stok_miktari=float(item.get("stok_miktari") or 0.0),
                            kritik_stok=float(item.get("kritik_stok") or 3.0),
                            hizli_satis_butonu=bool(item.get("hizli_satis_butonu", False)),
                            aktif=True,
                        ))
                    db.session.add_all(yeni_urunler)
                    db.session.commit()
                except Exception:
                    db.session.rollback()

        # Eğer Render veya PythonAnywhere bulut ortamında çalışıyorsa Sabit Kapıyı otomatik buluta bağla
        bulut_url = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("BULUT_SUNUCU_URL")
        if not bulut_url and os.environ.get("PYTHONANYWHERE_DOMAIN"):
            kullanici_pa = os.environ.get("USER") or os.environ.get("USERNAME")
            if kullanici_pa:
                bulut_url = f"https://{kullanici_pa}.{os.environ.get('PYTHONANYWHERE_DOMAIN')}"
        if bulut_url:
            bulut_url = bulut_url.rstrip("/")
            BAGLANTI_DURUMU["dis_url"] = bulut_url
            BAGLANTI_DURUMU["bulut_aktif"] = True
            try:
                import urllib.request
                req = urllib.request.Request(
                    "https://ntfy.sh/seneller_pos_kapi_88421",
                    data=bulut_url.encode("utf-8"),
                    method="PUT",
                )
                urllib.request.urlopen(req, timeout=4)
            except Exception:
                pass

    from app.auth import auth_bp
    from app.routes_main import main_bp
    from app.routes_stok import stok_bp
    from app.routes_cari import cari_bp
    from app.routes_ai import ai_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(stok_bp)
    app.register_blueprint(cari_bp)
    app.register_blueprint(ai_bp)

    return app
