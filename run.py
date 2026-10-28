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
                    BAGLANTI_DURUMU["dis_url"] = aday_url
                    try:
                        import json, requests
                        bulut_dosya = os.path.join(os.path.dirname(__file__), "bulut_ayar.json")
                        bulut_aktif_mi = False
                        if os.path.exists(bulut_dosya):
                            with open(bulut_dosya, "r", encoding="utf-8") as bf:
                                b_data = json.load(bf)
                                if b_data.get("aktif_mod") == "bulut" and b_data.get("bulut_url"):
                                    bulut_aktif_mi = True
                                    BAGLANTI_DURUMU["dis_url"] = b_data.get("bulut_url")
                        if not bulut_aktif_mi:
                            requests.put("https://ntfy.sh/seneller_pos_kapi_88421", data=aday_url.encode("utf-8"), timeout=5)
                    except Exception:
                        pass

                if ("Registered tunnel connection" in line or "Connection" in line) and aday_url and not baglanti_hazir:
                    baglanti_hazir = True
                    try:
                        import json, requests
                        bulut_dosya = os.path.join(os.path.dirname(__file__), "bulut_ayar.json")
                        bulut_aktif_mi = False
                        if os.path.exists(bulut_dosya):
                            with open(bulut_dosya, "r", encoding="utf-8") as bf:
                                b_data = json.load(bf)
                                if b_data.get("aktif_mod") == "bulut" and b_data.get("bulut_url"):
                                    bulut_aktif_mi = True
                                    BAGLANTI_DURUMU["dis_url"] = b_data.get("bulut_url")
                        if not bulut_aktif_mi:
                            BAGLANTI_DURUMU["dis_url"] = aday_url
                            requests.put("https://ntfy.sh/seneller_pos_kapi_88421", data=aday_url.encode("utf-8"), timeout=5)
                    except Exception:
                        pass
                    print("\n" + "=" * 70, flush=True)
                    print("  [SABİT TELEFON ADRESİ EŞİTLENDİ - HİÇ DEĞİŞMEYEN LİNK AKTİF]", flush=True)
                    print("  -> Patron Sabit Link  : https://files.catbox.moe/eaalrw.html?hesap=admin", flush=True)
                    print("  -> Personel Sabit Link: https://files.catbox.moe/eaalrw.html?hesap=eleman", flush=True)
                    print(f"  -> Aktif Tünel        : {aday_url}", flush=True)
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
