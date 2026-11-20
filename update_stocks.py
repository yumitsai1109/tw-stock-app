import urllib.request
import ssl
import json
import math
from datetime import datetime, timedelta, timezone

# 忽略證交所 SSL 憑證驗證問題（解決雲端主機連線失敗）
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

tw_tz = timezone(timedelta(hours=8))
now_tw = datetime.now(tw_tz)

def fetch_json(url):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    with urllib.request.urlopen(req, context=ctx, timeout=25) as resp:
        return json.loads(resp.read().decode('utf-8'))

def main():
    print(f"[{now_tw.strftime('%Y-%m-%d %H:%M:%S')}] 開始執行台股選股引擎...")
    candidates = []
    market_date = now_tw.strftime("%Y-%m-%d")

    # 嘗試從證交所 OpenAPI 抓取全市場上市行情
    try:
        twse_url = "https://twse.com.tw"
        twse_data = fetch_json(twse_url)
        
        inst_map = {}
        try:
            t86_list = fetch_json("https://twse.com.tw")
            for row in t86_list:
                code = str(row.get("Code", "")).strip()
                raw_net = str(row.get("TotalInstitutionalInvestorsNetBuySell", "0")).replace(",", "").strip()
                net_buy = int(float(raw_net)) if raw_net and raw_net != "--" else 0
                inst_map[code] = round(net_buy / 1000, 1)
        except Exception as e:
            print("三大法人暫無資料:", e)

        for item in twse_data:
            code = str(item.get("Code", "")).strip()
            name = str(item.get("Name", "")).strip()
            if len(code) != 4 or not code.isdigit() or code.startswith("00"):
                continue
            try:
                c_str = str(item.get("ClosingPrice", "0")).replace(",", "").strip()
                o_str = str(item.get("OpeningPrice", "0")).replace(",", "").strip()
                v_str = str(item.get("TradeVolume", "0")).replace(",", "").strip()
                chg_str = str(item.get("Change", "0")).replace("+", "").replace("X", "0").replace(",", "").strip()
                
                if not c_str or c_str == "--" or not o_str or o_str == "--":
                    continue
                close_p = float(c_str)
                open_p = float(o_str)
                vol_lots = int(float(v_str)) // 1000
                change_p = float(chg_str) if chg_str and chg_str != "--" else 0.0
                
                prev_close = close_p - change_p
                pct_change = round((change_p / prev_close) * 100, 2) if prev_close > 0 else 0

                if close_p > open_p and pct_change >= 0.8 and vol_lots >= 1500:
                    candidates.append({
                        "code": code,
                        "name": name,
                        "close": close_p,
                        "pct": pct_change,
                        "vol": vol_lots,
                        "inst_net": inst_map.get(code, 0)
                    })
            except Exception:
                continue
        print(f"證交所資料解析成功，初篩出 {len(candidates)} 檔活躍股")
    except Exception as e:
        print("證交所連線異常，改用備援觀察池:", e)

    # 若證交所維護或連不上，自動啟用台股主流 50 檔核心觀察池（絕無假資料）
    if not candidates:
        backup_pool = [
            ("2330","台積電"),("2317","鴻海"),("2454","聯發科"),("2382","廣達"),("3231","緯創"),
            ("2308","台達電"),("2303","聯電"),("3711","日月光投控"),("2357","華碩"),("2376","技嘉"),
            ("3017","奇鋐"),("3324","雙鴻"),("2368","金像電"),("3037","欣興"),("2383","台光電"),
            ("2603","長榮"),("2609","陽明"),("2615","萬海"),("2618","長榮航"),("2610","華航"),
            ("1513","中興電"),("1519","華城"),("1503","士電"),("1504","東元"),("1609","大亞"),
            ("2881","富邦金"),("2882","國泰金"),("2891","中信金"),("2886","兆豐金"),("2884","玉山金"),
            ("2327","國巨"),("2492","華新科"),("3008","大立光"),("3443","創意"),("3661","世芯-KY"),
            ("6669","緯穎"),("2356","英業達"),("2324","仁寶"),("4938","和碩"),("2301","光寶科"),
            ("2345","智邦"),("3533","嘉澤"),("2049","上銀"),("1590","亞德客-KY"),("2395","研華"),
            ("2408","南亞科"),("2344","華邦電"),("3034","聯詠"),("2379","瑞昱"),("5347","世界")
        ]
        for c, n in backup_pool:
            candidates.append({"code": c, "name": n, "close": 0, "pct": 0, "vol": 0, "inst_net": 0})

    candidates.sort(key=lambda x: (x["vol"], x["pct"]), reverse=True)
    top_candidates = candidates[:55]

    start_date = (now_tw - timedelta(days=100)).strftime("%Y-%m-%d")
    zhu_lin_picks = []
    sarah_picks = []

    for stock in top_candidates:
        code = stock["code"]
        fm_url = f"https://finmindtrade.com{code}&start_date={start_date}"
        try:
            res = fetch_json(fm_url)
            hist = res.get("data", [])
            if len(hist) < 25:
                continue
            
            closes = [float(d["close"]) for d in hist]
            opens = [float(d["open"]) for d in hist]
            lows = [float(d["min"]) for d in hist]
            vols = [int(d["Trading_Volume"]) // 1000 for d in hist]
            market_date = hist[-1].get("date", market_date)

            curr_c = closes[-1]
            curr_o = opens[-1]
            prev_c = closes[-2]
            curr_v = vols[-1]
            pct = round(((curr_c - prev_c) / prev_c) * 100, 2) if prev_c > 0 else 0

            if curr_c <= curr_o or pct < 0.5 or curr_v < 1000:
                continue

            stock["close"] = curr_c
            stock["pct"] = pct
            stock["vol"] = curr_v

            ma5 = sum(closes[-5:]) / 5
            ma10 = sum(closes[-10:]) / 10
            ma20 = sum(closes[-20:]) / 20
            ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else ma20
            
            prev_ma5 = sum(closes[-6:-1]) / 5
            prev_ma20 = sum(closes[-21:-1]) / 20
            vol_ma5 = sum(vols[-6:-1]) / 5 if len(vols) >= 6 else curr_v

            variance = sum((p - ma20) ** 2 for p in closes[-20:]) / 20
            std20 = math.sqrt(variance)
            bb_upper = ma20 + 2 * std20
            bb_width = (4 * std20) / ma20 if ma20 > 0 else 0

            prev_var = sum((p - prev_ma20) ** 2 for p in closes[-21:-1]) / 20
            prev_std = math.sqrt(prev_var)
            prev_bb_width = (4 * prev_std) / prev_ma20 if prev_ma20 > 0 else 0

            tags = []
            if stock["inst_net"] > 300:
                tags.append(f"法人買超{int(stock['inst_net'])}張")

            # 朱家泓 / 林穎：站上三線 + 底底高 + 成交量放大
            recent_low = min(lows[-5:])
            prior_low = min(lows[-15:-5])
            if curr_c > ma5 and curr_c > ma10 and curr_c > ma20 and recent_low >= prior_low and curr_v >= vol_ma5 * 1.2:
                z_tags = list(tags) + ["一陽站上三線", "底底高結構"]
                if curr_c > ma60:
                    z_tags.append("站穩季線")
                zhu_lin_picks.append({**stock, "ma5": round(ma5, 2), "ma20": round(ma20, 2), "tags": z_tags})

            # 莎拉形態學：5MA/20MA 金包銀 + 布林開口向上
            golden_cross = (prev_ma5 <= prev_ma20 and ma5 > ma20) or (ma5 > ma20 and (ma5 - ma20) / ma20 <= 0.04)
            if golden_cross and curr_c > ma20 and bb_width > prev_bb_width:
                s_tags = list(tags) + ["5MA/20MA金包銀", "布林開口向上"]
                if curr_c >= bb_upper * 0.98:
                    s_tags.append("沿上軌強攻")
                sarah_picks.append({**stock, "ma5": round(ma5, 2), "ma20": round(ma20, 2), "tags": s_tags})

        except Exception:
            continue

    output = {
        "updated_at": f"{market_date} (系統更新 {now_tw.strftime('%H:%M')})",
        "zhu_lin_picks": zhu_lin_picks[:12],
        "sarah_picks": sarah_picks[:12]
    }

    with open("recommendations.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"執行完畢！朱林策略：{len(zhu_lin_picks)} 檔，莎拉策略：{len(sarah_picks)} 檔。")

if __name__ == "__main__":
    main()
