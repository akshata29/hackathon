#!/usr/bin/env python3
"""
seed-portfolio-db.py
====================
Creates and seeds a local SQLite database (data/portfolio.db) with realistic
per-user portfolio data.  Row-level security is enforced at the application
layer: every query filters on user_id.

Users seeded:
    fabricusera@MngEnvMCAP152362.onmicrosoft.com  — Growth / Tech-heavy investor
    fabricuserb@MngEnvMCAP152362.onmicrosoft.com  — Conservative / Balanced investor
    admin@MngEnvMCAP152362.onmicrosoft.com         — Advisor overview (large AUM)
    dev                                            — Dev/local fallback identity

Run:
    python scripts/seed-portfolio-db.py [--db path/to/portfolio.db]

The MCP server reads this file when DB_PATH env var is set.
"""

import argparse
import os
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Deterministic per-user portfolio definitions
# ---------------------------------------------------------------------------

USERS = [
    {
        "user_id": "fabricusera@MngEnvMCAP152362.onmicrosoft.com",
        "display_name": "Fabric User A",
        "email": "fabricusera@MngEnvMCAP152362.onmicrosoft.com",
        "profile": "growth",
    },
    {
        "user_id": "fabricuserb@MngEnvMCAP152362.onmicrosoft.com",
        "display_name": "Fabric User B",
        "email": "fabricuserb@MngEnvMCAP152362.onmicrosoft.com",
        "profile": "conservative",
    },
    {
        "user_id": "admin@MngEnvMCAP152362.onmicrosoft.com",
        "display_name": "Portfolio Admin",
        "email": "admin@MngEnvMCAP152362.onmicrosoft.com",
        "profile": "diversified",
    },
    {
        "user_id": "dev",
        "display_name": "Dev User",
        "email": "dev@localhost",
        "profile": "growth",
    },
]

# Holdings definition: (symbol, name, sector, shares, avg_cost, current_price)
PROFILES: dict[str, list[tuple]] = {
    # -------------------------------------------------------------------------
    # Aggressive growth — ~60% Technology, rest in high-growth discretionary /
    # communication. 25 positions; avg holding period 18 months.
    # -------------------------------------------------------------------------
    "growth": [
        # Large-cap tech core
        ("AAPL",  "Apple Inc.",                    "Technology",             450, 125.00, 189.50),
        ("MSFT",  "Microsoft Corp.",               "Technology",             200, 285.00, 415.20),
        ("NVDA",  "NVIDIA Corp.",                  "Technology",             120, 220.00, 875.40),
        ("GOOGL", "Alphabet Inc.",                 "Technology",              80, 105.00, 175.60),
        ("META",  "Meta Platforms Inc.",           "Technology",              90, 195.00, 540.30),
        # Semiconductor ecosystem
        ("AMD",   "Advanced Micro Devices",        "Technology",             110, 105.00, 165.40),
        ("AVGO",  "Broadcom Inc.",                 "Technology",              35, 870.00,1582.00),
        ("QCOM",  "Qualcomm Inc.",                 "Technology",             100, 128.00, 162.90),
        ("AMAT",  "Applied Materials Inc.",        "Technology",              60, 148.00, 196.50),
        # Software / SaaS
        ("CRM",   "Salesforce Inc.",               "Technology",              60, 230.00, 285.70),
        ("NOW",   "ServiceNow Inc.",               "Technology",              25, 680.00, 925.60),
        ("ADBE",  "Adobe Inc.",                    "Technology",              40, 490.00, 385.20),
        ("INTU",  "Intuit Inc.",                   "Technology",              30, 548.00, 680.40),
        ("SNOW",  "Snowflake Inc.",                "Technology",              70, 185.00, 142.80),
        ("PLTR",  "Palantir Technologies",         "Technology",             400,  14.50,  28.70),
        # Cloud / internet
        ("AMZN",  "Amazon.com Inc.",               "Consumer Discretionary", 160, 120.00, 196.80),
        ("NFLX",  "Netflix Inc.",                  "Communication Services",  40, 380.00, 985.30),
        ("UBER",  "Uber Technologies Inc.",        "Consumer Discretionary", 180,  38.00,  82.15),
        # Fintech & payments
        ("V",     "Visa Inc.",                    "Financials",              80, 225.00, 310.80),
        ("PYPL",  "PayPal Holdings Inc.",          "Financials",             150,  68.00,  72.40),
        ("SQ",    "Block Inc.",                    "Financials",             130,  65.00,  78.90),
        # EV / clean-tech growth
        ("TSLA",  "Tesla Inc.",                    "Consumer Discretionary",  75, 195.00, 180.25),
        # Diversification anchors
        ("SPGI",  "S&P Global Inc.",               "Financials",              35, 380.00, 488.70),
        ("LLY",   "Eli Lilly and Co.",             "Healthcare",              25, 620.00,1088.40),
        ("BX",    "Blackstone Inc.",               "Financials",              55, 105.00, 168.30),
    ],

    # -------------------------------------------------------------------------
    # Conservative income — dividend-focused, low beta, all-weather 25 positions.
    # Target yield 2.8%, max drawdown tolerance -10%.
    # -------------------------------------------------------------------------
    "conservative": [
        # Healthcare
        ("JNJ",   "Johnson & Johnson",             "Healthcare",             220, 145.00, 152.30),
        ("UNH",   "UnitedHealth Group",            "Healthcare",              65, 520.00, 490.15),
        ("ABT",   "Abbott Laboratories",           "Healthcare",             150, 102.00, 118.60),
        ("MDT",   "Medtronic plc",                 "Healthcare",             180,  82.00,  88.45),
        ("PFE",   "Pfizer Inc.",                   "Healthcare",             400,  36.00,  27.80),
        # Consumer Staples
        ("PG",    "Procter & Gamble",              "Consumer Staples",       280, 140.00, 165.80),
        ("KO",    "Coca-Cola Co.",                 "Consumer Staples",       400,  52.00,  63.40),
        ("PEP",   "PepsiCo Inc.",                  "Consumer Staples",       120, 168.00, 157.20),
        ("WMT",   "Walmart Inc.",                  "Consumer Staples",       150,  58.00,  94.20),
        ("CL",    "Colgate-Palmolive Co.",         "Consumer Staples",       200,  74.00,  95.30),
        # Financials
        ("JPM",   "JPMorgan Chase",                "Financials",             180, 135.00, 225.60),
        ("BRK.B", "Berkshire Hathaway B",          "Financials",             140, 270.00, 458.20),
        ("WFC",   "Wells Fargo & Co.",             "Financials",             250,  42.00,  68.50),
        ("TFC",   "Truist Financial Corp.",        "Financials",             300,  32.00,  39.80),
        # Energy
        ("XOM",   "ExxonMobil",                    "Energy",                 200,  85.00, 117.40),
        ("CVX",   "Chevron Corp.",                 "Energy",                 130, 148.00, 163.20),
        # Utilities
        ("NEE",   "NextEra Energy",                "Utilities",              250,  58.00,  73.15),
        ("SO",    "Southern Co.",                  "Utilities",              300,  64.00,  88.90),
        ("D",     "Dominion Energy Inc.",          "Utilities",              220,  52.00,  57.40),
        # Communication
        ("VZ",    "Verizon Communications",        "Communication Services", 350,  44.00,  40.80),
        ("T",     "AT&T Inc.",                     "Communication Services", 600,  25.00,  22.15),
        # Consumer Discretionary
        ("MCD",   "McDonald's Corp.",              "Consumer Discretionary",  70, 270.00, 318.90),
        # Real Estate
        ("O",     "Realty Income Corp.",           "Real Estate",            200,  58.00,  55.40),
        ("VICI",  "VICI Properties Inc.",          "Real Estate",            300,  28.00,  29.80),
        ("PLD",   "Prologis Inc.",                 "Real Estate",             60, 115.00, 122.40),
    ],

    # -------------------------------------------------------------------------
    # Diversified — 35-position model portfolio, all 11 GICS sectors represented.
    # Large AUM ($2M+), blends growth and income (advisor / admin view).
    # -------------------------------------------------------------------------
    "diversified": [
        # Technology (22%)
        ("AAPL",  "Apple Inc.",                    "Technology",             500, 130.00, 189.50),
        ("MSFT",  "Microsoft Corp.",               "Technology",             300, 290.00, 415.20),
        ("NVDA",  "NVIDIA Corp.",                  "Technology",             200, 230.00, 875.40),
        ("GOOGL", "Alphabet Inc.",                 "Technology",             100, 102.00, 175.60),
        ("META",  "Meta Platforms Inc.",           "Technology",             100, 200.00, 540.30),
        ("AVGO",  "Broadcom Inc.",                 "Technology",              40, 850.00,1582.00),
        ("ADBE",  "Adobe Inc.",                    "Technology",              50, 480.00, 385.20),
        # Financials (18%)
        ("JPM",   "JPMorgan Chase",                "Financials",             350, 130.00, 225.60),
        ("GS",    "Goldman Sachs",                 "Financials",              90, 380.00, 495.30),
        ("BLK",   "BlackRock Inc.",                "Financials",              40, 800.00, 948.70),
        ("BRK.B", "Berkshire Hathaway B",          "Financials",             180, 262.00, 458.20),
        ("V",     "Visa Inc.",                    "Financials",             110, 218.00, 310.80),
        ("SPGI",  "S&P Global Inc.",               "Financials",              55, 370.00, 488.70),
        # Healthcare (12%)
        ("UNH",   "UnitedHealth Group",            "Healthcare",              80, 530.00, 490.15),
        ("JNJ",   "Johnson & Johnson",             "Healthcare",             250, 148.00, 152.30),
        ("LLY",   "Eli Lilly and Co.",             "Healthcare",              50, 600.00,1088.40),
        ("ABT",   "Abbott Laboratories",           "Healthcare",             120, 105.00, 118.60),
        # Energy (7%)
        ("XOM",   "ExxonMobil",                    "Energy",                 300,  82.00, 117.40),
        ("CVX",   "Chevron Corp.",                 "Energy",                 200, 140.00, 163.20),
        ("SLB",   "SLB (Schlumberger)",            "Energy",                 200,  48.00,  52.60),
        # Consumer Discretionary (8%)
        ("AMZN",  "Amazon.com Inc.",               "Consumer Discretionary", 200, 115.00, 196.80),
        ("HD",    "Home Depot Inc.",               "Consumer Discretionary",  80, 310.00, 395.50),
        ("MCD",   "McDonald's Corp.",              "Consumer Discretionary",  60, 268.00, 318.90),
        # Consumer Staples (6%)
        ("PG",    "Procter & Gamble",              "Consumer Staples",       300, 138.00, 165.80),
        ("COST",  "Costco Wholesale",              "Consumer Staples",        60, 680.00, 895.40),
        ("WMT",   "Walmart Inc.",                  "Consumer Staples",       200,  56.00,  94.20),
        # Industrials (5%)
        ("CAT",   "Caterpillar Inc.",              "Industrials",             60, 260.00, 368.40),
        ("HON",   "Honeywell International",       "Industrials",             80, 195.00, 218.60),
        ("UPS",   "United Parcel Service",         "Industrials",            100, 158.00, 128.30),
        # Utilities (4%)
        ("NEE",   "NextEra Energy",                "Utilities",              180,  68.00,  73.15),
        ("SO",    "Southern Co.",                  "Utilities",              200,  62.00,  88.90),
        # Real Estate (4%)
        ("AMT",   "American Tower Corp.",          "Real Estate",             70, 195.00, 218.80),
        ("PLD",   "Prologis Inc.",                 "Real Estate",             80, 112.00, 122.40),
        # Communication Services (5%)
        ("GOOGL", "Alphabet Inc. (Class C)",       "Communication Services", 100, 102.00, 175.60),
        ("NFLX",  "Netflix Inc.",                  "Communication Services",  30, 375.00, 985.30),
        # Materials (4%)
        ("LIN",   "Linde plc",                    "Materials",               50, 380.00, 465.80),
        ("APD",   "Air Products and Chemicals",    "Materials",               40, 288.00, 312.40),
    ],
}

PERFORMANCE: dict[str, dict] = {
    "growth": {
        "ytd_return_pct": 27.4,
        "one_year_return_pct": 34.8,
        "three_year_annualized_pct": 18.2,
        "benchmark": "S&P 500",
        "benchmark_ytd_pct": 12.1,
        "alpha": 15.3,
        "beta": 1.42,
        "sharpe_ratio": 1.68,
        "max_drawdown_pct": -19.3,
        "volatility_pct": 22.5,
    },
    "conservative": {
        "ytd_return_pct": 6.8,
        "one_year_return_pct": 9.2,
        "three_year_annualized_pct": 7.5,
        "benchmark": "S&P 500",
        "benchmark_ytd_pct": 12.1,
        "alpha": -5.3,
        "beta": 0.62,
        "sharpe_ratio": 1.21,
        "max_drawdown_pct": -5.8,
        "volatility_pct": 9.2,
    },
    "diversified": {
        "ytd_return_pct": 14.7,
        "one_year_return_pct": 22.3,
        "three_year_annualized_pct": 11.8,
        "benchmark": "S&P 500",
        "benchmark_ytd_pct": 12.1,
        "alpha": 2.6,
        "beta": 1.08,
        "sharpe_ratio": 1.42,
        "max_drawdown_pct": -8.3,
        "volatility_pct": 15.2,
    },
}


def _transactions(user_id: str, profile: str) -> list[dict]:
    """
    Generate realistic transaction history for a user.

    Patterns generated per holding:
      1. Initiating BUY (Jan–Jun 2023) — scaled to 60-80% of current position
      2. Add-on BUY on dip (4-6 months later, price ~5-8% below avg cost)
      3. DRIP reinvestment (dividend reinvestment, small buy, every quarter)
      4. Partial SELL for profit-taking on big winners (P&L > 40%)
      5. Top-up BUY near year-end for tax-loss harvesting positions
    Results in 50-80 transactions per user.
    """
    holdings = PROFILES[profile]
    trades: list[dict] = []
    base = date(2023, 1, 3)

    for i, (symbol, name, sector, shares, avg_cost, current_price) in enumerate(holdings):
        spread = i * 5  # stagger entry dates

        # 1. Initial position — buy 70% of current shares
        init_shares = max(1, int(shares * 0.70))
        init_price = round(avg_cost * 0.93, 2)
        init_date = (base + timedelta(days=spread)).isoformat()
        trades.append({
            "user_id": user_id, "symbol": symbol,
            "trade_date": init_date, "trade_type": "BUY",
            "shares": init_shares, "price": init_price,
            "total_amount": round(init_shares * init_price, 2),
        })

        # 2. Add-on BUY ~4 months later on a dip
        addon_date = (base + timedelta(days=spread + 120)).isoformat()
        addon_shares = max(1, int(shares * 0.15))
        addon_price = round(avg_cost * 0.96, 2)
        trades.append({
            "user_id": user_id, "symbol": symbol,
            "trade_date": addon_date, "trade_type": "BUY",
            "shares": addon_shares, "price": addon_price,
            "total_amount": round(addon_shares * addon_price, 2),
        })

        # 3. DRIP — quarterly dividend reinvestment (income / staples / financials)
        if sector in ("Consumer Staples", "Financials", "Utilities",
                      "Healthcare", "Real Estate", "Energy"):
            for q in range(4):
                drip_date = (base + timedelta(days=spread + 90 * (q + 1) + 15)).isoformat()
                drip_shares = max(1, int(shares * 0.01))
                drip_price = round(avg_cost * (1.0 + q * 0.02), 2)
                trades.append({
                    "user_id": user_id, "symbol": symbol,
                    "trade_date": drip_date, "trade_type": "DRIP",
                    "shares": drip_shares, "price": drip_price,
                    "total_amount": round(drip_shares * drip_price, 2),
                })

        # 4. Partial profit-taking SELL if unrealized gain > 40%
        gain_pct = (current_price - avg_cost) / max(avg_cost, 0.01)
        if gain_pct > 0.40 and shares > 10:
            sell_shares = max(1, int(shares * 0.20))
            sell_price = round(avg_cost * (1 + gain_pct * 0.85), 2)
            sell_date = (base + timedelta(days=spread + 270)).isoformat()
            trades.append({
                "user_id": user_id, "symbol": symbol,
                "trade_date": sell_date, "trade_type": "SELL",
                "shares": sell_shares, "price": sell_price,
                "total_amount": round(sell_shares * sell_price, 2),
            })

        # 5. Top-up BUY near year-end (remaining shares to reach current position)
        remaining = max(1, shares - init_shares - addon_shares)
        if remaining > 0:
            topup_date = (base + timedelta(days=spread + 355)).isoformat()
            topup_price = round(avg_cost * 1.02, 2)
            trades.append({
                "user_id": user_id, "symbol": symbol,
                "trade_date": topup_date, "trade_type": "BUY",
                "shares": remaining, "price": topup_price,
                "total_amount": round(remaining * topup_price, 2),
            })

    # Sort chronologically
    trades.sort(key=lambda t: t["trade_date"])
    return trades


# ---------------------------------------------------------------------------
# Database creation
# ---------------------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS portfolios (
    user_id      TEXT PRIMARY KEY,
    display_name TEXT,
    email        TEXT,
    profile      TEXT,
    total_value  REAL,
    cash         REAL,
    created_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS holdings (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           TEXT NOT NULL,
    symbol            TEXT NOT NULL,
    name              TEXT,
    sector            TEXT,
    shares            INTEGER NOT NULL,
    avg_cost          REAL NOT NULL,
    current_price     REAL NOT NULL,
    market_value      REAL NOT NULL,
    unrealized_pnl    REAL NOT NULL,
    unrealized_pnl_pct REAL NOT NULL,
    weight_pct        REAL NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES portfolios(user_id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    trade_date   TEXT NOT NULL,
    trade_type   TEXT NOT NULL,
    shares       REAL NOT NULL,
    price        REAL NOT NULL,
    total_amount REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES portfolios(user_id)
);

CREATE TABLE IF NOT EXISTS performance (
    user_id                   TEXT PRIMARY KEY,
    ytd_return_pct            REAL,
    one_year_return_pct       REAL,
    three_year_annualized_pct REAL,
    benchmark                 TEXT DEFAULT 'S&P 500',
    benchmark_ytd_pct         REAL DEFAULT 12.1,
    alpha                     REAL,
    beta                      REAL,
    sharpe_ratio              REAL,
    max_drawdown_pct          REAL,
    volatility_pct            REAL,
    FOREIGN KEY (user_id) REFERENCES portfolios(user_id)
);

CREATE INDEX IF NOT EXISTS idx_holdings_user   ON holdings(user_id);
CREATE INDEX IF NOT EXISTS idx_txn_user        ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_txn_user_symbol ON transactions(user_id, symbol);
"""


def seed(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(DDL)

    for user in USERS:
        uid = user["user_id"]
        profile = user["profile"]
        raw_holdings = PROFILES[profile]

        # Compute portfolio value
        total_value = sum(shares * curr for _, _, _, shares, _, curr in raw_holdings)
        cash = round(total_value * 0.05, 2)

        # Upsert portfolio row
        conn.execute(
            """INSERT INTO portfolios (user_id, display_name, email, profile, total_value, cash)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   display_name=excluded.display_name,
                   total_value=excluded.total_value,
                   cash=excluded.cash,
                   updated_at=datetime('now')
            """,
            (uid, user["display_name"], user["email"], profile, round(total_value, 2), cash),
        )

        # Clear and re-seed holdings
        conn.execute("DELETE FROM holdings WHERE user_id = ?", (uid,))
        for symbol, name, sector, shares, avg_cost, current_price in raw_holdings:
            market_value = round(shares * current_price, 2)
            cost_basis = round(shares * avg_cost, 2)
            unr_pnl = round(market_value - cost_basis, 2)
            unr_pct = round((market_value - cost_basis) / max(cost_basis, 0.01) * 100, 2)
            weight = round(market_value / total_value * 100, 2)
            conn.execute(
                """INSERT INTO holdings
                   (user_id, symbol, name, sector, shares, avg_cost, current_price,
                    market_value, unrealized_pnl, unrealized_pnl_pct, weight_pct)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (uid, symbol, name, sector, shares, avg_cost, current_price,
                 market_value, unr_pnl, unr_pct, weight),
            )

        # Clear and re-seed transactions
        conn.execute("DELETE FROM transactions WHERE user_id = ?", (uid,))
        for txn in _transactions(uid, profile):
            conn.execute(
                """INSERT INTO transactions (user_id, symbol, trade_date, trade_type, shares, price, total_amount)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (txn["user_id"], txn["symbol"], txn["trade_date"], txn["trade_type"],
                 txn["shares"], txn["price"], txn["total_amount"]),
            )

        # Upsert performance
        perf = PERFORMANCE[profile]
        conn.execute(
            """INSERT INTO performance
               (user_id, ytd_return_pct, one_year_return_pct, three_year_annualized_pct,
                benchmark, benchmark_ytd_pct, alpha, beta, sharpe_ratio, max_drawdown_pct, volatility_pct)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   ytd_return_pct=excluded.ytd_return_pct,
                   one_year_return_pct=excluded.one_year_return_pct,
                   three_year_annualized_pct=excluded.three_year_annualized_pct,
                   alpha=excluded.alpha, beta=excluded.beta,
                   sharpe_ratio=excluded.sharpe_ratio,
                   max_drawdown_pct=excluded.max_drawdown_pct,
                   volatility_pct=excluded.volatility_pct
            """,
            (uid, perf["ytd_return_pct"], perf["one_year_return_pct"],
             perf["three_year_annualized_pct"], perf["benchmark"], perf["benchmark_ytd_pct"],
             perf["alpha"], perf["beta"], perf["sharpe_ratio"],
             perf["max_drawdown_pct"], perf["volatility_pct"]),
        )

        h_count = conn.execute("SELECT COUNT(*) FROM holdings WHERE user_id=?", (uid,)).fetchone()[0]
        t_count = conn.execute("SELECT COUNT(*) FROM transactions WHERE user_id=?", (uid,)).fetchone()[0]
        print(f"  {uid:<50}  holdings={h_count:2d}  txns={t_count:2d}  value=${total_value:,.0f}")

    conn.commit()
    conn.close()
    print(f"\nLocal portfolio database written to: {db_path}")
    print("Set DB_PATH env var on the MCP server to enable SQLite-backed RLS queries.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed local portfolio SQLite database")
    parser.add_argument(
        "--db",
        default=str(Path(__file__).parent.parent / "data" / "portfolio.db"),
        help="Path to output SQLite file (default: data/portfolio.db)",
    )
    args = parser.parse_args()
    print(f"Seeding {args.db} ...\n")
    seed(args.db)
