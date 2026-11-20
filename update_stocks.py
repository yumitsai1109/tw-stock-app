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
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
        return json.loads(resp.read().decode('utf-8'))

def main():
    # 台股主流核心觀察池（涵蓋半導體、AI伺服器、重電、航運、金融、電子零組件、面板記憶體）
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

    start_date = (now_tw - timedelta(days=95)).strftime("%Y-%m-%d")
    chip_start = (now_tw - timedelta(days=7)).strftime("%Y-%m-%d")
    
    zhu_lin_picks = []
    sarah_picks = []
    market_date = now_tw.strftime("%Y-%m-%d")
    scanned_count = 0
    err_sample = ""

    for code, name in watch_list:
        try:
            # 1. 抓取 FinMind 真實歷史日 K 線
            price_url = f"https://finmindtrade.com{code}&start_date={start_date}"
            p_res = fetch_json(price_url)
            hist = p_res.get("data", [])
            if len(hist) < 20:
                continue

            scanned_count += 1
            opens = [float(d.get("open", 0)) for d in hist]
            closes = [float(d.get("close", 0)) for d in hist]
            lows = [float(d.get("min", 0)) for d in hist]
            vols = [int(d.get("Trading_Volume", 0)) // 1000 for d in hist]
            
            last_row = hist[-1]
            market_date = str(last_row.get("date", market_date))

            curr_c = closes[-1]
            curr_o = opens[-1]
            prev_c = closes[-2]
            curr_v = vols[-1]
            pct = round(((curr_c - prev_c) / prev_c) * 100, 2) if prev_c > 0 else 0.0

            # 2. 抓取 FinMind 三大法人買賣超 (外資/投信)
            f_net = 0.0
            t_net = 0.0
            try:
                inst_url = f"https://finmindtrade.com{code}&start_date={chip_start}"
                i_res = fetch_json(inst_url)
                i_data = i_res.get("data", [])
                if i_data:
                    latest_chip_date = i_data[-1].get("date")
                    for row in i_data:
                        if row.get("date") == latest_chip_date:
                            inv_name = str(row.get("name", ""))
                            net_lots = round((int(row.get("buy", 0)) - int(row.get("sell", 0))) / 1000, 1)
                            if "Foreign_Investor" in inv_name:
                                f_net += net_lots
                            elif "Investment_Trust" in inv_name:
                                t_net += net_lots
            except Exception:
                pass

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

            chip_tags = []
            if f_net > 0 and t_net > 0:
                chip_tags.append("土洋同步買超")
            if f_net >= 300:
                chip_tags.append(f"外資大買{int(f_net)}張")
            elif f_net > 0:
                chip_tags.append(f"外資買超{int(f_net)}張")
            if t_net >= 50:
                chip_tags.append(f"投信認養{int(t_net)}張")
            if vol_ratio >= 1.3:
                chip_tags.append(f"主力爆量{vol_ratio}倍")

            tot_inst = round(f_net + t_net, 1)

            # 【策略 A：朱家泓 / 林穎】抗跌收紅K + 站上 5MA 與 20MA 多頭起漲
            if curr_c >= curr_o and curr_c >= ma5 and curr_c >= ma20:
                z_tags = list(chip_tags) + ["抗跌站穩月線"]
                if curr_c > ma10 and prev_c <= ma10:
                    z_tags.append("一陽穿三線")
                if min(lows[-5:]) >= min(lows[-15:-5]):
                    z_tags.append("底底高結構")
                if curr_c > ma60:
                    z_tags.append("季線之上")
                zhu_lin_picks.append({
                    "code": code, "name": name, "close": curr_c,
                    "pct": pct, "vol": curr_v, "ma5": round(ma5, 2), "ma20": round(ma20, 2),
                    "inst_net": tot_inst, "tags": z_tags
                })

            # 【策略 B：莎拉形態學】5MA(金) >= 20MA(銀) 金包銀多頭結構 + 站穩布林中軌之上
            if ma5 >= ma20 and curr_c >= ma20:
                s_tags = list(chip_tags) + ["5MA/20MA金包銀"]
                if prev_ma5 <= prev_ma20:
                    s_tags.append("剛黃金交叉")
                if curr_c >= bb_upper * 0.95:
                    s_tags.append("沿布林上軌強攻")
                sarah_picks.append({
                    "code": code, "name": name, "close": curr_c,
                    "pct": pct, "vol": curr_v, "ma5": round(ma5, 2), "ma20": round(ma20, 2),
                    "inst_net": tot_inst, "tags": s_tags
                })

        except Exception as e:
            if not err_sample:
                err_sample = type(e).__name__
            continue

    zhu_lin_picks.sort(key=lambda x: (x["inst_net"] > 0, x["pct"]), reverse=True)
    sarah_picks.sort(key=lambda x: (x["inst_net"] > 0, x["pct"]), reverse=True)

    diag = f"FinMind精算{scanned_count}檔" if scanned_count > 0 else f"連線異常:{err_sample}"
    output = {
        "updated_at": f"{market_date} ({diag} · 更新 {now_tw.strftime('%H:%M')})",
        "zhu_lin_picks": zhu_lin_picks[:12],
        "sarah_picks": sarah_picks[:12]
    }

    with open("recommendations.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
