import urllib.request
import json
import math
from datetime import datetime, timedelta, timezone

# 設定台灣時區
tw_tz = timezone(timedelta(hours=8))
now_tw = datetime.now(tw_tz)

def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode('utf-8'))

def main():
    print(f"[{now_tw.strftime('%Y-%m-%d %H:%M:%S')}] 開始抓取台股全市場真實盤後資料...")
    
    # 1. 抓取證交所(上市)當日全市場收盤行情
    twse_url = "https://twse.com.tw"
    twse_data = fetch_json(twse_url)
    
    # 2. 抓取證交所(上市)三大法人買賣超
    t86_url = "https://twse.com.tw"
    try:
        t86_list = fetch_json(t86_url)
        inst_map = {}
        for row in t86_list:
            code = row.get("Code", "").strip()
            # 三大法人買賣超股數
            net_buy = int(float(row.get("TotalInstitutionalInvestorsNetBuySell", "0").replace(",", "") or 0))
            inst_map[code] = round(net_buy / 1000, 1) # 換算為張數
    except Exception as e:
        print("三大法人資料暫無更新，略過籌碼過濾:", e)
        inst_map = {}

    # 3. 取得核心觀察池歷史 K 線 (透過 FinMind 免費開放資料計算真實均線與布林通道)
    # 先從當日上市普通股中，初篩出「收紅、成交量 > 2000張」的活躍標的，再抓60日K線精算技術指標
    candidates = []
    for item in twse_data:
        code = item.get("Code", "").strip()
        name = item.get("Name", "").strip()
        # 排除 ETF 與權證 (只保留4碼純數字普通股且非00開頭)
        if len(code) != 4 or not code.isdigit() or code.startswith("00"):
            continue
        try:
            close_p = float(item.get("ClosingPrice", 0))
            open_p = float(item.get("OpeningPrice", 0))
            high_p = float(item.get("HighestPrice", 0))
            low_p = float(item.get("LowestPrice", 0))
            vol_shares = int(item.get("TradeVolume", 0))
            change_str = item.get("Change", "0").replace("+", "").replace("X", "0")
            change_p = float(change_str)
            
            vol_lots = vol_shares // 1000
            prev_close = close_p - change_p
            pct_change = round((change_p / prev_close) * 100, 2) if prev_close > 0 else 0

            # 初篩：當日收紅、漲幅 > 1%、成交量 > 2,000 張
            if close_p > open_p and pct_change >= 1.0 and vol_lots >= 2000:
                candidates.append({
                    "code": code,
                    "name": name,
                    "close": close_p,
                    "open": open_p,
                    "high": high_p,
                    "low": low_p,
                    "pct": pct_change,
                    "vol": vol_lots,
                    "inst_net": inst_map.get(code, 0)
                })
        except:
            continue

    # 依成交量與漲幅排序，取前 60 檔活躍股進行 60 日均線與布林通道深度精算
    candidates.sort(key=lambda x: (x["vol"], x["pct"]), reverse=True)
    top_candidates = candidates[:60]
    print(f"初篩活躍股共 {len(candidates)} 檔，針對前 {len(top_candidates)} 檔進行歷史均線與布林精算...")

    start_date = (now_tw - timedelta(days=100)).strftime("%Y-%m-%d")
    zhu_lin_picks = []   # 朱家泓 / 林穎：底部起漲與均線多頭突破
    sarah_picks = []     # 莎拉形態學：布林通道金包銀與壓縮開口

    for stock in top_candidates:
        code = stock["code"]
        fm_url = f"https://finmindtrade.com{code}&start_date={start_date}"
        try:
            res = fetch_json(fm_url)
            hist = res.get("data", [])
            if len(hist) < 25:
                continue
            
            closes = [float(d["close"]) for d in hist]
            lows = [float(d["min"]) for d in hist]
            vols = [int(d["Trading_Volume"]) // 1000 for d in hist]

            # 計算均線
            ma5 = sum(closes[-5:]) / 5
            ma10 = sum(closes[-10:]) / 10
            ma20 = sum(closes[-20:]) / 20
            ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else ma20
            
            prev_ma5 = sum(closes[-6:-1]) / 5
            prev_ma20 = sum(closes[-21:-1]) / 20
            vol_ma5 = sum(vols[-6:-1]) / 5 if len(vols) >= 6 else vols[-1]

            # 計算 20 日布林通道 (中軌 20MA ± 2倍標準差)
            variance = sum((p - ma20) ** 2 for p in closes[-20:]) / 20
            std20 = math.sqrt(variance)
            bb_upper = ma20 + 2 * std20
            bb_lower = ma20 - 2 * std20
            bb_width = (bb_upper - bb_lower) / ma20 if ma20 > 0 else 0

            prev_var = sum((p - prev_ma20) ** 2 for p in closes[-21:-1]) / 20
            prev_std = math.sqrt(prev_var)
            prev_bb_width = (4 * prev_std) / prev_ma20 if prev_ma20 > 0 else 0

            curr_c = closes[-1]
            curr_v = vols[-1]
            tags = []

            # 檢查籌碼加分
            if stock["inst_net"] > 300:
                tags.append(f"法人買超{int(stock['inst_net'])}張")

            # 【策略 A：朱家泓 / 林穎 均線多頭與底部起漲】
            # 條件：站上 5MA/10MA/20MA、底底高(近5日最低 > 前10日最低)、成交量 > 5日均量1.3倍
            recent_low = min(lows[-5:])
            prior_low = min(lows[-15:-5])
            if curr_c > ma5 and curr_c > ma10 and curr_c > ma20 and recent_low >= prior_low and curr_v >= vol_ma5 * 1.3:
                z_tags = list(tags)
                z_tags.append("一陽站上三線")
                z_tags.append("底底高結構")
                if curr_c > ma60:
                    z_tags.append("站穩季線")
                stock_info = {**stock, "ma5": round(ma5, 2), "ma20": round(ma20, 2), "tags": z_tags}
                zhu_lin_picks.append(stock_info)

            # 【策略 B：莎拉形態學 布林通道金包銀】
            # 條件：5MA(金) > 20MA(銀) 且剛黃金交叉或低乖離(<3%)、股價站上布林中軌、布林帶寬開口擴大
            golden_cross = (prev_ma5 <= prev_ma20 and ma5 > ma20) or (ma5 > ma20 and (ma5 - ma20) / ma20 <= 0.035)
            bb_expanding = bb_width > prev_bb_width
            if golden_cross and curr_c > ma20 and bb_expanding:
                s_tags = list(tags)
                s_tags.append("5MA/20MA金包銀")
                s_tags.append("布林開口向上")
                if curr_c >= bb_upper * 0.98:
                    s_tags.append("沿上軌強攻")
                stock_info = {**stock, "ma5": round(ma5, 2), "ma20": round(ma20, 2), "bb_upper": round(bb_upper, 2), "tags": s_tags}
                sarah_picks.append(stock_info)

        except Exception as e:
            continue

    output = {
        "updated_at": now_tw.strftime("%Y-%m-%d %H:%M"),
        "market_date": twse_data[0].get("Date", "") if twse_data else "",
        "zhu_lin_picks": zhu_lin_picks[:12],
        "sarah_picks": sarah_picks[:12]
    }

    with open("recommendations.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"完成！朱林策略選出 {len(zhu_lin_picks)} 檔，莎拉策略選出 {len(sarah_picks)} 檔。")

if __name__ == "__main__":
    main()
