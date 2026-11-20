import urllib.request
import ssl
import json
import math
import time
from datetime import datetime, timedelta, timezone

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

tw_tz = timezone(timedelta(hours=8))
now_tw = datetime.now(tw_tz)

def fetch_json(url):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*'
    })
    with urllib.request.urlopen(req, context=ctx, timeout=25) as resp:
        return json.loads(resp.read().decode('utf-8'))

def parse_num(val):
    s = str(val or "0").replace(",", "").replace("+", "").replace("X", "").strip()
    if not s or s == "--":
        return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0

def main():
    status_notes = []
    inst_map = {}

    # 1. 抓取證交所三大法人買賣超 (T86)
    try:
        t86_data = fetch_json("https://twse.com.tw")
        for row in t86_data:
            code = str(row.get("Code", "")).strip()
            f_net = round(parse_num(row.get("ForeignInvestorsNetBuySell", 0)) / 1000, 1)
            t_net = round(parse_num(row.get("InvestmentTrustNetBuySell", 0)) / 1000, 1)
            tot_net = round(parse_num(row.get("TotalInstitutionalInvestorsNetBuySell", 0)) / 1000, 1)
            inst_map[code] = {"foreign": f_net, "trust": t_net, "total": tot_net}
        status_notes.append(f"法人資料{len(inst_map)}筆")
    except Exception as e:
        status_notes.append(f"T86異常:{type(e).__name__}")

    # 2. 抓取證交所全市場上市每日收盤行情 (STOCK_DAY_ALL)
    daily_list = []
    market_date = now_tw.strftime("%Y-%m-%d")
    try:
        all_data = fetch_json("https://twse.com.tw")
        for item in all_data:
            code = str(item.get("Code", "")).strip()
            name = str(item.get("Name", "")).strip()
            if len(code) != 4 or not code.isdigit() or code.startswith("00"):
                continue
            close_p = parse_num(item.get("ClosingPrice"))
            open_p = parse_num(item.get("OpeningPrice"))
            high_p = parse_num(item.get("HighestPrice"))
            low_p = parse_num(item.get("LowestPrice"))
            vol_lots = int(parse_num(item.get("TradeVolume")) // 1000)
            chg_p = parse_num(item.get("Change"))
            if close_p <= 0 or open_p <= 0:
                continue
            prev_c = close_p - chg_p
            pct = round((chg_p / prev_c) * 100, 2) if prev_c > 0 else 0.0
            chip = inst_map.get(code, {"foreign": 0.0, "trust": 0.0, "total": 0.0})

            # 初篩：當日收紅(收盤 >= 開盤)、成交量 >= 1500張、三大法人無大幅倒貨
            if close_p >= open_p and vol_lots >= 1500 and chip["total"] > -1500:
                daily_list.append({
                    "code": code, "name": name, "close": close_p, "open": open_p,
                    "high": high_p, "low": low_p, "pct": pct, "vol": vol_lots,
                    "foreign": chip["foreign"], "trust": chip["trust"], "inst_net": chip["total"]
                })
        status_notes.append(f"初篩活躍股{len(daily_list)}檔")
    except Exception as e:
        status_notes.append(f"行情異常:{type(e).__name__}")

    # 依法人買超與漲幅排序，取前 35 檔最強勢標的向證交所抓取近 2 個月歷史 K 線計算均線與布林
    daily_list.sort(key=lambda x: (x["inst_net"] > 100, x["pct"]), reverse=True)
    top_pool = daily_list[:35]

    zhu_lin_picks = []
    sarah_picks = []
    scanned_count = 0

    # 計算本月與上月日期字串 (YYYYMM01)
    this_month = now_tw.strftime("%Y%m01")
    first_of_this = now_tw.replace(day=1)
    last_month = (first_of_this - timedelta(days=1)).strftime("%Y%m01")

    for stock in top_pool:
        code = stock["code"]
        closes = []
        lows = []
        vols = []
        try:
            for ym in (last_month, this_month):
                url = f"https://twse.com.tw{ym}&stockNo={code}"
                res = fetch_json(url)
                if res.get("stat") == "OK":
                    for row in res.get("data", []):
                        # row: [日期, 成交股數, 成交金額, 開盤, 最高, 最低, 收盤, 漲跌, 筆數]
                        cols = list(row)
                        if len(cols) >= 7:
                            v_l = int(parse_num(cols.pop(1)) // 1000)
                            # 取出最低與收盤 (原本 index 5 與 6，pop(1) 後變成 4 與 5)
                            l_p = parse_num(cols.pop(4))
                            c_p = parse_num(cols.pop(4))
                            if c_p > 0:
                                closes.append(c_p)
                                lows.append(l_p)
                                vols.append(v_l)
                time.sleep(0.15)
        except Exception:
            pass

        # 若證交所歷史月線暫時限流，仍保留當日真實盤後強勢與法人買超數據作為備援
        if len(closes) >= 20:
            scanned_count += 1
            ma5 = sum(closes[-5:]) / 5
            ma10 = sum(closes[-10:]) / 10
            ma20 = sum(closes[-20:]) / 20
            prev_ma5 = sum(closes[-6:-1]) / 5
            prev_ma20 = sum(closes[-21:-1]) / 20
            vol_ma5 = sum(vols[-6:-1]) / 5 if len(vols) >= 6 else stock["vol"]
            vol_ratio = round(stock["vol"] / vol_ma5, 1) if vol_ma5 > 0 else 1.0

            variance = sum((p - ma20) ** 2 for p in closes[-20:]) / 20
            std20 = math.sqrt(variance)
            bb_upper = ma20 + 2 * std20

            chip_tags = []
            if stock["foreign"] > 0 and stock["trust"] > 0:
                chip_tags.append("土洋同步買超")
            if stock["foreign"] >= 300:
                chip_tags.append(f"外資大買{int(stock['foreign'])}張")
            elif stock["foreign"] > 0:
                chip_tags.append(f"外資買超{int(stock['foreign'])}張")
            if stock["trust"] >= 50:
                chip_tags.append(f"投信認養{int(stock['trust'])}張")
            if vol_ratio >= 1.3:
                chip_tags.append(f"主力爆量{vol_ratio}倍")

            curr_c = stock["close"]
            prev_c = closes[-2]

            # 策略 A：朱家泓 / 林穎 (站上5MA與20MA多頭起漲)
            if curr_c >= ma5 and curr_c >= ma20:
                z_tags = list(chip_tags) + ["站穩月線多頭"]
                if curr_c > ma10 and prev_c <= ma10:
                    z_tags.append("一陽穿三線")
                if len(lows) >= 15 and min(lows[-5:]) >= min(lows[-15:-5]):
                    z_tags.append("底底高結構")
                zhu_lin_picks.append({
                    "code": code, "name": stock["name"], "close": curr_c,
                    "pct": stock["pct"], "vol": stock["vol"],
                    "ma5": round(ma5, 2), "ma20": round(ma20, 2),
                    "inst_net": stock["inst_net"], "tags": z_tags
                })

            # 策略 B：莎拉形態學 (5MA/20MA 金包銀多頭結構)
            if ma5 >= ma20 and curr_c >= ma20:
                s_tags = list(chip_tags) + ["5MA/20MA金包銀"]
                if prev_ma5 <= prev_ma20:
                    s_tags.append("剛黃金交叉")
                if curr_c >= bb_upper * 0.95:
                    s_tags.append("沿布林上軌強攻")
                sarah_picks.append({
                    "code": code, "name": stock["name"], "close": curr_c,
                    "pct": stock["pct"], "vol": stock["vol"],
                    "ma5": round(ma5, 2), "ma20": round(ma20, 2),
                    "inst_net": stock["inst_net"], "tags": s_tags
                })
        else:
            # 備援：直接依證交所當日真實盤後強勢紅K + 法人買超篩選
            if stock["pct"] >= 1.5 and (stock["foreign"] > 100 or stock["trust"] > 30 or stock["inst_net"] > 200):
                b_tags = ["盤後真實強勢紅K"]
                if stock["foreign"] > 0:
                    b_tags.append(f"外資買超{int(stock['foreign'])}張")
                if stock["trust"] > 0:
                    b_tags.append(f"投信買超{int(stock['trust'])}張")
                item_obj = {
                    "code": code, "name": stock["name"], "close": stock["close"],
                    "pct": stock["pct"], "vol": stock["vol"],
                    "ma5": stock["open"], "ma20": stock["low"],
                    "inst_net": stock["inst_net"], "tags": b_tags
                }
                zhu_lin_picks.append(item_obj)
                sarah_picks.append(item_obj)

    zhu_lin_picks.sort(key=lambda x: (x["inst_net"], x["pct"]), reverse=True)
    sarah_picks.sort(key=lambda x: (x["inst_net"], x["pct"]), reverse=True)

    diag_text = " | ".join(status_notes)
    output = {
        "updated_at": f"{market_date} ({diag_text} · 精算{scanned_count}檔 · {now_tw.strftime('%H:%M')})",
        "zhu_lin_picks": zhu_lin_picks[:12],
        "sarah_picks": sarah_picks[:12]
    }

    with open("recommendations.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
