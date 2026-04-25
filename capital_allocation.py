"""
SwingAI - Capital Allocation Engine
Tells you exactly how much to deploy vs keep in cash, every day.
Based on Minervini's market exposure model.
"""
import datetime

EXPOSURE_TIERS = [
    (80, 100, 90, "Aggressive",   "Market confirmed bull - deploy fully"),
    (65,  79, 75, "Offensive",    "Good conditions - take quality setups"),
    (50,  64, 55, "Moderate",     "Mixed signals - only A/A+ setups"),
    (35,  49, 35, "Defensive",    "Weak breadth - reduce size, wait"),
    (20,  34, 15, "Capital Pres", "Danger zone - minimal exposure"),
    ( 0,  19,  0, "Cash",         "Bear market - 100% cash"),
]
RISK_PER_TRADE_PCT = 1.0
GRADE_SIZE_MULT = {"A+": 1.0, "A": 0.8, "B+": 0.6, "B": 0.4, "C": 0.0}

def _get_tier(score):
    for mn, mx, deploy, label, desc in EXPOSURE_TIERS:
        if mn <= score <= mx:
            return {"deploy_pct": deploy, "label": label, "description": desc}
    return {"deploy_pct": 0, "label": "Cash", "description": "Unknown"}

def _vix_adjustment(vix_val):
    if vix_val is None: return 0
    if vix_val > 30: return -20
    elif vix_val > 24: return -10
    elif vix_val < 13: return -5
    return 0

def _setup_count_signal(n):
    if n >= 15: return f"Strong ({n} setups) - deploy fully"
    elif n >= 8: return f"Moderate ({n} setups) - selective"
    elif n >= 3: return f"Thin ({n} setups) - very selective"
    else: return f"Scarce ({n} setups) - stay patient"

def get_capital_allocation(macro, sectors, scan_data, portfolio_inr=1_000_000):
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    base_score   = macro.get("macro_score", 50)
    vix_val      = macro.get("vix", {}).get("value")
    health_score = max(0, min(100, base_score + _vix_adjustment(vix_val)))
    tier         = _get_tier(health_score)
    deploy_pct   = tier["deploy_pct"]
    cash_pct     = 100 - deploy_pct
    deploy_inr   = int(portfolio_inr * deploy_pct / 100)
    cash_inr     = portfolio_inr - deploy_inr

    results        = scan_data.get("results", [])
    aplus          = [r for r in results if r["grade"] == "A+"]
    a_grade        = [r for r in results if r["grade"] == "A"]
    quality_setups = len(aplus) + len(a_grade)
    setup_signal   = _setup_count_signal(quality_setups)

    top_setups = (aplus + a_grade)[:10]
    avg_risk   = sum(float(r.get("risk_pct", 8)) for r in top_setups) / len(top_setups) if top_setups else 8.0

    risk_per_trade_inr = int(portfolio_inr * RISK_PER_TRADE_PCT / 100)
    max_position_inr   = int(risk_per_trade_inr / (avg_risk / 100)) if avg_risk > 0 else int(deploy_inr * 0.2)
    max_position_inr   = min(max_position_inr, int(portfolio_inr * 0.20))
    max_positions      = min(int(deploy_inr / max_position_inr), 10) if max_position_inr > 0 and deploy_inr > 0 else 0

    grade_sizing = {g: {"position_inr": int(max_position_inr * m), "multiplier": m} for g, m in GRADE_SIZE_MULT.items()}

    key_rules = []
    if deploy_pct == 0:       key_rules.append("STAY IN CASH - Do not enter any new positions")
    elif deploy_pct <= 25:    key_rules.append("Minimal exposure - Only A+ setups, half size")
    elif deploy_pct <= 55:    key_rules.append("Selective - A and A+ setups only")
    else:                     key_rules.append("Normal exposure - Work all quality setups")

    rotation_type = sectors.get("rotation_type", "Mixed")
    leaders       = sectors.get("leaders", [])
    if leaders and rotation_type == "Risk-On":
        key_rules.append(f"Sector tailwind: Focus on {leaders[0]['sector']} stocks")
    elif rotation_type == "Defensive":
        key_rules.append("Market defensive - avoid cyclicals/small caps")
    if vix_val and vix_val > 24:
        key_rules.append(f"VIX at {vix_val} - reduce position size by 30%")
    key_rules.append(f"Max risk/trade: Rs{risk_per_trade_inr:,.0f} (1% rule)")

    gs = grade_sizing
    lines = [
        "========================",
        f"CAPITAL ALLOCATION - {today}",
        f"Market Health: {health_score}/100 - {tier['label']}",
        "========================",
        "",
        f"Portfolio:    Rs{portfolio_inr:>12,.0f}",
        f"Deploy Now:   Rs{deploy_inr:>12,.0f}  ({deploy_pct}%)",
        f"Keep Cash:    Rs{cash_inr:>12,.0f}  ({cash_pct}%)",
        "",
        f"Max Positions: {max_positions}",
        f"Risk/Trade:    Rs{risk_per_trade_inr:,.0f}",
        f"Max Pos Size:  Rs{max_position_inr:,.0f}",
        "",
        "SIZING BY GRADE:",
        f"  A+: Rs{gs.get('A+',{}).get('position_inr',0):>10,.0f}",
        f"  A:  Rs{gs.get('A',{}).get('position_inr',0):>10,.0f}",
        f"  B+: Rs{gs.get('B+',{}).get('position_inr',0):>10,.0f}",
        "",
        f"Setups: {setup_signal}",
        "",
        "TODAY'S RULES:",
    ] + [f"  {r}" for r in key_rules]

    return {
        "date": today, "portfolio_inr": portfolio_inr,
        "health_score": health_score, "deploy_pct": deploy_pct, "cash_pct": cash_pct,
        "deploy_inr": deploy_inr, "cash_inr": cash_inr,
        "tier_label": tier["label"], "tier_description": tier["description"],
        "max_positions": max_positions, "risk_per_trade_inr": risk_per_trade_inr,
        "max_position_size_inr": max_position_inr, "avg_stop_pct": round(avg_risk, 1),
        "setup_signal": setup_signal, "quality_setups": quality_setups,
        "grade_sizing": grade_sizing, "key_rules": key_rules,
        "telegram_block": "\n".join(lines),
    }
