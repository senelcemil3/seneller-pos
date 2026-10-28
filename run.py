import os
import re
import time
import socket
import atexit
import threading
import subprocess
from pathlib import Path
from waitress import serve
from app import create_app, BAGLANTI_DURUMU, otomatik_yedek_al


def eski_port_islemlerini_temizle(port=5000):
    """5000 portunu kilitleyen eski askıda kalmış python/cloudflared işlemlerini temizler."""
    kendi_pid = os.getpid()
    try:
        out = subprocess.check_output(f'netstat -aon | findstr ":{port}"', shell=True, text=True)
        for line in out.splitlines():
            parcalar = line.split()
            if len(parcalar) >= 5:
                pid = int(parcalar[-1])
                if pid != kendi_pid and pid > 0:
                    subprocess.run(f"taskkill /F /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


eski_port_islemlerini_temizle(5000)
app = create_app()


def _kapi_adresini_yayinla(hedef_url):
    """Aktif dış ağ adresini hem ntfy kanalına hem de GitHub Pages (docs/aktif_adres.json) üzerine yazar."""
    import json, base64, urllib.request
    base_dir = os.path.dirname(__file__)
    bulut_dosya = os.path.join(base_dir, "bulut_ayar.json")
    if os.path.exists(bulut_dosya):
        try:
            with open(bulut_dosya, "r", encoding="utf-8") as bf:
                b_data = json.load(bf)
                if b_data.get("aktif_mod") == "bulut" and b_data.get("bulut_url"):
                    hedef_url = b_data.get("bulut_url")
        except Exception:
            pass

    BAGLANTI_DURUMU["dis_url"] = hedef_url

    # 1. Yerel docs/aktif_adres.json dosyasını güncelle
    docs_dir = os.path.join(base_dir, "docs")
    os.makedirs(docs_dir, exist_ok=True)
    aktif_json_yol = os.path.join(docs_dir, "aktif_adres.json")
    icerik_str = json.dumps({
        "dis_url": hedef_url,
        "yerel_url": BAGLANTI_DURUMU.get("yerel_url", "http://192.168.1.104:5000"),
        "guncelleme": time.strftime("%Y-%m-%d %H:%M:%S")
    }, ensure_ascii=False, indent=2)
    try:
        with open(aktif_json_yol, "w", encoding="utf-8") as af:
            af.write(icerik_str)
    except Exception:
        pass

    # 2. ntfy.sh kanalına gönder
    try:
        import requests
        requests.put("https://ntfy.sh/seneller_pos_kapi_88421", data=hedef_url.encode("utf-8"), timeout=5)
    except Exception:
        pass

    # 3. GitHub Pages (senelcemil3.github.io/seneller-pos/aktif_adres.json) dosyasını API ile anında güncelle
    try:
        cred = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            text=True,
            capture_output=True,
            timeout=4,
        )
        lines = dict(line.split("=", 1) for line in cred.stdout.splitlines() if "=" in line)
        user = lines.get("username", "")
        token = lines.get("password", "")
        if user and token:
            api_url = f"https://api.github.com/repos/{user}/seneller-pos/contents/docs/aktif_adres.json"
            headers = {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "SenellerPOS",
            }
            sha = None
            try:
                req_get = urllib.request.Request(api_url, headers=headers)
                with urllib.request.urlopen(req_get, timeout=5) as r_get:
                    sha = json.loads(r_get.read().decode("utf-8")).get("sha")
            except Exception:
                pass
            payload = {
                "message": "Otomatik canli sunucu adresi guncellemesi",
                "content": base64.b64encode(icerik_str.encode("utf-8")).decode("ascii"),
            }
            if sha:
                payload["sha"] = sha
            req_put = urllib.request.Request(
                api_url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="PUT",
            )
            urllib.request.urlopen(req_put, timeout=6)
    except Exception:
        pass


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def dis_ag_tuneli_baslat(port=5000):
    """
    Cloudflare Tunnel'i '--protocol http2' ile başlatır ve stderr tamponunu
    sürekli okuyarak tıkanmayı ve Error 1033 hatasını tamamen engeller.
    """
    url_pattern = re.compile(r"(https://[a-zA-Z0-9-]+\.trycloudflare\.com)")

    try:
        from pycloudflared.util import get_info, download
        info = get_info()
        if not Path(info.executable).exists():
            download(info)
        exe_path = info.executable
    except Exception as e:
        print(f"  [Bilgi] Tunnel aracı hazırlanamadı: {e}")
        return

    while True:
        proc = None
        try:
            args = [
                exe_path,
                "tunnel",
                "--url",
                f"http://127.0.0.1:{port}",
                "--protocol",
                "http2",
                "--no-autoupdate",
            ]
            proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
            )
            atexit.register(proc.terminate)

            aday_url = None
            baglanti_hazir = False

            for line in proc.stderr:
                m = url_pattern.search(line)
                if m:
                    aday_url = m.group(1)
                    _kapi_adresini_yayinla(aday_url)

                if ("Registered tunnel connection" in line or "Connection" in line) and aday_url and not baglanti_hazir:
                    baglanti_hazir = True
                    _kapi_adresini_yayinla(aday_url)
                    print("\n" + "=" * 70, flush=True)
                    print("  [KURUMSAL SABİT TELEFON ADRESİ EŞİTLENDİ - HİÇ DEĞİŞMEYEN LİNK AKTİF]", flush=True)
                    print("  -> Patron Sabit Link  : https://senelcemil3.github.io/seneller-pos/?hesap=admin", flush=True)
                    print("  -> Personel Sabit Link: https://senelcemil3.github.io/seneller-pos/?hesap=eleman", flush=True)
                    print(f"  -> Aktif Tünel        : {BAGLANTI_DURUMU.get('dis_url')}", flush=True)
                    print("=" * 70 + "\n", flush=True)

            proc.wait()
        except Exception as e:
            print(f"  [Tünel Yeniden Başlatılıyor]: {e}", flush=True)
        finally:
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
        time.sleep(3)


if __name__ == "__main__":
    local_ip = get_local_ip()
    BAGLANTI_DURUMU["yerel_url"] = f"http://{local_ip}:5000"

    yedek_yolu = otomatik_yedek_al(app, etiket="acilis")

    print("=" * 70, flush=True)
    print("  ŞENELLER POS - BARKODLU SATIŞ, STOK VE MONTAJ TAKİP SİSTEMİ", flush=True)
    print("=" * 70, flush=True)
    print(f"  Bilgisayardan Giriş       : http://127.0.0.1:5000", flush=True)
    print(f"  Dükkân Wi-Fi Telefondan   : http://{local_ip}:5000", flush=True)
    if yedek_yolu:
        print("  Otomatik Veritabanı Yedeği: Alındı (WAL Zırhlı Mod Aktif)", flush=True)
    print("  4.5G / Dış Ağ Tüneli      : HTTP/2 protokolü ile bağlanıyor...", flush=True)
    print("=" * 70, flush=True)

    threading.Thread(target=dis_ag_tuneli_baslat, args=(5000,), daemon=True).start()
    serve(app, host="0.0.0.0", port=5000, threads=8)
