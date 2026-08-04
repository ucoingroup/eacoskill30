# -*- coding: utf-8 -*-
"""
EACO Daily Agent v5.1 - 每日自动运行，监控Solana链上EACO资产数据，模拟每日赚钱过程。
无需私钥，只读取链上公开数据。

v5.1 新增:
  - 8个Web赚钱策略(W01-W08): Upwork/Fiverr/UserTesting/Respondent/MTurk/Rev/Prolific/Honeygain
  - 双轨赚钱: Web法币收入 + Web3/EACO生态收入
  - 目标$600/天的多平台组合策略
  - 每日工作流时间表优化

v5.0 新增:
  - 每日赚钱模拟引擎：选择当日最优策略组合并模拟执行
  - 投资组合追踪：记录持仓变化和累计收益
  - 收益历史记录：JSON 文件持久化，每日追加
  - 双语每日行动计划：CN/EN 具体操作步骤
  - --test 离线模式：不依赖外部 API，使用模拟数据快速测试
  - 累计收益仪表盘：总收益、日收益率、策略胜率
  - 报告复制到 eaco-app 并推送 GitHub Pages 提示

v4.0 改进:
  - 修复导入兼容性（stdlib 模块顶层导入，requests 可选）
  - --quiet / --json-only CLI 标志（cron 友好）
  - 报告自动复制到 eaco-app 目录
  - 主函数 try/except 保护，退出码规范化

数据源:
  - Gate.io API: SOL/USDT, USDC 价格
  - PublicNode Solana RPC: EACO链上数据
  - GeckoTerminal API: EACO DEX 价格（备用）
  - DexScreener / Jupiter Price API（海外备用）

Author: EACO Agent
Date: 2026-08-04
"""
import json, datetime, os, sys, time, math, ssl, urllib.request, urllib.error

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    requests = None  # type: ignore
    HAS_REQUESTS = False

# ===== CONFIG =====
EACO_MINT = "DqfoyZH96RnvZusSp3Cdncjpyp3C74ZmJzGhjmHnDHRH"
SOL_MINT = "So11111111111111111111111111111111111111112"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
ECNH_MINT = "7GQnqthWKa5v2GqXYWhmgWZY5mCRrniwK3Xuinm9GKw5"

# Meteora DLMM pools
METEORA_E_USDT_POOL = "6ZfCi3qzhgDN1ygHVYXvfsfrwz8ZhQ7hD5mJtjeuUDyE"
METEORA_E_SOL_POOL = "GsDB4iKELP7KDVjn5ZcHsJhWRY8J3HqTxvE86zyDhV34"

# 数据源
GATEIO_API = "https://api.gateio.ws/api/v4/spot/tickers"
SOLANA_RPC = "https://solana-rpc.publicnode.com"
GECKO_TERMINAL_API = "https://api.geckoterminal.com/api/v2/networks/solana/tokens/" + EACO_MINT + "/pools"

# 海外备用源
DEXSCREENER_API = "https://api.dexscreener.com/latest/dex/tokens/" + EACO_MINT
JUP_PRICE_API = "https://price.jup.ag/v6/price?ids="

# Output
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_FILE = os.path.join(OUTPUT_DIR, "eaco_daily_report.json")
HTML_REPORT = os.path.join(OUTPUT_DIR, "eaco_daily_report.html")
LOG_FILE = os.path.join(OUTPUT_DIR, "eaco_agent.log")
PORTFOLIO_FILE = os.path.join(OUTPUT_DIR, "eaco_portfolio.json")
HISTORY_FILE = os.path.join(OUTPUT_DIR, "eaco_earning_history.json")

# EACO 链上已知信息
EACO_TOTAL_SUPPLY = 1348368645.63
EACO_DECIMALS = 9

# 价格预警阈值
PRICE_ALERT_THRESHOLD_PCT = 10.0  # 10% 变动触发预警

# SSL context
if not HAS_REQUESTS:
    SSL_CTX = ssl.create_default_context()
    SSL_CTX.check_hostname = False
    SSL_CTX.verify_mode = ssl.CERT_NONE

def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def fetch_json(url, timeout=15, method="GET", body=None):
    """Fetch JSON from URL with fallback to urllib."""
    if HAS_REQUESTS and requests is not None:
        try:
            if method == "GET":
                resp = requests.get(url, timeout=timeout, headers={"User-Agent": "EACO-Agent/4.0", "Accept": "application/json"}, verify=False)
            else:
                resp = requests.post(url, json=body, timeout=timeout, headers={"Content-Type": "application/json", "User-Agent": "EACO-Agent/4.0"}, verify=False)
            return resp.json()
        except Exception as e:
            log(f"  fetch failed: {url[:80]}... -> {str(e)[:100]}")
            return None
    # Fallback to stdlib urllib
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "EACO-Agent/4.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log(f"  fetch failed: {url[:80]}... -> {e}")
        return None

def rpc_call(method, params):
    """Call Solana JSON-RPC via PublicNode."""
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        if HAS_REQUESTS and requests is not None:
            resp = requests.post(SOLANA_RPC, json=body, timeout=20,
                               headers={"Content-Type": "application/json", "User-Agent": "EACO-Agent/4.0"},
                               verify=False)
            data = resp.json()
        else:
            req = urllib.request.Request(SOLANA_RPC, data=json.dumps(body).encode("utf-8"),
                                         headers={"Content-Type": "application/json", "User-Agent": "EACO-Agent/4.0"},
                                         method="POST")
            with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        if "error" in data:
            log(f"  RPC error ({method}): {data['error']}")
            return None
        return data.get("result")
    except Exception as e:
        log(f"  RPC call failed ({method}): {str(e)[:100]}")
        return None

# ===== DATA FETCHING =====

def get_sol_price_gateio():
    """Get SOL price from Gate.io."""
    data = fetch_json(f"{GATEIO_API}?currency_pair=SOL_USDT", timeout=10)
    if data and isinstance(data, list) and len(data) > 0:
        price = float(data[0].get("last", 0) or 0)
        vol24h = float(data[0].get("quote_volume", 0) or 0)
        high = float(data[0].get("high_24h", 0) or 0)
        low = float(data[0].get("low_24h", 0) or 0)
        change = float(data[0].get("change_percentage", 0) or 0)
        return {"price": price, "vol_24h": vol24h, "high_24h": high, "low_24h": low, "change_24h": change}
    return None

def get_usdc_price_gateio():
    """Get USDC price from Gate.io."""
    data = fetch_json(f"{GATEIO_API}?currency_pair=USDC_USDT", timeout=10)
    if data and isinstance(data, list) and len(data) > 0:
        return float(data[0].get("last", 1.0) or 1.0)
    return 1.0

def get_eaco_onchain_data():
    """Get EACO on-chain data via PublicNode Solana RPC."""
    result = {"supply": EACO_TOTAL_SUPPLY, "slot": 0, "holders_estimated": 0, "epoch": 0}

    # Get token supply
    supply_result = rpc_call("getTokenSupply", [EACO_MINT])
    if supply_result and "value" in supply_result:
        supply_str = supply_result["value"].get("uiAmountString", "0")
        result["supply"] = float(supply_str)
        result["decimals"] = supply_result["value"].get("decimals", 9)
        result["slot"] = supply_result.get("context", {}).get("slot", 0)
        log(f"  EACO Supply (on-chain): {result['supply']:,.2f}")
    else:
        log(f"  Using cached supply: {result['supply']:,.2f}")

    # Get epoch info
    epoch_info = rpc_call("getEpochInfo", [])
    if epoch_info:
        result["slot"] = epoch_info.get("absoluteSlot", result["slot"])
        result["epoch"] = epoch_info.get("epoch", 0)
        log(f"  Current slot: {result['slot']}, epoch: {result['epoch']}")

    # Get token accounts count (holder estimate)
    accounts_result = rpc_call("getTokenAccountBalance", [EACO_MINT])
    # Try getProgramAccounts for holder count (approximate)
    holder_result = rpc_call("getProgramAccounts", [
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        {"encoding": "jsonParsed", "filters": [{"dataSize": 165}, {"memcmp": {"offset": 0, "bytes": EACO_MINT}}]}
    ])
    if holder_result and isinstance(holder_result, list):
        result["holders_estimated"] = len(holder_result)
        log(f"  EACO Token accounts (holders): {result['holders_estimated']}")

    return result

def get_meteora_pool_data():
    """Read Meteora DLMM pool on-chain data."""
    pools = {}
    for name, pool_addr in [("E-USDT", METEORA_E_USDT_POOL), ("E-SOL", METEORA_E_SOL_POOL)]:
        log(f"  Fetching Meteora pool {name} ({pool_addr[:12]}...)")
        account_info = rpc_call("getAccountInfo", [pool_addr, {"encoding": "base64"}])
        if account_info:
            pools[name] = {
                "address": pool_addr,
                "exists": True,
                "data_size": len(account_info.get("value", {}).get("data", [b""])[0]) if account_info.get("value") else 0,
            }
            log(f"    Pool {name}: exists, data retrieved")
        else:
            pools[name] = {"address": pool_addr, "exists": False, "data_size": 0}
            log(f"    Pool {name}: not found or error")
    return pools

def get_eaco_price_geckoterminal():
    """Try GeckoTerminal API for EACO price."""
    data = fetch_json(GECKO_TERMINAL_API, timeout=12)
    if not data or "data" not in data:
        return 0, 0, 0, []

    pools = data.get("data", [])
    if not pools:
        return 0, 0, 0, []

    best_price = 0.0
    total_liq = 0.0
    total_vol = 0.0
    interesting = []

    for p in pools:
        attrs = p.get("attributes", {})
        rel = p.get("relationships", {})

        price_usd_str = attrs.get("base_token_price_usd", "0")
        liq_str = attrs.get("reserve_in_usd", "0")
        vol_str = attrs.get("volume_usd", {}).get("h24", "0")
        txns = attrs.get("transactions", {}).get("h24", {})
        change_str = attrs.get("price_change_percentage", {}).get("h24", "0")

        try:
            price_usd = float(price_usd_str)
        except (ValueError, TypeError):
            price_usd = 0.0
        try:
            liq = float(liq_str)
        except (ValueError, TypeError):
            liq = 0.0
        try:
            vol = float(vol_str)
        except (ValueError, TypeError):
            vol = 0.0
        try:
            change = float(change_str)
        except (ValueError, TypeError):
            change = 0.0

        dex_id = rel.get("dex", {}).get("data", {}).get("id", "?")

        if price_usd > 0 and best_price == 0:
            best_price = price_usd
        total_liq += liq
        total_vol += vol

        interesting.append({
            "dex": dex_id,
            "pair": p.get("id", "?")[:12] + "...",
            "base": "EACO",
            "quote": rel.get("quote_token", {}).get("data", {}).get("id", "?"),
            "price_usd": price_usd,
            "liquidity_usd": liq,
            "volume_24h": vol,
            "buys_24h": int(txns.get("buys", 0)) if txns else 0,
            "sells_24h": int(txns.get("sells", 0)) if txns else 0,
            "change_24h": change,
        })

    interesting.sort(key=lambda x: x["liquidity_usd"], reverse=True)
    if best_price == 0 and interesting:
        best_price = interesting[0]["price_usd"]

    return best_price, total_liq, total_vol, interesting

def get_eaco_price_dexscreener():
    """Try DexScreener for EACO price (海外，可能不可达)."""
    data = fetch_json(DEXSCREENER_API, timeout=12)
    if not data or "pairs" not in data:
        return 0, 0, 0, []

    pairs = data.get("pairs", [])
    interesting = []
    best_price = 0.0
    total_liq = 0.0
    total_vol = 0.0

    for p in pairs:
        dex = p.get("dexId", "?")
        if dex.lower() not in ["raydium", "orca", "meteora", "pumpswap"]:
            continue
        price_usd = float(p.get("priceUsd", 0) or 0)
        liq = float(p.get("liquidity", {}).get("usd", 0) or 0)
        vol = float(p.get("volume", {}).get("h24", 0) or 0)
        txns = p.get("txns", {}).get("h24", {})
        change = float(p.get("priceChange", {}).get("h24", 0) or 0)

        if price_usd > 0 and best_price == 0:
            best_price = price_usd
        total_liq += liq
        total_vol += vol

        interesting.append({
            "dex": dex,
            "pair": p.get("pairAddress", "?")[:12] + "...",
            "base": p.get("baseToken", {}).get("symbol", "?"),
            "quote": p.get("quoteToken", {}).get("symbol", "?"),
            "price_usd": price_usd,
            "liquidity_usd": liq,
            "volume_24h": vol,
            "buys_24h": txns.get("buys", 0) if txns else 0,
            "sells_24h": txns.get("sells", 0) if txns else 0,
            "change_24h": change,
        })

    interesting.sort(key=lambda x: x["liquidity_usd"], reverse=True)
    if best_price == 0 and interesting:
        best_price = interesting[0]["price_usd"]

    return best_price, total_liq, total_vol, interesting

def get_eaco_price_jupiter():
    """Try Jupiter Price API."""
    data = fetch_json(JUP_PRICE_API + EACO_MINT, timeout=12)
    if data and "data" in data:
        price_data = data["data"].get(EACO_MINT, {})
        if price_data and "price" in price_data:
            return float(price_data["price"])
    return 0.0

def estimate_eaco_price(sol_price, onchain_data):
    """
    Estimate EACO price using multiple sources.
    Priority: GeckoTerminal > DexScreener > Jupiter > Fallback
    """
    # Try GeckoTerminal first (more likely reachable from China)
    gt_price, gt_liq, gt_vol, gt_pairs = get_eaco_price_geckoterminal()
    if gt_price and gt_price > 0:
        log(f"  EACO price (GeckoTerminal): ${gt_price}")
        return gt_price, gt_liq, gt_vol, gt_pairs, "GeckoTerminal"

    # Try DexScreener
    ds_price, ds_liq, ds_vol, ds_pairs = get_eaco_price_dexscreener()
    if ds_price and ds_price > 0:
        log(f"  EACO price (DexScreener): ${ds_price}")
        return ds_price, ds_liq, ds_vol, ds_pairs, "DexScreener"

    # Try Jupiter
    jup_price = get_eaco_price_jupiter()
    if jup_price and jup_price > 0:
        log(f"  EACO price (Jupiter): ${jup_price}")
        return jup_price, 0.0, 0.0, [], "Jupiter"

    # Fallback: use estimated price
    estimated = 0.001
    log(f"  EACO price: using estimate ${estimated} (all APIs unreachable)")
    log(f"  For real-time price: https://dexscreener.com/solana/{EACO_MINT}")
    return estimated, 0.0, 0.0, [], "Estimated (API unreachable)"

# ===== PORTFOLIO & SIMULATION ENGINE (v5.0) =====

def load_portfolio():
    """Load portfolio state from file, or initialize if not exists."""
    default_portfolio = {
        "initial_capital_sol": 10.0,
        "initial_capital_usd": 700.0,
        "current_sol": 10.0,
        "current_eaco": 0.0,
        "current_usd": 0.0,
        "total_earned_usd": 0.0,
        "total_earned_eaco": 0.0,
        "total_earned_sol": 0.0,
        "days_active": 0,
        "last_run": None,
        "strategy_results": {},  # {"S01": {"runs": 5, "total_usd": 12.5, "wins": 4}}
        "daily_history": [],     # [{"date": "2026-08-04", "earned_usd": 2.5, ...}]
    }
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                p = json.load(f)
            # Merge with defaults to handle new fields
            for k, v in default_portfolio.items():
                if k not in p:
                    p[k] = v
            return p
        except Exception as e:
            log(f"  Warning: could not load portfolio, using default: {e}")
    return default_portfolio


def save_portfolio(portfolio):
    """Save portfolio state to file."""
    try:
        with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
            json.dump(portfolio, f, ensure_ascii=False, indent=2)
        log(f"  Portfolio saved to {PORTFOLIO_FILE}")
    except Exception as e:
        log(f"  Warning: could not save portfolio: {e}")


def load_history():
    """Load earning history from file."""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"records": [], "cumulative_usd": 0.0, "cumulative_eaco": 0.0, "total_days": 0}


def save_history(history):
    """Save earning history to file."""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        log(f"  History saved to {HISTORY_FILE}")
    except Exception as e:
        log(f"  Warning: could not save history: {e}")


def select_daily_strategies(sol_price, eaco_price, total_liq, sol_change_24h):
    """
    Select today's optimal strategy mix based on market conditions.
    Returns list of (strategy, allocated_sol, expected_apr_pct, reason_cn, reason_en).
    """
    selected = []
    
    # Market condition assessment
    volatile = abs(sol_change_24h) > 5
    high_liq = total_liq > 50000
    bullish = sol_change_24h > 2
    
    # 1. Always include AI content factory (no capital needed, pure earning)
    for s in STRATEGIES:
        if s["id"] == "S11":
            selected.append((s, 0, s["daily_apr_range"], 
                "AI内容工厂零成本24/7产出，每日必选",
                "AI content factory zero-cost 24/7 output, daily must-run"))
            break
    
    # 2. Translation rewards (no capital, no risk)
    for s in STRATEGIES:
        if s["id"] == "S14":
            selected.append((s, 0, s["daily_apr_range"],
                "多语言翻译零风险赚EACO，每日必做",
                "Translation rewards zero-risk EACO earning, daily must-do"))
            break
    
    # 3. Community promo (no capital, no risk)
    for s in STRATEGIES:
        if s["id"] == "S15":
            selected.append((s, 0, s["daily_apr_range"],
                "社区推广零成本赚佣金，每日必做",
                "Community promo zero-cost commission, daily must-do"))
            break
    
    # 4. DePIN node (low capital, auto)
    for s in STRATEGIES:
        if s["id"] == "S10":
            selected.append((s, 0, s["daily_apr_range"],
                "DePIN节点自动运行，被动收入",
                "DePIN node auto-running, passive income"))
            break
    
    # 5. If volatile, add grid trading
    if volatile:
        for s in STRATEGIES:
            if s["id"] == "S05":
                selected.append((s, 3, s["daily_apr_range"],
                    "市场波动大，AI网格交易低买高卖",
                    "High volatility, AI grid trading buy low sell high"))
                break
    
    # 6. If bullish, add staking
    if bullish:
        for s in STRATEGIES:
            if s["id"] == "S04":
                selected.append((s, 3, s["daily_apr_range"],
                    "SOL上涨趋势，质押EACO吃生态红利",
                    "SOL uptrend, stake EACO for ecosystem dividends"))
                break
    
    # 7. Always add cross-DEX arbitrage if liquidity exists
    if high_liq:
        for s in STRATEGIES:
            if s["id"] == "S03":
                selected.append((s, 2, s["daily_apr_range"],
                    "流动性充足，跨DEX套利空间大",
                    "Sufficient liquidity, cross-DEX arbitrage opportunity"))
                break
    else:
        for s in STRATEGIES:
            if s["id"] == "S06":
                selected.append((s, 2, s["daily_apr_range"],
                    "AI自动套利，小额试探",
                    "AI auto-arbitrage, small position probe"))
                break
    
    return selected


def simulate_daily_earning(portfolio, selected, sol_price, eaco_price):
    """
    Simulate today's earning based on selected strategies.
    Returns daily_result dict.
    """
    import random
    
    total_earned_usd = 0.0
    total_earned_eaco = 0.0
    total_earned_sol = 0.0
    strategy_details = []
    
    for strat, allocated_sol, apr_range, reason_cn, reason_en in selected:
        low_apr, high_apr = apr_range
        # Use mid-range with some randomness for realism
        base_apr = (low_apr + high_apr) / 2
        variance = (high_apr - low_apr) / 4
        actual_apr = base_apr + random.uniform(-variance, variance)
        actual_apr = max(low_apr * 0.5, min(high_apr * 1.2, actual_apr))
        
        # Capital in USD
        capital_usd = allocated_sol * sol_price
        
        # For zero-capital strategies, use a base effort value
        if allocated_sol == 0:
            capital_usd = sol_price * 1.0  # Assume 1 SOL equivalent effort
        
        earned_usd = capital_usd * actual_apr / 100
        earned_eaco = earned_usd / eaco_price if eaco_price > 0 else 0
        earned_sol = earned_usd / sol_price if sol_price > 0 else 0
        
        total_earned_usd += earned_usd
        total_earned_eaco += earned_eaco
        total_earned_sol += earned_sol
        
        # Track strategy performance
        sid = strat["id"]
        if sid not in portfolio["strategy_results"]:
            portfolio["strategy_results"][sid] = {"runs": 0, "total_usd": 0.0, "wins": 0}
        portfolio["strategy_results"][sid]["runs"] += 1
        portfolio["strategy_results"][sid]["total_usd"] += earned_usd
        if earned_usd > 0:
            portfolio["strategy_results"][sid]["wins"] += 1
        
        strategy_details.append({
            "id": sid,
            "name_cn": strat["name_cn"],
            "name_en": strat["name_en"],
            "skill_ref": strat["skill_ref"],
            "allocated_sol": allocated_sol,
            "actual_apr_pct": round(actual_apr, 3),
            "earned_usd": round(earned_usd, 4),
            "earned_eaco": round(earned_eaco, 0),
            "earned_sol": round(earned_sol, 6),
            "reason_cn": reason_cn,
            "reason_en": reason_en,
        })
    
    # Update portfolio
    portfolio["current_sol"] += total_earned_sol
    portfolio["current_eaco"] += total_earned_eaco
    portfolio["current_usd"] += total_earned_usd
    portfolio["total_earned_usd"] += total_earned_usd
    portfolio["total_earned_eaco"] += total_earned_eaco
    portfolio["total_earned_sol"] += total_earned_sol
    portfolio["days_active"] += 1
    
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d")
    portfolio["last_run"] = today
    
    daily_record = {
        "date": today,
        "sol_price": round(sol_price, 2),
        "eaco_price": eaco_price,
        "strategies_run": len(selected),
        "earned_usd": round(total_earned_usd, 4),
        "earned_eaco": round(total_earned_eaco, 0),
        "earned_sol": round(total_earned_sol, 6),
        "portfolio_sol_after": round(portfolio["current_sol"], 4),
        "portfolio_eaco_after": round(portfolio["current_eaco"], 0),
        "portfolio_usd_after": round(portfolio["current_usd"], 2),
        "details": strategy_details,
    }
    
    portfolio["daily_history"].append(daily_record)
    # Keep only last 365 days
    if len(portfolio["daily_history"]) > 365:
        portfolio["daily_history"] = portfolio["daily_history"][-365:]
    
    return daily_record


def generate_action_plan(selected, sol_price, eaco_price):
    """Generate bilingual daily action plan with concrete steps."""
    actions_cn = []
    actions_en = []
    
    for strat, allocated_sol, _, reason_cn, reason_en in selected:
        sid = strat["id"]
        
        # Generate concrete steps per strategy
        if sid == "S11":  # AI Content Factory
            steps_cn = [
                f"启动AI Agent，生成3篇EACO相关文章/视频",
                f"自动翻译内容到英语、日语、韩语",
                f"发布到社区，按阅读量获EACO奖励",
            ]
            steps_en = [
                f"Start AI Agent, generate 3 EACO-related articles/videos",
                f"Auto-translate content to English, Japanese, Korean",
                f"Publish to community, earn EACO per view",
            ]
        elif sid == "S14":  # Translation
            steps_cn = [
                f"选择EACO白皮书章节，翻译为目标语言",
                f"提交翻译到社区审核",
                f"审核通过后按字数获EACO奖励",
            ]
            steps_en = [
                f"Select EACO whitepaper section, translate to target language",
                f"Submit translation for community review",
                f"Earn EACO per word after approval",
            ]
        elif sid == "S15":  # Community promo
            steps_cn = [
                f"在社交媒体分享EACO最新动态",
                f"邀请新用户加入Telegram群组",
                f"按邀请人数获EACO佣金",
            ]
            steps_en = [
                f"Share EACO updates on social media",
                f"Invite new users to Telegram groups",
                f"Earn EACO commission per invite",
            ]
        elif sid == "S10":  # DePIN
            steps_cn = [
                f"检查DePIN节点运行状态",
                f"确认昨日贡献量达标",
                f"领取EACO节点激励",
            ]
            steps_en = [
                f"Check DePIN node status",
                f"Verify yesterday's contribution met target",
                f"Claim EACO node incentive",
            ]
        elif sid == "S05":  # Grid trading
            steps_cn = [
                f"分配 {allocated_sol} SOL 到AI网格交易",
                f"设置网格区间（根据波动率自动计算）",
                f"启动网格机器人24h运行",
            ]
            steps_en = [
                f"Allocate {allocated_sol} SOL to AI grid trading",
                f"Set grid range (auto-calculated from volatility)",
                f"Start grid bot for 24h operation",
            ]
        elif sid == "S04":  # Staking
            steps_cn = [
                f"质押 {allocated_sol} SOL 等值EACO",
                f"确认质押锁定期",
                f"开始每日领取生态分红",
            ]
            steps_en = [
                f"Stake {allocated_sol} SOL worth of EACO",
                f"Confirm staking lock period",
                f"Start daily ecosystem dividend collection",
            ]
        elif sid in ("S03", "S06"):  # Arbitrage
            steps_cn = [
                f"分配 {allocated_sol} SOL 到套利资金池",
                f"监控Raydium/Meteora/Orca价差",
                f"价差>0.5%时自动执行套利",
            ]
            steps_en = [
                f"Allocate {allocated_sol} SOL to arbitrage pool",
                f"Monitor Raydium/Meteora/Orca price spread",
                f"Auto-execute when spread > 0.5%",
            ]
        else:
            steps_cn = [f"执行 {strat['name_cn']}", f"参考 skill: {strat['skill_ref']}"]
            steps_en = [f"Execute {strat['name_en']}", f"Refer to skill: {strat['skill_ref']}"]
        
        actions_cn.append({
            "id": sid,
            "name": strat["name_cn"],
            "reason": reason_cn,
            "steps": steps_cn,
            "allocated_sol": allocated_sol,
        })
        actions_en.append({
            "id": sid,
            "name": strat["name_en"],
            "reason": reason_en,
            "steps": steps_en,
            "allocated_sol": allocated_sol,
        })
    
    return actions_cn, actions_en


STRATEGIES = [
    {
        "id": "S01", "name_cn": "Raydium流动性挖矿", "name_en": "Raydium Liquidity Mining",
        "skill_ref": "eaco-skill02",
        "desc": "Raydium添加EACO-SOL LP，赚0.25%手续费分成+LP奖励",
        "desc_en": "Add EACO-SOL LP on Raydium, earn 0.25% fee share + LP rewards",
        "apy_estimate": "30-80%", "risk_cn": "中（无常损失）", "risk_en": "Medium (impermanent loss)",
        "capital_type": "LP资金 (EACO+SOL)", "needs_private_key": True, "needs_capital": True,
        "daily_apr_range": (0.08, 0.22), "difficulty": "2", "auto_executable": False,
    },
    {
        "id": "S02", "name_cn": "Meteora DLMM集中流动性", "name_en": "Meteora DLMM Concentrated Liquidity",
        "skill_ref": "eaco-skill03",
        "desc": "Meteora DLMM池集中流动性做市，资金效率3-5倍",
        "desc_en": "Concentrated liquidity MM on Meteora DLMM, 3-5x capital efficiency",
        "apy_estimate": "50-150%", "risk_cn": "中高（集中风险）", "risk_en": "Med-High (concentration risk)",
        "capital_type": "LP资金 (EACO+USDT)", "needs_private_key": True, "needs_capital": True,
        "daily_apr_range": (0.14, 0.41), "difficulty": "3", "auto_executable": False,
    },
    {
        "id": "S03", "name_cn": "跨DEX价差套利", "name_en": "Cross-DEX Spread Arbitrage",
        "skill_ref": "eaco-skill07",
        "desc": "监控Raydium/Orca/Meteora间EACO价差，自动搬砖",
        "desc_en": "Monitor EACO price gaps across Raydium/Orca/Meteora, auto-arbitrage",
        "apy_estimate": "20-60%", "risk_cn": "低（瞬时套利）", "risk_en": "Low (instant arbitrage)",
        "capital_type": "交易资金 (SOL/USDT)", "needs_private_key": True, "needs_capital": True,
        "daily_apr_range": (0.05, 0.16), "difficulty": "3", "auto_executable": True,
    },
    {
        "id": "S04", "name_cn": "EACO质押生息", "name_en": "EACO Staking Yield",
        "skill_ref": "eaco-skill05",
        "desc": "质押EACO获取生态分红和治理权",
        "desc_en": "Stake EACO for ecosystem dividends and governance rights",
        "apy_estimate": "10-25%", "risk_cn": "低", "risk_en": "Low",
        "capital_type": "EACO持仓", "needs_private_key": True, "needs_capital": True,
        "daily_apr_range": (0.03, 0.07), "difficulty": "1", "auto_executable": True,
    },
    {
        "id": "S05", "name_cn": "AI量化网格交易", "name_en": "AI Grid Trading Bot",
        "skill_ref": "eaco-skill04",
        "desc": "AI分析波动率动态调网格，低买高卖EACO",
        "desc_en": "AI-driven grid trading with dynamic volatility-based parameters",
        "apy_estimate": "40-120%", "risk_cn": "中（震荡市优）", "risk_en": "Medium (best in range-bound)",
        "capital_type": "交易资金 (USDT)", "needs_private_key": True, "needs_capital": True,
        "daily_apr_range": (0.11, 0.33), "difficulty": "3", "auto_executable": True,
    },
    {
        "id": "S06", "name_cn": "AI跨DEX自动套利", "name_en": "AI Auto-Arbitrage Bot",
        "skill_ref": "eaco-skill30",
        "desc": "AI实时监控多DEX价差，自动执行跨平台套利",
        "desc_en": "AI real-time multi-DEX spread detection and auto-execution",
        "apy_estimate": "30-90%", "risk_cn": "低-中", "risk_en": "Low-Medium",
        "capital_type": "交易资金 (SOL)", "needs_private_key": True, "needs_capital": True,
        "daily_apr_range": (0.08, 0.25), "difficulty": "3", "auto_executable": True,
    },
    {
        "id": "S07", "name_cn": "RWA新能源资产碎片投资", "name_en": "RWA Renewable Energy Investment",
        "skill_ref": "eaco-skill22",
        "desc": "用EACO认购代币化光伏电站份额，每日领发电收益",
        "desc_en": "Tokenized solar farm shares via EACO, daily energy yield",
        "apy_estimate": "8-15%", "risk_cn": "低（实体支撑）", "risk_en": "Low (backed by assets)",
        "capital_type": "EACO持仓", "needs_private_key": True, "needs_capital": True,
        "daily_apr_range": (0.02, 0.04), "difficulty": "2", "auto_executable": False,
    },
    {
        "id": "S08", "name_cn": "EACO-USDT稳定币对做市", "name_en": "EACO-USDT Stablecoin Pair MM",
        "skill_ref": "eaco-skill08",
        "desc": "Meteora添加EACO-USDT流动性，降低无常损失",
        "desc_en": "Add EACO-USDT liquidity on Meteora, reduced impermanent loss",
        "apy_estimate": "25-60%", "risk_cn": "中低", "risk_en": "Med-Low",
        "capital_type": "LP资金 (EACO+USDT)", "needs_private_key": True, "needs_capital": True,
        "daily_apr_range": (0.07, 0.16), "difficulty": "2", "auto_executable": False,
    },
    {
        "id": "S09", "name_cn": "EACO LP合伙人锁仓分红", "name_en": "EACO LP Partner Lock-up Dividends",
        "skill_ref": "eaco-skill27",
        "desc": "1-100 SOL档位LP计划，锁仓90天享手续费分红",
        "desc_en": "1-100 SOL tier LP program, 90-day lock for fee dividends",
        "apy_estimate": "20-50%", "risk_cn": "中（锁仓风险）", "risk_en": "Medium (lock-up risk)",
        "capital_type": "SOL", "needs_private_key": True, "needs_capital": True,
        "daily_apr_range": (0.05, 0.14), "difficulty": "2", "auto_executable": False,
    },
    {
        "id": "S10", "name_cn": "DePIN节点运行激励", "name_en": "DePIN Node Operation Incentive",
        "skill_ref": "eaco-skill11",
        "desc": "部署DePIN节点共享算力/带宽，获EACO激励",
        "desc_en": "Run DePIN node, share compute/bandwidth, earn EACO",
        "apy_estimate": "15-35%", "risk_cn": "低", "risk_en": "Low",
        "capital_type": "硬件/带宽", "needs_private_key": False, "needs_capital": False,
        "daily_apr_range": (0.04, 0.10), "difficulty": "2", "auto_executable": True,
    },
    # === NEW in v3.0 ===
    {
        "id": "S11", "name_cn": "AI内容工厂自动赚钱", "name_en": "AI Content Factory Auto-Earning",
        "skill_ref": "eaco-skill01",
        "desc": "AI Agent自动生成文章/视频/翻译，EACO结算，24/7",
        "desc_en": "AI Agent auto-generates content, EACO payment, 24/7",
        "apy_estimate": "50-200%", "risk_cn": "低", "risk_en": "Low",
        "capital_type": "AI算力", "needs_private_key": False, "needs_capital": False,
        "daily_apr_range": (0.14, 0.55), "difficulty": "2", "auto_executable": True,
    },
    {
        "id": "S12", "name_cn": "NFT生态铸造交易", "name_en": "Eco NFT Mint & Trade",
        "skill_ref": "eaco-skill10",
        "desc": "铸造环保NFT，EACO定价，Solana市场交易",
        "desc_en": "Mint eco-NFTs, EACO pricing, trade on Solana",
        "apy_estimate": "30-100%", "risk_cn": "中（市场波动）", "risk_en": "Medium (market volatility)",
        "capital_type": "EACO持仓", "needs_private_key": True, "needs_capital": True,
        "daily_apr_range": (0.08, 0.27), "difficulty": "2", "auto_executable": False,
    },
    {
        "id": "S13", "name_cn": "碳信用交易", "name_en": "Carbon Credit Trading",
        "skill_ref": "eaco-skill07",
        "desc": "链上碳减排NFT，EACO计价交易碳信用",
        "desc_en": "On-chain carbon NFTs, trade carbon credits in EACO",
        "apy_estimate": "15-40%", "risk_cn": "低", "risk_en": "Low",
        "capital_type": "EACO持仓", "needs_private_key": True, "needs_capital": True,
        "daily_apr_range": (0.04, 0.11), "difficulty": "2", "auto_executable": False,
    },
    {
        "id": "S14", "name_cn": "多语言翻译奖励", "name_en": "Multilingual Translation Rewards",
        "skill_ref": "eaco-skill20",
        "desc": "翻译EACO文档到7种语言，按字数获EACO奖励",
        "desc_en": "Translate EACO docs to 7 languages, earn EACO per word",
        "apy_estimate": "20-50%", "risk_cn": "无", "risk_en": "None",
        "capital_type": "劳动力", "needs_private_key": False, "needs_capital": False,
        "daily_apr_range": (0.05, 0.14), "difficulty": "1", "auto_executable": True,
    },
    {
        "id": "S15", "name_cn": "全球社区推广佣金", "name_en": "Global Community Promo Commission",
        "skill_ref": "eaco-skill30",
        "desc": "推广EACO，邀请新用户，获EACO佣金奖励",
        "desc_en": "Promote EACO, invite users, earn EACO commission",
        "apy_estimate": "10-60%", "risk_cn": "无", "risk_en": "None",
        "capital_type": "社交网络", "needs_private_key": False, "needs_capital": False,
        "daily_apr_range": (0.03, 0.16), "difficulty": "1", "auto_executable": True,
    },
    # v5.1: Web earning strategies (daily payment platforms)
    {
        "id": "W01", "name_cn": "Upwork自由职业", "name_en": "Upwork Freelance",
        "skill_ref": "eaco-skill01",
        "desc": "Upwork接单：编程/设计/写作/翻译，时薪$50-150",
        "desc_en": "Upwork projects: coding/design/writing/translation, $50-150/h",
        "apy_estimate": "200-500%", "risk_cn": "无", "risk_en": "None",
        "capital_type": "技能+时间", "needs_private_key": False, "needs_capital": False,
        "daily_apr_range": (0.5, 3.0), "difficulty": "2", "auto_executable": False,
    },
    {
        "id": "W02", "name_cn": "Fiverr Gig经济", "name_en": "Fiverr Gig Economy",
        "skill_ref": "eaco-skill01",
        "desc": "Fiverr出售服务：设计/写作/AI工具，$5-500/gig",
        "desc_en": "Fiverr services: design/writing/AI tools, $5-500/gig",
        "apy_estimate": "100-300%", "risk_cn": "无", "risk_en": "None",
        "capital_type": "技能+时间", "needs_private_key": False, "needs_capital": False,
        "daily_apr_range": (0.3, 2.0), "difficulty": "1", "auto_executable": False,
    },
    {
        "id": "W03", "name_cn": "UserTesting网站测试", "name_en": "UserTesting Website Testing",
        "skill_ref": "eaco-skill11",
        "desc": "测试网站/APP，20分钟$10，访谈$30-60",
        "desc_en": "Test websites/apps, $10/20min, interviews $30-60",
        "apy_estimate": "50-150%", "risk_cn": "无", "risk_en": "None",
        "capital_type": "时间", "needs_private_key": False, "needs_capital": False,
        "daily_apr_range": (0.2, 1.0), "difficulty": "1", "auto_executable": True,
    },
    {
        "id": "W04", "name_cn": "Respondent B2B访谈", "name_en": "Respondent B2B Research",
        "skill_ref": "eaco-skill01",
        "desc": "B2B研究访谈，时薪$50-200，按职业匹配",
        "desc_en": "B2B research interviews, $50-200/h, matched by profession",
        "apy_estimate": "300-1000%", "risk_cn": "无", "risk_en": "None",
        "capital_type": "职业背景+时间", "needs_private_key": False, "needs_capital": False,
        "daily_apr_range": (1.0, 5.0), "difficulty": "2", "auto_executable": False,
    },
    {
        "id": "W05", "name_cn": "MTurk微任务", "name_en": "MTurk Microtasks",
        "skill_ref": "eaco-skill11",
        "desc": "Amazon MTurk数据标注/分类/审核，多任务并行",
        "desc_en": "Amazon MTurk data labeling/classification/review, parallel tasks",
        "apy_estimate": "50-200%", "risk_cn": "无", "risk_en": "None",
        "capital_type": "时间", "needs_private_key": False, "needs_capital": False,
        "daily_apr_range": (0.15, 0.8), "difficulty": "1", "auto_executable": True,
    },
    {
        "id": "W06", "name_cn": "Rev音频转录", "name_en": "Rev Transcription",
        "skill_ref": "eaco-skill20",
        "desc": "音频转文字$0.30-1.10/min，需通过英语测试",
        "desc_en": "Audio to text $0.30-1.10/min, pass English test",
        "apy_estimate": "80-200%", "risk_cn": "无", "risk_en": "None",
        "capital_type": "英语+时间", "needs_private_key": False, "needs_capital": False,
        "daily_apr_range": (0.2, 1.0), "difficulty": "2", "auto_executable": False,
    },
    {
        "id": "W07", "name_cn": "Prolific学术研究", "name_en": "Prolific Academic Research",
        "skill_ref": "eaco-skill11",
        "desc": "参与大学研究问卷，时薪$8-15",
        "desc_en": "Participate in university research, $8-15/h",
        "apy_estimate": "40-100%", "risk_cn": "无", "risk_en": "None",
        "capital_type": "时间", "needs_private_key": False, "needs_capital": False,
        "daily_apr_range": (0.1, 0.5), "difficulty": "1", "auto_executable": True,
    },
    {
        "id": "W08", "name_cn": "Honeygain被动带宽", "name_en": "Honeygain Passive Bandwidth",
        "skill_ref": "eaco-skill11",
        "desc": "分享闲置带宽，24/7被动收入$1-5/天",
        "desc_en": "Share unused bandwidth, 24/7 passive $1-5/day",
        "apy_estimate": "10-30%", "risk_cn": "无", "risk_en": "None",
        "capital_type": "网络带宽", "needs_private_key": False, "needs_capital": False,
        "daily_apr_range": (0.01, 0.05), "difficulty": "1", "auto_executable": True,
    },
]

def calculate_daily_earnings(eaco_price_usd, sol_price_usd, total_liq_usd, vol_24h):
    """Calculate estimated daily earnings for 3 capital tiers across 15 strategies."""
    tiers = [
        {"name": "1 SOL", "sol": 1, "usd_equiv": sol_price_usd * 1},
        {"name": "10 SOL", "sol": 10, "usd_equiv": sol_price_usd * 10},
        {"name": "100 SOL", "sol": 100, "usd_equiv": sol_price_usd * 100},
    ]

    results = []
    for strat in STRATEGIES:
        low_apr, high_apr = strat["daily_apr_range"]
        strat_result = {
            "id": strat["id"],
            "name_cn": strat["name_cn"],
            "name_en": strat["name_en"],
            "skill_ref": strat["skill_ref"],
            "desc_cn": strat["desc"],
            "desc_en": strat["desc_en"],
            "apy_range": strat["apy_estimate"],
            "risk_cn": strat["risk_cn"],
            "risk_en": strat["risk_en"],
            "difficulty": strat["difficulty"],
            "auto_executable": strat["auto_executable"],
            "needs_key": strat["needs_private_key"],
            "needs_capital": strat["needs_capital"],
            "daily_estimates": []
        }

        for tier in tiers:
            capital_usd = tier["usd_equiv"]
            low_daily = capital_usd * low_apr / 100
            high_daily = capital_usd * high_apr / 100

            # Safe division
            low_eaco = low_daily / eaco_price_usd if eaco_price_usd and eaco_price_usd > 0 else 0
            high_eaco = high_daily / eaco_price_usd if eaco_price_usd and eaco_price_usd > 0 else 0
            low_sol = low_daily / sol_price_usd if sol_price_usd and sol_price_usd > 0 else 0
            high_sol = high_daily / sol_price_usd if sol_price_usd and sol_price_usd > 0 else 0

            strat_result["daily_estimates"].append({
                "tier": tier["name"],
                "capital_sol": tier["sol"],
                "capital_usd": round(capital_usd, 2),
                "low_daily_usd": round(low_daily, 2),
                "high_daily_usd": round(high_daily, 2),
                "low_daily_eaco": round(low_eaco, 0) if low_eaco < 100000 else round(low_eaco / 1000, 1),
                "high_daily_eaco": round(high_eaco, 0) if high_eaco < 100000 else round(high_eaco / 1000, 1),
                "low_daily_sol": round(low_sol, 4),
                "high_daily_sol": round(high_sol, 4),
                "low_daily_usdt": round(low_daily, 2),
                "high_daily_usdt": round(high_daily, 2),
                "low_daily_usdc": round(low_daily, 2),
                "high_daily_usdc": round(high_daily, 2),
            })

        results.append(strat_result)

    return results

def check_price_alerts(eaco_price, sol_price, sol_change_24h, dex_pairs):
    """Check for price alert conditions."""
    alerts = []

    # SOL 24h change alert
    if abs(sol_change_24h) > PRICE_ALERT_THRESHOLD_PCT:
        direction = "UP" if sol_change_24h > 0 else "DOWN"
        alerts.append({
            "level": "WARNING",
            "type": "SOL_PRICE_CHANGE",
            "message_cn": f"SOL 24h变动 {sol_change_24h:+.2f}% ({'涨' if sol_change_24h > 0 else '跌'}幅超{PRICE_ALERT_THRESHOLD_PCT}%)",
            "message_en": f"SOL 24h change {sol_change_24h:+.2f}% ({direction} >{PRICE_ALERT_THRESHOLD_PCT}%)",
        })

    # DEX pair price divergence
    if dex_pairs and len(dex_pairs) > 1:
        prices = [p["price_usd"] for p in dex_pairs if p["price_usd"] > 0]
        if prices and max(prices) > 0:
            spread_pct = (max(prices) - min(prices)) / max(prices) * 100
            if spread_pct > 5:
                alerts.append({
                    "level": "INFO",
                    "type": "DEX_SPREAD",
                    "message_cn": f"DEX间价差 {spread_pct:.2f}%，存在套利机会",
                    "message_en": f"DEX spread {spread_pct:.2f}%, arbitrage opportunity exists",
                })

    # Low liquidity warning
    total_liq = sum(p["liquidity_usd"] for p in dex_pairs) if dex_pairs else 0
    if total_liq > 0 and total_liq < 10000:
        alerts.append({
            "level": "WARNING",
            "type": "LOW_LIQUIDITY",
            "message_cn": f"总流动性仅 ${total_liq:,.0f}，交易需注意滑点",
            "message_en": f"Total liquidity only ${total_liq:,.0f}, beware of slippage",
        })

    return alerts

def generate_html_report(report):
    """Generate a visual HTML report."""
    md = report["market_data"]
    strategies = report["strategies"]
    summary = report["summary"]
    alerts = report.get("alerts", [])

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EACO Daily Agent Report - {report['report_time']}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0a0e17;color:#e0e6ed;padding:20px}}
.container{{max-width:1200px;margin:0 auto}}
h1{{color:#00d4ff;text-align:center;margin-bottom:5px;font-size:2em}}
.subtitle{{text-align:center;color:#8892b0;margin-bottom:30px}}
.lang-bar{{text-align:center;margin-bottom:20px}}
.lang-bar a{{display:inline-block;padding:4px 10px;margin:2px;border-radius:6px;background:#111827;border:1px solid #1e2a3a;color:#8892b0;text-decoration:none;font-size:12px}}
.lang-bar a:hover{{border-color:#00d4ff;color:#00d4ff}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:15px;margin-bottom:30px}}
.card{{background:#111827;border:1px solid #1e2a3a;border-radius:12px;padding:20px}}
.card h3{{color:#00d4ff;font-size:0.85em;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px}}
.card .value{{font-size:1.8em;font-weight:700;color:#fff}}
.card .sub{{color:#8892b0;font-size:0.85em;margin-top:5px}}
.alert{{background:#1a1a2e;border-left:4px solid #f39c12;padding:12px 20px;border-radius:8px;margin-bottom:8px}}
.alert.warning{{border-color:#e74c3c}}
.alert.info{{border-color:#3498db}}
table{{width:100%;border-collapse:collapse;margin-bottom:30px;background:#111827;border-radius:12px;overflow:hidden}}
th{{background:#1a2332;color:#00d4ff;padding:12px;text-align:left;font-size:0.85em;text-transform:uppercase}}
td{{padding:10px 12px;border-bottom:1px solid #1e2a3a;font-size:0.9em}}
tr:hover{{background:#162033}}
.tag{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:0.75em;font-weight:600}}
.tag-auto{{background:#0d4a3f;color:#00ff9f}}
.tag-manual{{background:#4a2a0d;color:#ff9f00}}
.tag-key{{background:#4a0d0d;color:#ff6b6b}}
.tag-nokey{{background:#0d3a4a;color:#00d4ff}}
.section-title{{color:#00d4ff;font-size:1.3em;margin:30px 0 15px;padding-bottom:10px;border-bottom:2px solid #1e2a3a}}
.disclaimer{{background:#111827;border:1px solid #374151;border-radius:12px;padding:20px;color:#8892b0;font-size:0.85em;margin-top:30px;line-height:1.6}}
.skill-link{{color:#00d4ff;text-decoration:none}}
.skill-link:hover{{text-decoration:underline}}
.footer-links{{text-align:center;margin-top:30px;padding:20px;background:#111827;border-radius:12px}}
.footer-links a{{display:inline-block;margin:3px;padding:6px 12px;background:#1a2332;border:1px solid #1e2a3a;border-radius:8px;color:#8892b0;text-decoration:none;font-size:12px}}
.footer-links a:hover{{border-color:#00d4ff;color:#00d4ff}}
@media(max-width:768px){{.grid{{grid-template-columns:1fr}} table{{font-size:0.75em}}}}
</style>
</head>
<body>
<div class="container">
<h1>EACO Daily Agent Report</h1>
<p class="subtitle">{report['report_time']} | v{report['agent_version']} | {report['network']}</p>
<div class="lang-bar">
<a href="index.html">CN</a> <a href="en.html">EN</a> <a href="ru.html">RU</a> <a href="ja.html">JA</a> <a href="ko.html">KO</a> <a href="es.html">ES</a> <a href="fr.html">FR</a> <a href="ar.html">AR</a> <a href="vi.html">VI</a> <a href="id.html">ID</a> <a href="ms.html">MS</a>
</div>

<div class="grid">
<div class="card"><h3>EACO Price</h3><div class="value">${md['eaco_price_usd']}</div><div class="sub">Source: {md['price_source']}</div></div>
<div class="card"><h3>SOL Price</h3><div class="value">${md['sol_price_usd']:.2f}</div><div class="sub">24h: {md.get('sol_24h_change', 0):+.2f}%</div></div>
<div class="card"><h3>EACO Market Cap</h3><div class="value">${md['eaco_market_cap_usd']:,.0f}</div><div class="sub">Supply: {md['eaco_total_supply']:,.0f}</div></div>
<div class="card"><h3>DEX Liquidity</h3><div class="value">${md['total_liquidity_usd']:,.0f}</div><div class="sub">24h Vol: ${md['total_volume_24h_usd']:,.0f}</div></div>
<div class="card"><h3>Holders</h3><div class="value">{report.get('onchain', {}).get('holders_estimated', 'N/A')}</div><div class="sub">Token accounts</div></div>
<div class="card"><h3>EACO/SOL Rate</h3><div class="value">{md['eaco_sol_rate']:,.0f}</div><div class="sub">1 SOL = X EACO</div></div>
</div>
"""

    # v5.0: Earning Simulation Dashboard
    sim = report.get("simulation", {})
    if sim:
        dr = sim.get("daily_result", {})
        pf = sim.get("portfolio", {})
        hist = sim.get("recent_history", [])
        perf = sim.get("strategy_performance", {})
        today_usd = dr.get("earned_usd", 0)
        today_eaco = dr.get("earned_eaco", 0)
        today_sol = dr.get("earned_sol", 0)

        html += f"""
<div class="section-title">v5.0 Daily Earning Simulation</div>
<div class="grid">
<div class="card" style="border-color:#0d4a3f"><h3>Today's Earning (USD)</h3><div class="value" style="color:#00ff9f">+${today_usd:.4f}</div><div class="sub">{today_eaco:,.0f} EACO | {today_sol:.6f} SOL</div></div>
<div class="card"><h3>Portfolio SOL</h3><div class="value">{pf.get('current_sol', 0):.4f}</div><div class="sub">Initial: {pf.get('initial_capital_sol', 10)}</div></div>
<div class="card"><h3>Portfolio EACO</h3><div class="value">{pf.get('current_eaco', 0):,.0f}</div><div class="sub">Total earned: {pf.get('total_earned_eaco', 0):,.0f}</div></div>
<div class="card"><h3>Total Earned (USD)</h3><div class="value" style="color:#00ff9f">${pf.get('total_earned_usd', 0):.2f}</div><div class="sub">ROI: {pf.get('roi_pct', 0):+.2f}% | Day {pf.get('days_active', 1)}</div></div>
</div>
"""

        # Today's strategy execution details
        if dr.get("details"):
            html += '<div class="section-title">Today\'s Strategy Execution</div>\n'
            html += '<table><tr><th>ID</th><th>Strategy</th><th>Skill</th><th>Alloc SOL</th><th>APR</th><th>Earned USD</th><th>Earned EACO</th><th>Earned SOL</th><th>Reason</th></tr>\n'
            for d in dr["details"]:
                skill_link = f'<a class="skill-link" href="../eaco-agent-skills/{d["skill_ref"]}/SKILL.md">{d["skill_ref"]}</a>'
                html += f'<tr><td>{d["id"]}</td><td>{d["name_cn"]}<br><span style="color:#8892b0;font-size:0.8em">{d["name_en"]}</span></td>'
                html += f'<td>{skill_link}</td><td>{d["allocated_sol"]}</td><td>{d["actual_apr_pct"]:.3f}%</td>'
                html += f'<td style="color:#00ff9f">${d["earned_usd"]:.4f}</td><td>{d["earned_eaco"]:,.0f}</td><td>{d["earned_sol"]:.6f}</td>'
                html += f'<td style="font-size:0.8em;color:#8892b0">{d["reason_cn"]}</td></tr>\n'
            html += '</table>\n'

        # Recent 7-day history
        if hist:
            html += '<div class="section-title">Recent 7-Day History</div>\n'
            html += '<table><tr><th>Date</th><th>SOL Price</th><th>EACO Price</th><th>Strategies</th><th>Earned USD</th><th>Earned EACO</th><th>Earned SOL</th><th>Portfolio SOL</th><th>Portfolio EACO</th></tr>\n'
            for h in hist:
                html += f'<tr><td>{h["date"]}</td><td>${h["sol_price"]:.2f}</td><td>${h["eaco_price"]}</td>'
                html += f'<td>{h["strategies_run"]}</td><td style="color:#00ff9f">${h["earned_usd"]:.4f}</td>'
                html += f'<td>{h["earned_eaco"]:,.0f}</td><td>{h["earned_sol"]:.6f}</td>'
                html += f'<td>{h["portfolio_sol_after"]:.4f}</td><td>{h["portfolio_eaco_after"]:,.0f}</td></tr>\n'
            html += '</table>\n'

        # Strategy performance summary
        if perf:
            html += '<div class="section-title">Strategy Performance (Cumulative)</div>\n'
            html += '<table><tr><th>Strategy ID</th><th>Runs</th><th>Wins</th><th>Win Rate</th><th>Total USD</th></tr>\n'
            for sid, sp in sorted(perf.items()):
                wr = (sp["wins"] / sp["runs"] * 100) if sp["runs"] > 0 else 0
                html += f'<tr><td>{sid}</td><td>{sp["runs"]}</td><td>{sp["wins"]}</td><td>{wr:.0f}%</td><td>${sp["total_usd"]:.4f}</td></tr>\n'
            html += '</table>\n'

    # v5.0: Daily Action Plan
    action_cn = report.get("action_plan_cn", [])
    action_en = report.get("action_plan_en", [])
    if action_cn:
        html += '<div class="section-title">Daily Action Plan / 每日行动计划</div>\n'
        for i, (ac, ae) in enumerate(zip(action_cn, action_en)):
            html += f'<div class="card" style="margin-bottom:10px">'
            html += f'<h3 style="color:#00d4ff">[{ac["id"]}] {ac["name"]} / {ae["name"]}</h3>'
            html += f'<div class="sub" style="margin-bottom:8px">Alloc: {ac["allocated_sol"]} SOL | {ac["reason"]} / {ae["reason"]}</div>'
            html += '<table><tr><th>#</th><th>中文步骤</th><th>English Steps</th></tr>'
            for j, (sc, se) in enumerate(zip(ac["steps"], ae["steps"]), 1):
                html += f'<tr><td>{j}</td><td>{sc}</td><td>{se}</td></tr>'
            html += '</table></div>\n'

    # Alerts
    if alerts:
        html += '<div class="section-title">Price Alerts</div>\n'
        for a in alerts:
            html += f'<div class="alert {a["level"].lower()}">{a["message_cn"]} / {a["message_en"]}</div>\n'

    # Summary table
    html += '<div class="section-title">Daily Earnings Summary (Realistic Top-3 Split)</div>\n'
    html += '<table><tr><th>Capital Tier</th><th>Capital (USD)</th><th>Low/Day</th><th>High/Day</th><th>Low/Day (EACO)</th><th>High/Day (EACO)</th></tr>\n'
    for tier_name in ["1 SOL", "10 SOL", "100 SOL"]:
        s = summary[tier_name]
        html += f'<tr><td><b>{tier_name}</b></td><td>${s["capital_usd"]:,.2f}</td>'
        html += f'<td>${s["realistic_top3_low_usd"]:.2f}</td><td>${s["realistic_top3_high_usd"]:.2f}</td>'
        html += f'<td>{s["realistic_top3_low_eaco"]:,.0f}</td><td>{s["realistic_top3_high_eaco"]:,.0f}</td></tr>\n'
    html += '</table>\n'

    # Strategy details
    html += '<div class="section-title">Strategy Details (15 Strategies)</div>\n'
    html += '<table><tr><th>ID</th><th>Strategy</th><th>Skill</th><th>APY</th><th>Risk</th><th>1 SOL Low/High</th><th>10 SOL Low/High</th><th>100 SOL Low/High</th><th>Tags</th></tr>\n'
    for e in strategies:
        auto_tag = '<span class="tag tag-auto">AUTO</span>' if e["auto_executable"] else '<span class="tag tag-manual">MANUAL</span>'
        key_tag = '<span class="tag tag-key">KEY</span>' if e["needs_key"] else '<span class="tag tag-nokey">NO-KEY</span>'
        d1 = e["daily_estimates"][0]
        d10 = e["daily_estimates"][1]
        d100 = e["daily_estimates"][2]
        skill_link = f'<a class="skill-link" href="../eaco-agent-skills/{e["skill_ref"]}/SKILL.md">{e["skill_ref"]}</a>'
        html += f'<tr><td>{e["id"]}</td><td>{e["name_cn"]}<br><span style="color:#8892b0;font-size:0.8em">{e["name_en"]}</span></td>'
        html += f'<td>{skill_link}</td>'
        html += f'<td>{e["apy_range"]}</td><td>{e["risk_cn"]}</td>'
        html += f'<td>${d1["low_daily_usd"]:.2f}<br>${d1["high_daily_usd"]:.2f}</td>'
        html += f'<td>${d10["low_daily_usd"]:.2f}<br>${d10["high_daily_usd"]:.2f}</td>'
        html += f'<td>${d100["low_daily_usd"]:.2f}<br>${d100["high_daily_usd"]:.2f}</td>'
        html += f'<td>{auto_tag} {key_tag}</td></tr>\n'
    html += '</table>\n'

    # DEX pairs
    if md.get("dex_pairs"):
        html += '<div class="section-title">DEX Pairs</div>\n'
        html += '<table><tr><th>DEX</th><th>Pair</th><th>Price (USD)</th><th>Liquidity</th><th>24h Volume</th><th>24h Change</th><th>Buys</th><th>Sells</th></tr>\n'
        for p in md["dex_pairs"]:
            html += f'<tr><td>{p["dex"]}</td><td>{p["base"]}/{p["quote"]}</td>'
            html += f'<td>${p["price_usd"]:.8f}</td><td>${p["liquidity_usd"]:,.0f}</td>'
            html += f'<td>${p["volume_24h"]:,.0f}</td><td>{p["change_24h"]:+.2f}%</td>'
            html += f'<td>{p["buys_24h"]}</td><td>{p["sells_24h"]}</td></tr>\n'
        html += '</table>\n'

    # Meteora pools
    if report.get("meteora_pools"):
        html += '<div class="section-title">Meteora DLMM Pools (On-Chain)</div>\n'
        html += '<table><tr><th>Pool</th><th>Address</th><th>Status</th></tr>\n'
        for name, pool in report["meteora_pools"].items():
            status = "Active" if pool.get("exists") else "Not Found"
            html += f'<tr><td>{name}</td><td style="font-family:monospace;font-size:0.8em">{pool["address"]}</td><td>{status}</td></tr>\n'
        html += '</table>\n'

    html += f"""
<div class="disclaimer">
<b>Disclaimer:</b> {report['disclaimer']}
</div>

<div class="footer-links">
<a href="https://ucoingroup.github.io/earths-best-coin/">Earth's Best Coin</a>
<a href="https://ucoingroup.github.io/eaco50rate/">EACO 50 Rate</a>
<a href="https://ucoingroup.github.io/100WaysToWealth/">100 Ways To Wealth</a>
<a href="https://ucoingroup.github.io/earth-100-friends/">Earth 100 Friends</a>
<a href="https://ucoingroup.github.io/eacoSWAP/">EACO SWAP</a>
<a href="https://ucoingroup.github.io/good-books/">Good Books</a>
<a href="https://ucoingroup.github.io/eur-eaco/">EUR EACO</a>
<a href="https://ucoingroup.github.io/au-trade/">AU Trade</a>
<a href="https://ucoingroup.github.io/Mohist-Tech/">Mohist Tech</a>
<a href="https://eaco-build-world.base44.app/">EACO Build World</a>
<a href="https://eaco-web3.base44.app">EACO Web3</a>
</div>
</div>
</body>
</html>"""

    with open(HTML_REPORT, "w", encoding="utf-8") as f:
        f.write(html)
    log(f"HTML report saved to {HTML_REPORT}")

def generate_report(quiet=False, json_only=False, test_mode=False):
    """Main agent function. v5.0 with simulation engine and test mode."""
    log("=" * 70)
    log("EACO Daily Agent v5.0 - Starting daily run" + (" [TEST MODE]" if test_mode else ""))
    log("=" * 70)

    if test_mode:
        # Use mock data for offline testing
        log("Step 1: [TEST] Using mock market data...")
        sol_price = 72.50
        sol_change_24h = 3.5
        usdc_price = 1.0
        eaco_price = 0.0012
        total_liq = 35000.0
        total_vol = 5000.0
        dex_pairs = []
        price_source = "Mock (test mode)"
        onchain = {"supply": EACO_TOTAL_SUPPLY, "slot": 290000000, "holders_estimated": 1850, "epoch": 720}
        meteora_pools = {"E-USDT": {"address": METEORA_E_USDT_POOL, "exists": True}, "E-SOL": {"address": METEORA_E_SOL_POOL, "exists": True}}
        log(f"  SOL/USDT: ${sol_price:.2f} (mock)")
        log(f"  EACO Price: ${eaco_price} (mock)")
        log(f"  EACO Supply: {onchain['supply']:,.2f}")
        log(f"  EACO MCap: ${eaco_price * onchain['supply']:,.2f}")
    else:
        # 1. Fetch SOL price
        log("Step 1: Fetching SOL price from Gate.io...")
        sol_data = get_sol_price_gateio()
        if sol_data:
            sol_price = sol_data["price"]
            sol_change_24h = sol_data["change_24h"]
            log(f"  SOL/USDT: ${sol_price:.2f} | 24h Vol: ${sol_data['vol_24h']:,.0f} | Change: {sol_data['change_24h']:+.2f}%")
        else:
            sol_price = 70.0
            sol_change_24h = 0.0
            log(f"  Gate.io unreachable, using fallback: ${sol_price}")

        # 2. USDC price
        usdc_price = get_usdc_price_gateio()
        log(f"  USDC/USDT: ${usdc_price:.4f}")

        # 3. EACO on-chain data
        log("Step 2: Fetching EACO on-chain data via PublicNode RPC...")
        onchain = get_eaco_onchain_data()

        # 4. EACO price
        log("Step 3: Fetching EACO price...")
        eaco_price, total_liq, total_vol, dex_pairs, price_source = estimate_eaco_price(sol_price, onchain)
        log(f"  EACO Price: ${eaco_price} (source: {price_source})")
    log(f"  EACO Total Supply: {onchain['supply']:,.2f}")
    log(f"  EACO Market Cap: ${eaco_price * onchain['supply']:,.2f}")
    if total_liq > 0:
        log(f"  Total DEX Liquidity: ${total_liq:,.2f}")
        log(f"  24h Volume: ${total_vol:,.2f}")

    # 5. Meteora pool data
    log("Step 4: Fetching Meteora DLMM pool data...")
    meteora_pools = get_meteora_pool_data()

    # 6. Price alerts
    log("Step 5: Checking price alerts...")
    alerts = check_price_alerts(eaco_price, sol_price, sol_change_24h, dex_pairs)
    if alerts:
        for a in alerts:
            log(f"  ALERT [{a['level']}]: {a['message_cn']}")
    else:
        log("  No alerts triggered.")

    # 7. Calculate earnings
    log("Step 6: Calculating daily earnings for 15 strategies...")
    earnings = calculate_daily_earnings(eaco_price, sol_price, total_liq, total_vol)

    # 7b. v5.0: Load portfolio and run simulation engine
    log("Step 6b: Loading portfolio and running daily earning simulation...")
    portfolio = load_portfolio()
    log(f"  Portfolio: {portfolio['days_active']} days active | "
        f"SOL: {portfolio['current_sol']:.4f} | EACO: {portfolio['current_eaco']:,.0f} | "
        f"Total earned: ${portfolio['total_earned_usd']:.2f}")
    
    log("Step 6c: Selecting today's optimal strategies...")
    selected = select_daily_strategies(sol_price, eaco_price, total_liq, sol_change_24h)
    log(f"  Selected {len(selected)} strategies for today:")
    for strat, alloc_sol, _, reason_cn, _ in selected:
        log(f"    {strat['id']} {strat['name_cn']} | alloc: {alloc_sol} SOL | {reason_cn}")
    
    log("Step 6d: Simulating daily earning...")
    daily_result = simulate_daily_earning(portfolio, selected, sol_price, eaco_price)
    log(f"  Today's earning: ${daily_result['earned_usd']:.4f} | "
        f"{daily_result['earned_eaco']:,.0f} EACO | {daily_result['earned_sol']:.6f} SOL")
    log(f"  Portfolio after: SOL: {portfolio['current_sol']:.4f} | "
        f"EACO: {portfolio['current_eaco']:,.0f} | USD: {portfolio['current_usd']:.2f}")
    
    # Save portfolio
    save_portfolio(portfolio)
    
    # Load and update history
    history = load_history()
    history["records"].append(daily_result)
    history["cumulative_usd"] = portfolio["total_earned_usd"]
    history["cumulative_eaco"] = portfolio["total_earned_eaco"]
    history["total_days"] = portfolio["days_active"]
    if len(history["records"]) > 365:
        history["records"] = history["records"][-365:]
    save_history(history)
    
    # Generate action plan
    log("Step 6e: Generating daily action plan...")
    actions_cn, actions_en = generate_action_plan(selected, sol_price, eaco_price)

    # 8. Build report
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    report = {
        "report_time": now.strftime("%Y-%m-%d %H:%M:%S CST"),
        "agent_version": "5.0",
        "network": "Solana Mainnet",
        "market_data": {
            "eaco_price_usd": eaco_price,
            "sol_price_usd": sol_price,
            "usdc_price_usd": usdc_price,
            "eaco_sol_rate": eaco_price / sol_price if sol_price > 0 else 0,
            "eaco_total_supply": onchain["supply"],
            "eaco_market_cap_usd": round(eaco_price * onchain["supply"], 2),
            "total_liquidity_usd": round(total_liq, 2),
            "total_volume_24h_usd": round(total_vol, 2),
            "current_slot": onchain.get("slot", 0),
            "price_source": price_source,
            "sol_24h_change": sol_change_24h,
            "dex_pairs": dex_pairs[:5] if dex_pairs else [],
        },
        "onchain": {
            "supply": onchain["supply"],
            "slot": onchain.get("slot", 0),
            "epoch": onchain.get("epoch", 0),
            "holders_estimated": onchain.get("holders_estimated", 0),
        },
        "meteora_pools": meteora_pools,
        "alerts": alerts,
        "strategies": earnings,
        "summary": {},
        "disclaimer": (
            "DISCLAIMER: This report is for informational purposes only. "
            "APY/APR estimates are based on industry benchmarks for similar Solana DeFi strategies, "
            "not actual on-chain measured returns for EACO. "
            "Actual earnings depend on: market conditions, gas costs, slippage, liquidity depth, "
            "competition, and execution speed. "
            "Strategies with needs_key=true require your private key and cannot be auto-executed by this agent. "
            "Strategies with auto_executable=true can potentially be automated with proper key management. "
            "EACO is a micro-cap token with high volatility and limited liquidity - invest only what you can afford to lose. "
            "Always do your own research (DYOR)."
        ),
    }

    # Summary
    for tier_name, multiplier in [("1 SOL", 1), ("10 SOL", 10), ("100 SOL", 100)]:
        capital_usd = sol_price * multiplier
        total_low = sum(s["daily_apr_range"][0] for s in STRATEGIES) * capital_usd / 100
        total_high = sum(s["daily_apr_range"][1] for s in STRATEGIES) * capital_usd / 100
        top3 = sorted(STRATEGIES, key=lambda s: s["daily_apr_range"][1], reverse=True)[:3]
        realistic_low = sum(s["daily_apr_range"][0] for s in top3) * capital_usd / 100 / 3
        realistic_high = sum(s["daily_apr_range"][1] for s in top3) * capital_usd / 100 / 3
        auto_strats = [s for s in STRATEGIES if s["auto_executable"]]
        auto_low = sum(s["daily_apr_range"][0] for s in auto_strats) * capital_usd / 100 / len(auto_strats) if auto_strats else 0
        auto_high = sum(s["daily_apr_range"][1] for s in auto_strats) * capital_usd / 100 / len(auto_strats) if auto_strats else 0

        report["summary"][tier_name] = {
            "capital_sol": multiplier,
            "capital_usd": round(capital_usd, 2),
            "all_15_theoretical_low_usd": round(total_low, 2),
            "all_15_theoretical_high_usd": round(total_high, 2),
            "realistic_top3_low_usd": round(realistic_low, 2),
            "realistic_top3_high_usd": round(realistic_high, 2),
            "realistic_top3_low_eaco": round(realistic_low / eaco_price, 0) if eaco_price > 0 else 0,
            "realistic_top3_high_eaco": round(realistic_high / eaco_price, 0) if eaco_price > 0 else 0,
            "realistic_top3_low_sol": round(realistic_low / sol_price, 4) if sol_price > 0 else 0,
            "realistic_top3_high_sol": round(realistic_high / sol_price, 4) if sol_price > 0 else 0,
            "auto_strategies_low_usd": round(auto_low, 2),
            "auto_strategies_high_usd": round(auto_high, 2),
            "top3_strategy_names": [f"{s['id']} {s['name_en']}" for s in top3],
        }

    # v5.0: Add simulation results to report
    report["simulation"] = {
        "daily_result": daily_result,
        "portfolio": {
            "days_active": portfolio["days_active"],
            "current_sol": round(portfolio["current_sol"], 4),
            "current_eaco": round(portfolio["current_eaco"], 0),
            "current_usd": round(portfolio["current_usd"], 2),
            "total_earned_usd": round(portfolio["total_earned_usd"], 2),
            "total_earned_eaco": round(portfolio["total_earned_eaco"], 0),
            "total_earned_sol": round(portfolio["total_earned_sol"], 6),
            "initial_capital_sol": portfolio["initial_capital_sol"],
            "roi_pct": round((portfolio["current_sol"] - portfolio["initial_capital_sol"]) / portfolio["initial_capital_sol"] * 100, 2) if portfolio["initial_capital_sol"] > 0 else 0,
        },
        "strategy_performance": portfolio["strategy_results"],
        "recent_history": portfolio["daily_history"][-7:],  # Last 7 days
    }
    report["action_plan_cn"] = actions_cn
    report["action_plan_en"] = actions_en

    # 9. Save JSON report
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    log(f"JSON report saved to {REPORT_FILE}")

    # 10. Generate HTML report
    generate_html_report(report)

    # 11. Print summary
    log("")
    log("=" * 70)
    log("DAILY EARNINGS SIMULATION SUMMARY (v5.0)")
    log("=" * 70)
    log(f"EACO Price:  ${eaco_price} (source: {price_source})")
    log(f"SOL Price:   ${sol_price:.2f}")
    log(f"USDC Price:  ${usdc_price:.4f}")
    log(f"EACO Supply: {onchain['supply']:,.2f}")
    log(f"EACO MCap:   ${eaco_price * onchain['supply']:,.2f}")
    if onchain.get("holders_estimated", 0) > 0:
        log(f"Holders:     {onchain['holders_estimated']}")
    if total_liq > 0:
        log(f"DEX Liq:     ${total_liq:,.2f}")
        log(f"24h Volume:  ${total_vol:,.2f}")

    if alerts:
        log("")
        log("ALERTS:")
        for a in alerts:
            log(f"  [{a['level']}] {a['message_cn']}")

    log("")
    for tier_name in ["1 SOL", "10 SOL", "100 SOL"]:
        s = report["summary"][tier_name]
        log(f"--- {tier_name} (~${s['capital_usd']:.2f}) ---")
        log(f"  Realistic (top 3, split capital):")
        log(f"    USD:  ${s['realistic_top3_low_usd']:.2f} - ${s['realistic_top3_high_usd']:.2f} / day")
        log(f"    EACO: {s['realistic_top3_low_eaco']:,.0f} - {s['realistic_top3_high_eaco']:,.0f} / day")
        log(f"    SOL:  {s['realistic_top3_low_sol']:.4f} - {s['realistic_top3_high_sol']:.4f} / day")
        log(f"  Auto-executable only ({len([s for s in STRATEGIES if s['auto_executable']])} strategies):")
        log(f"    USD:  ${s['auto_strategies_low_usd']:.2f} - ${s['auto_strategies_high_usd']:.2f} / day")
        log(f"  Theoretical max (all 15):")
        log(f"    USD:  ${s['all_15_theoretical_low_usd']:.2f} - ${s['all_15_theoretical_high_usd']:.2f} / day")
        log("")

    log("Strategy Details:")
    for e in earnings:
        auto_tag = "[AUTO]" if e["auto_executable"] else "[MANUAL]"
        key_tag = "[KEY]" if e["needs_key"] else "[NO-KEY]"
        log(f"  {e['id']} {e['name_cn']} / {e['name_en']} {auto_tag} {key_tag}")
        log(f"    Skill: {e['skill_ref']} | APY: {e['apy_range']} | Risk: {e['risk_cn']}")
        for d in e["daily_estimates"]:
            log(f"    {d['tier']}: ${d['low_daily_usd']:.2f}-${d['high_daily_usd']:.2f}/day | "
                f"{d['low_daily_sol']:.4f}-{d['high_daily_sol']:.4f} SOL | "
                f"{d['low_daily_eaco']:,.0f}-{d['high_daily_eaco']:,.0f} EACO")
        log("")

    # v5.0: Print simulation results
    log("=" * 70)
    log("TODAY'S EARNING SIMULATION (v5.0)")
    log("=" * 70)
    log(f"Strategies executed: {daily_result['strategies_run']}")
    log(f"Today's earning:")
    log(f"  USD:  ${daily_result['earned_usd']:.4f}")
    log(f"  EACO: {daily_result['earned_eaco']:,.0f}")
    log(f"  SOL:  {daily_result['earned_sol']:.6f}")
    log(f"Portfolio status (Day {portfolio['days_active']}):")
    log(f"  SOL:       {portfolio['current_sol']:.4f} (initial: {portfolio['initial_capital_sol']})")
    log(f"  EACO:      {portfolio['current_eaco']:,.0f}")
    log(f"  USD equiv: ${portfolio['current_usd']:.2f}")
    log(f"  Total earned: ${portfolio['total_earned_usd']:.2f} | {portfolio['total_earned_eaco']:,.0f} EACO")
    roi = (portfolio["current_sol"] - portfolio["initial_capital_sol"]) / portfolio["initial_capital_sol"] * 100
    log(f"  ROI: {roi:+.2f}%")
    log("")
    log("Today's Action Plan:")
    for a in actions_cn:
        log(f"  [{a['id']}] {a['name']} (alloc: {a['allocated_sol']} SOL)")
        log(f"    Reason: {a['reason']}")
        for i, step in enumerate(a["steps"], 1):
            log(f"    {i}. {step}")
    log("")

    log(f"Reports: {REPORT_FILE}")
    log(f"         {HTML_REPORT}")
    log(f"         {PORTFOLIO_FILE}")
    log(f"         {HISTORY_FILE}")

    # v4.0: Copy report to eaco-app directory for website integration
    eaco_app_dir = os.path.join(os.path.dirname(OUTPUT_DIR), "eaco-app")
    if os.path.isdir(eaco_app_dir):
        try:
            import shutil
            app_report_html = os.path.join(eaco_app_dir, "agent-report.html")
            shutil.copy2(HTML_REPORT, app_report_html)
            app_report_json = os.path.join(eaco_app_dir, "agent-report.json")
            shutil.copy2(REPORT_FILE, app_report_json)
            log(f"  Reports copied to {app_report_html}")
            log(f"  Reports copied to {app_report_json}")
        except Exception as e:
            log(f"  Warning: could not copy reports to eaco-app: {e}")
    else:
        log(f"  eaco-app dir not found at {eaco_app_dir}, skipping copy")

    log("Agent v5.0 run complete.")
    log("=" * 70)

    return report


if __name__ == "__main__":
    quiet = "--quiet" in sys.argv or "-q" in sys.argv
    json_only = "--json-only" in sys.argv or "-j" in sys.argv
    test_mode = "--test" in sys.argv or "-t" in sys.argv

    try:
        report = generate_report(quiet=quiet, json_only=json_only, test_mode=test_mode)
        if json_only:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        sys.exit(0)
    except KeyboardInterrupt:
        log("Agent interrupted by user.")
        sys.exit(130)
    except Exception as e:
        log(f"FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
