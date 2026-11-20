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

def fetch_text(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "application/json, text/csv, */*"
    })
    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")

def safe_float(val, default=0.0):
    try:
        s = str(val).replace(",", "").strip()
        if not s or s in ("--", "N/A", "null", "None"):
            return default
        return float(s)
    except Exception:
        return default

def safe_int(val, default=0):
    try:
        return int(safe_float(val, float(default)))
    except Exception:
        return default

def evaluate_stock(code, name, opens, closes, lows, vols, inst_lots=None):
    if len(closes) < 21:
        return None, None

    curr_c = closes[-1]
    curr_o = opens[-1]
    prev_c = closes[-2]
    curr_v = vols[-1]

    if curr_v < 1500 or prev_c <= 0 or curr_c <= 0:
        return None, None

    pct = round(((curr_c - prev_c) / prev_c) * 100, 2)
    ma5 = sum(closes[-5:]) / 5.0
    ma10 = sum(closes[-10:]) / 10.0
    ma20 = sum(closes[-20:]) / 20.0
    ma60 = sum(closes[-60:]) / 60.0 if len(closes) >= 60 else ma20

    prev_ma5 = sum(closes[-6:-1]) / 5.0
    prev_ma20 = sum(closes[-21:-1]) / 20.0
    vol_ma5 = sum(vols[-6:-1]) / 5.0 if len(vols) >= 6 else float(curr_v)
    vol_ratio = round(curr_v / vol_ma5, 1) if vol_ma5 > 0 else 1.0

    variance = sum((p - ma20) ** 2 for p in closes[-20:]) / 20.0
    std20 = math.sqrt(max(variance, 0.0))
    bb_upper = ma20 + 2.0 * std20

    chip_tags = []
    if inst_lots is not None and inst_lots >= 500:
        chip_tags.append(f"三大法人買超{inst_lots:,}張")
    if vol_ratio >= 1.5:
        chip_tags.append(f"主力大戶爆量{vol_ratio}倍")
    elif vol_ratio >= 1.15:
        chip_tags.append(f"資金量增進場{vol_ratio}倍")

    zhu_item = None
    sarah_item = None

    # 策略 A：朱家泓 / 林穎（收紅K + 站上 5MA 與 20MA 多頭起漲）
    if curr_c >= curr_o and curr_c >= ma5 and curr_c >= ma20:
        z_tags = list(chip_tags) + ["站穩月線多頭"]
        if curr_c > ma10 and prev_c <= ma10:
            z_tags.append("一陽穿三線")
        if len(lows) >= 15 and min(lows[-5:]) >= min(lows[-15:-5]):
            z_tags.append("底底高結構")
        if curr_c > ma60:
            z_tags.append("季線之上")
        zhu_item = {
            "code": code, "name": name, "close": round(curr_c, 2),
            "pct": pct, "vol": curr_v, "ma5": round(ma5, 2), "ma20": round(ma20, 2),
            "tags": z_tags
        }

    # 策略 B：莎拉形態學（5MA >= 20MA 金包銀多頭結構 + 站穩布林中軌之上）
    if ma5 >= ma20 and curr_c >= ma20:
        s_tags = list(chip_tags) + ["5MA/20MA金包銀"]
        if prev_ma5 <= prev_ma20:
            s_tags.append("剛黃金交叉")
        if curr_c >= bb_upper * 0.95:
            s_tags.append("沿2倍布林上軌強攻")
        sarah_item = {
            "code": code, "name": name, "close": round(curr_c, 2),
            "pct": pct, "vol": curr_v, "ma5": round(ma5, 2), "ma20": round(ma20, 2),
            "tags": s_tags
        }

    return zhu_item, sarah_item

def main():
    zhu_lin_picks = []
    sarah_picks = []
    market_date = now_tw.strftime("%Y-%m-%d")
    scanned_count = 0
    diag_notes = []

    # 1. 先嘗試抓取 TWSE 三大法人買賣超 T86_ALL（供籌碼加分標籤與全市場掃描使用）
    inst_map = {}
    twse_daily_list = []
    try:
        t86_raw = fetch_text("https://openapi.twse.com.tw/v1/fund/T86_ALL", timeout=20)
        t86_data = json.loads(t86_raw)
        if isinstance(t86_data, list):
            for r in t86_data:
                c = str(r.get("證券代號", "")).strip()
                net_shares = safe_int(r.get("三大法人買賣超股數", 0))
                if c:
                    inst_map[c] = net_shares // 1000
    except Exception as e:
        diag_notes.append(f"T86略過:{str(e)[:25]}")

    try:
        day_raw = fetch_text("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=20)
        day_data = json.loads(day_raw)
        if isinstance(day_data, list) and len(day_data) > 0:
            twse_daily_list = day_data
    except Exception as e:
        diag_notes.append(f"TWSE日線略過:{str(e)[:25]}")

    # 2. 使用 Stooq 全球開放台股日 K 線 CSV 接口精算 60 檔主流權值與中小型飆股（含完整 5/10/20/60MA 與布林通道）
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

    seen_codes = set()
    for code, name in watch_list:
        stooq_url = f"https://stooq.com/q/d/l/?s={code}.tw&i=d"
        try:
            csv_text = fetch_text(stooq_url, timeout=12)
            lines = [line.strip() for line in csv_text.strip().splitlines() if line.strip()]
            if len(lines) < 25:
                continue

            bars = []
            for line in lines[-70:]:
                parts = line.split(",")
                if len(parts) >= 6 and parts[0] != "Date":
                    d_str = parts[0].strip()
                    o_val = safe_float(parts[1])
                    l_val = safe_float(parts[3])
                    c_val = safe_float(parts[4])
                    v_lots = safe_int(parts[5]) // 1000
                    if c_val > 0 and o_val > 0:
                        bars.append((d_str, o_val, c_val, l_val, v_lots))

            if len(bars) < 22:
                continue

            scanned_count += 1
            seen_codes.add(code)
            market_date = bars[-1][0]

            opens = [b[1] for b in bars]
            closes = [b[2] for b in bars]
            lows = [b[3] for b in bars]
            vols = [b[4] for b in bars]

            z_item, s_item = evaluate_stock(code, name, opens, closes, lows, vols, inst_map.get(code))
            if z_item:
                zhu_lin_picks.append(z_item)
            if s_item:
                sarah_picks.append(s_item)

            time.sleep(0.12)
        except Exception as e:
            if not diag_notes:
                diag_notes.append(f"Stooq:{str(e)[:30]}")
            continue

    # 3. 若有抓到 TWSE 全市場日收盤，額外補充全市場爆量強勢收紅股（補足觀察清單外的黑馬）
    if twse_daily_list:
        for r in twse_daily_list:
            code = str(r.get("Code", "")).strip()
            name = str(r.get("Name", "")).strip()
            if code in seen_codes or not (len(code) == 4 and code.isdigit() and not code.startswith("00")):
                continue
            o_val = safe_float(r.get("OpeningPrice"))
            c_val = safe_float(r.get("ClosingPrice"))
            chg_val = safe_float(r.get("Change"))
            v_lots = safe_int(r.get("TradeVolume")) // 1000
            prev_c = c_val - chg_val
            if o_val > 0 and c_val > o_val and chg_val > 0 and v_lots >= 5000 and prev_c > 0:
                pct = round((chg_val / prev_c) * 100, 2)
                inst_lots = inst_map.get(code, 0)
                if pct >= 4.0 or inst_lots >= 1000:
                    scanned_count += 1
                    tags = ["TWSE全市場強勢掃描", f"成交{v_lots:,}張"]
                    if inst_lots >= 500:
                        tags.append(f"三大法人買超{inst_lots:,}張")
                    zhu_lin_picks.append({
                        "code": code, "name": name, "close": round(c_val, 2),
                        "pct": pct, "vol": v_lots, "ma5": round(c_val, 2), "ma20": round(prev_c, 2),
                        "tags": tags
                    })

    zhu_lin_picks.sort(key=lambda x: x["pct"], reverse=True)
    sarah_picks.sort(key=lambda x: x["pct"], reverse=True)

    status_summary = f"成功精算{scanned_count}檔" if scanned_count > 0 else f"異常:{';'.join(diag_notes)}"
    output = {
        "updated_at": f"{market_date} ({status_summary} · 更新 {now_tw.strftime('%H:%M')})",
        "zhu_lin_picks": zhu_lin_picks[:12],
        "sarah_picks": sarah_picks[:12]
    }

    with open("recommendations.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("完成產出 recommendations.json：", output["updated_at"])

if __name__ == "__main__":
    main()
