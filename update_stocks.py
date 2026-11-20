import urllib.request
import ssl
import json
import math
from datetime import datetime, timedelta, timezone

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

tw_tz = timezone(timedelta(hours=8))
now_tw = datetime.now(tw_tz)

def fetch_json(url):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
        return json.loads(resp.read().decode('utf-8'))

def main():
    # 台股主流與熱門核心觀察池（涵蓋半導體、AI、重電、航運、金融、電子零組件）
    watch_list = [
        ("2330","台積電"),("2317","鴻海"),("2454","聯發科"),("2382","廣達"),("3231","緯創"),
        ("2308","台達電"),("2303","聯電"),("3711","日月光投控"),("2357","華碩"),("2376","技嘉"),
        ("3017","奇鋐"),("3324","雙鴻"),("2368","金像電"),("3037","欣興"),("2383","台光電"),
        ("2603","長榮"),("2609","陽明"),("2615","萬海"),("2618","長榮航"),("2610","華航"),
        ("1513","中興電"),("1519","華城"),("1503","士電"),("1504","東元"),("1609","大亞"),
        ("2881","富邦金"),("2882","國泰金"),("2891","中信金"),("2886","兆豐金"),("2884","玉山金"),
        ("2327","國巨"),("2492","華新科"),("3008","大立光"),("3443","創意"),("3661","世芯-KY"),
        ("6669","緯穎"),("2356","英業達"),("2324","仁寶"),("4938","和碩"),("2301","光寶科"),
        ("2345","智邦"),("3533","嘉澤"),("2049","上銀"),("1590","亞德客-KY"),("2395","研華"),
        ("2408","南亞科"),("2344","華邦電"),("3034","聯詠"),("2379","瑞昱"),("5347","世界"),
        ("2466","冠西電"),("8112","至上"),("2409","友達"),("3481","群創"),("6770","力積電"),
        ("3035","智原"),("3529","力旺"),("5269","祥碩"),("6415","矽力*-KY"),("2360","致茂")
    ]

    zhu_lin_picks = []
    sarah_picks = []
    market_date = now_tw.strftime("%Y-%m-%d")
    scanned_count = 0

    for code, name in watch_list:
        # 直接向 Yahoo Finance 抓取真實 3 個月日 K 線（全球 CDN 節點，永不被封鎖）
        yf_url = f"https://yahoo.com{code}.TW?range=3mo&interval=1d"
        try:
            res = fetch_json(yf_url)
            result = res["chart"]["result"][0]
            timestamps = result["timestamp"]
            quote = result["indicators"]["quote"][0]
            
            # 過濾掉空值
            valid_bars = []
            for i in range(len(timestamps)):
                c = quote["close"][i]
                o = quote["open"][i]
                l = quote["low"][i]
                v = quote["volume"][i]
                if c is not None and o is not None and l is not None and v is not None:
                    valid_bars.append((timestamps[i], float(o), float(c), float(l), int(v) // 1000))
            
            if len(valid_bars) < 25:
                continue

            scanned_count += 1
            last_ts = valid_bars[-1][0]
            market_date = datetime.fromtimestamp(last_ts, tz=tw_tz).strftime("%Y-%m-%d")

            closes = [b[2] for b in valid_bars]
            opens = [b[1] for b in valid_bars]
            lows = [b[3] for b in valid_bars]
            vols = [b[4] for b in valid_bars]

            curr_c = closes[-1]
            curr_o = opens[-1]
            prev_c = closes[-2]
            curr_v = vols[-1]
            pct = round(((curr_c - prev_c) / prev_c) * 100, 2) if prev_c > 0 else 0

            ma5 = sum(closes[-5:]) / 5
            ma10 = sum(closes[-10:]) / 10
            ma20 = sum(closes[-20:]) / 20
            ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else ma20
            
            prev_ma5 = sum(closes[-6:-1]) / 5
            prev_ma20 = sum(closes[-21:-1]) / 20
            vol_ma5 = sum(vols[-6:-1]) / 5 if len(vols) >= 6 else curr_v
            vol_ratio = round(curr_v / vol_ma5, 1) if vol_ma5 > 0 else 1.0

            variance = sum((p - ma20) ** 2 for p in closes[-20:]) / 20
            std20 = math.sqrt(variance)
            bb_upper = ma20 + 2 * std20

            # 籌碼與量能主力標籤
            chip_tags = []
            if vol_ratio >= 1.5:
                chip_tags.append(f"主力爆量{vol_ratio}倍")
            elif vol_ratio >= 1.1:
                chip_tags.append(f"量增主力進場{vol_ratio}倍")

            # 【策略 A：朱家泓 / 林穎】收紅K + 站上 5MA 與 20MA 多頭起漲
            if curr_c >= curr_o and curr_c >= ma5 and curr_c >= ma20:
                z_tags = list(chip_tags) + ["站穩月線多頭"]
                if curr_c > ma10 and prev_c <= ma10:
                    z_tags.append("一陽穿三線")
                if min(lows[-5:]) >= min(lows[-15:-5]):
                    z_tags.append("底底高結構")
                if curr_c > ma60:
                    z_tags.append("季線之上")
                zhu_lin_picks.append({
                    "code": code, "name": name, "close": round(curr_c, 2),
                    "pct": pct, "vol": curr_v, "ma5": round(ma5, 2), "ma20": round(ma20, 2),
                    "tags": z_tags
                })

            # 【策略 B：莎拉形態學】5MA(金) >= 20MA(銀) 金包銀多頭結構 + 站穩布林中軌之上
            if ma5 >= ma20 and curr_c >= ma20:
                s_tags = list(chip_tags) + ["5MA/20MA金包銀"]
                if prev_ma5 <= prev_ma20:
                    s_tags.append("剛黃金交叉")
                if curr_c >= bb_upper * 0.95:
                    s_tags.append("沿布林上軌強攻")
                sarah_picks.append({
                    "code": code, "name": name, "close": round(curr_c, 2),
                    "pct": pct, "vol": curr_v, "ma5": round(ma5, 2), "ma20": round(ma20, 2),
                    "tags": s_tags
                })

        except Exception:
            continue

    zhu_lin_picks.sort(key=lambda x: x["pct"], reverse=True)
    sarah_picks.sort(key=lambda x: x["pct"], reverse=True)

    output = {
        "updated_at": f"{market_date} (已精算 {scanned_count} 檔 · 更新 {now_tw.strftime('%H:%M')})",
        "zhu_lin_picks": zhu_lin_picks[:12],
        "sarah_picks": sarah_picks[:12]
    }

    with open("recommendations.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
