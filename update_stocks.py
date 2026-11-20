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
    with urllib.request.urlopen(req, context=ctx, timeout=25) as resp:
        return json.loads(resp.read().decode('utf-8'))

def parse_lots(val):
    s = str(val or "0").replace(",", "").strip()
    if not s or s == "--":
        return 0
    return round(int(float(s)) / 1000, 1)

def main():
    candidates = []
    market_date = now_tw.strftime("%Y-%m-%d")
    inst_map = {}

    # 1. 抓取證交所三大法人明細（拆解外資、投信、自營商與合計大戶買賣超）
    try:
        for row in fetch_json("https://twse.com.tw"):
            code = str(row.get("Code", "")).strip()
            foreign_net = parse_lots(row.get("ForeignInvestorsNetBuySell", 0))
            trust_net = parse_lots(row.get("InvestmentTrustNetBuySell", 0))
            total_net = parse_lots(row.get("TotalInstitutionalInvestorsNetBuySell", 0))
            inst_map[code] = {
                "foreign": foreign_net,
                "trust": trust_net,
                "total": total_net
            }
    except Exception as e:
        print("三大法人資料暫無更新:", e)

    # 2. 抓取證交所全市場上市行情並結合籌碼初篩
    try:
        twse_data = fetch_json("https://twse.com.tw")
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

                chip = inst_map.get(code, {"foreign": 0, "trust": 0, "total": 0})
                
                # 排除法人大舉倒貨（賣超超過 1500 張）的股票，避免拉高出貨陷阱
                if chip["total"] < -1500:
                    continue

                # 收紅K且成交量 >= 1000 張進入技術指標精算
                if close_p >= open_p and pct_change >= 0 and vol_lots >= 1000:
                    candidates.append({
                        "code": code, "name": name, "close": close_p,
                        "pct": pct_change, "vol": vol_lots,
                        "foreign_net": chip["foreign"],
                        "trust_net": chip["trust"],
                        "inst_net": chip["total"]
                    })
            except Exception:
                continue
    except Exception as e:
        print("證交所行情抓取異常:", e)

    # 備援熱門觀察池
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
            chip = inst_map.get(c, {"foreign": 0, "trust": 0, "total": 0})
            candidates.append({
                "code": c, "name": n, "close": 0, "pct": 0, "vol": 0,
                "foreign_net": chip["foreign"], "trust_net": chip["trust"], "inst_net": chip["total"]
            })

    # 優先排序：有法人大戶買超 ＋ 成交量活躍的標的優先進行歷史 K 線精算
    candidates.sort(key=lambda x: (x["inst_net"] > 300, x["vol"], x["pct"]), reverse=True)
    top_candidates = candidates[:65]

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

            if curr_c < curr_o or curr_v < 800:
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

            # 建立外資 / 投信 / 大戶籌碼標籤
            chip_tags = []
            f_net = stock["foreign_net"]
            t_net = stock["trust_net"]
            tot_net = stock["inst_net"]

            if f_net > 0 and t_net > 0 and (f_net + t_net) >= 300:
                chip_tags.append("土洋同步買超")
            if f_net >= 500:
                chip_tags.append(f"外資大買{int(f_net)}張")
            elif f_net >= 150:
                chip_tags.append(f"外資買超{int(f_net)}張")
            if t_net >= 100:
                chip_tags.append(f"投信認養{int(t_net)}張")
            if tot_net >= 800:
                chip_tags.append(f"法人大戶掃貨{int(tot_net)}張")

            # 籌碼過濾條件：必須具備「外資買超 > 100張」或「投信買超 > 50張」或「三大法人合計買超 > 200張」
            has_big_player = (f_net >= 100) or (t_net >= 50) or (tot_net >= 200)
            if not has_big_player:
                continue

            # 【策略 A：朱家泓 / 林穎 ＋ 大戶籌碼】站上 5MA 與 20MA 多頭起漲，且量增
            if curr_c >= ma5 and curr_c >= ma20 and curr_v >= vol_ma5 * 1.05:
                z_tags = list(chip_tags) + ["站穩月線多頭"]
                if curr_c > ma10 and prev_c <= ma10:
                    z_tags.append("一陽穿三線")
                if min(lows[-5:]) >= min(lows[-15:-5]):
                    z_tags.append("底底高結構")
                if curr_c > ma60:
                    z_tags.append("季線之上")
                zhu_lin_picks.append({**stock, "ma5": round(ma5, 2), "ma20": round(ma20, 2), "tags": z_tags})

            # 【策略 B：莎拉形態學 ＋ 大戶籌碼】5MA/20MA 金包銀多頭結構，站穩布林中軌之上
            if ma5 >= ma20 and curr_c >= ma20:
                s_tags = list(chip_tags) + ["5MA/20MA金包銀"]
                if prev_ma5 <= prev_ma20:
                    s_tags.append("剛黃金交叉")
                if curr_c >= bb_upper * 0.96:
                    s_tags.append("挑戰布林上軌")
                sarah_picks.append({**stock, "ma5": round(ma5, 2), "ma20": round(ma20, 2), "tags": s_tags})

        except Exception:
            continue

    # 排序：法人買超張數越多、漲幅越強排越前面
    zhu_lin_picks.sort(key=lambda x: (x["inst_net"], x["pct"]), reverse=True)
    sarah_picks.sort(key=lambda x: (x["inst_net"], x["pct"]), reverse=True)

    output = {
        "updated_at": f"{market_date} (系統更新 {now_tw.strftime('%H:%M')})",
        "zhu_lin_picks": zhu_lin_picks[:10],
        "sarah_picks": sarah_picks[:10]
    }

    with open("recommendations.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
