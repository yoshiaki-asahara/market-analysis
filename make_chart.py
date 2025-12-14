import json
import sys
import requests

from IPython.display import display
import pandas as pd
import re
from pathlib import Path
import yaml

API_URL = "https://api.jquants.com"

def debug(msg: str):
    """シンプルなデバッグ出力（タイムスタンプ付き）"""
    try:
        ts = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[DEBUG {ts}] {msg}")
    except Exception:
        print(f"[DEBUG] {msg}")

def make_chart(headers, code: str, company_name: str, output_dir: Path, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
    """
    価格チャート用の時系列データ（日足）を取得して整形して返す。

    Args:
        headers: API 認証ヘッダ（Bearer トークン）
        code (str): 銘柄コード
        start_date (str | None): 開始日（YYYY-MM-DD）。未指定ならAPIデフォルト。
        end_date (str | None): 終了日（YYYY-MM-DD）。未指定ならAPIデフォルト。
    """
    debug(f"make_chart start: code={code}, company_name={company_name}, start_date={start_date}, end_date={end_date}")
    delay_days = 12*7  # J-Quants APIのFreeプランのため12週間遅延
    lookback_days = 180

    # 取得期間を決定
    if start_date or end_date:
        from_date = start_date or (pd.Timestamp.today() - pd.Timedelta(days=lookback_days + delay_days)).strftime("%Y-%m-%d")
        to_date = end_date or (pd.Timestamp.today().normalize() - pd.Timedelta(days=delay_days)).strftime("%Y-%m-%d")
    else:
        to_date = (pd.Timestamp.today().normalize() - pd.Timedelta(days=delay_days)).strftime("%Y-%m-%d")
        from_date = (pd.Timestamp.today() - pd.Timedelta(days=lookback_days + delay_days)).strftime("%Y-%m-%d")
    debug(f"fetch range: from={from_date}, to={to_date}")

    # API 呼び出し
    url = f"{API_URL}/v1/prices/daily_quotes"
    params = {"code": code, "from": from_date, "to": to_date}
    try:
        res = requests.get(url, headers=headers, params=params, timeout=30)
        if res.status_code != 200:
            return pd.DataFrame()
        data = res.json()
    except Exception:
        return pd.DataFrame()

    quotes = data.get("daily_quotes") or data.get("data") or []
    if not quotes:
        return pd.DataFrame()

    # 整形
    df = pd.DataFrame(quotes)
    # 必須カラムの存在チェック
    required = ["Date", "Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return pd.DataFrame()

    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)

    # 列名整形と選択
    df = df.rename(columns={
        "Date": "date",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume"
    })[["date", "open", "high", "low", "close", "volume"]]

    # 簡単な指標（任意）
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()

    # プロットして画像を保存
    try:
        import matplotlib.pyplot as plt

        fig, ax_price = plt.subplots(figsize=(10, 6))
        ax_price.plot(df["date"], df["close"], label="Close", color="tab:blue", linewidth=1.5)
        ax_price.plot(df["date"], df["ma20"], label="MA20", color="tab:orange", linewidth=1.2)
        ax_price.plot(df["date"], df["ma60"], label="MA60", color="tab:green", linewidth=1.2)
        ax_price.set_title(f"{code} Price Chart")
        ax_price.set_xlabel("Date")
        ax_price.set_ylabel("Price")
        ax_price.grid(True, alpha=0.3)
        ax_price.legend(loc="upper left")

        ax_vol = ax_price.twinx()
        ax_vol.bar(df["date"], df["volume"], label="Volume", color="lightgray", alpha=0.6, width=2)
        ax_vol.set_ylabel("Volume")
        ax_vol.legend(loc="upper right")

        out_img = output_dir / f"{code}_{company_name}.png"
        fig.autofmt_xdate()
        plt.tight_layout()
        fig.savefig(out_img, dpi=150)
        plt.close(fig)
    except Exception:
        pass
    return df


def main():
    # config.yaml から refreshtoken を取得
    cfg_path = Path(__file__).with_name("config.yaml")
    if not cfg_path.exists():
        print(f"config.yaml not found at: {cfg_path}")
        sys.exit(1)
    try:
        with cfg_path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Failed to read config.yaml: {e}")
        sys.exit(1)

    # キーの揺れに対応
    refreshtoken = cfg.get("refreshtoken")

    if not refreshtoken:
        print("Refresh token not found in config.yaml or environment.")
        sys.exit(1)
    # idToken取得
    res = requests.post(f"{API_URL}/v1/token/auth_refresh?refreshtoken={refreshtoken}", timeout=30)
    if res.status_code == 200:
        id_token = res.json().get('idToken')
        headers = {'Authorization': f'Bearer {id_token}'}
        display("idTokenの取得に成功しました。")
        debug("idToken fetched successfully.")
    else:
        msg = res.json().get("message", f"HTTP {res.status_code}")
        display(msg)
        print("Failed to fetch idToken.")
        sys.exit(1)

    # cfg から lookback_days を取得し、既定の取得期間を差し替える
    lb = int(cfg.get("lookback_days", 180))
    delay_days = 12 * 7
    start_date = (pd.Timestamp.today() - pd.Timedelta(days=lb + delay_days)).strftime("%Y-%m-%d")
    end_date = (pd.Timestamp.today().normalize() - pd.Timedelta(days=delay_days)).strftime("%Y-%m-%d")

    # tikers.txt からティッカーコードを読み込み（1 行 1 コード、# で始まる行はコメント扱い）
    tickers_path = Path(__file__).with_name("search_result.txt")
    company_names = {}

    if tickers_path.exists():
        try:
            with tickers_path.open("r", encoding="utf-8-sig") as f:
                for line in f:
                    s = line.strip()
                    if not s or s.startswith("#"):
                        continue
                    parts = [p.strip() for p in re.split(r"[,\t]", s) if p.strip()]
                    code = parts[0] if parts else ""
                    name = parts[1] if len(parts) > 1 else ""
                    if code:
                        company_names[code] = name
            debug(f"Loaded {len(company_names)} tickers from search_result.txt")
        except Exception as e:
            debug(f"Failed to read tickers: {e}")
            company_names = {}
    else:
        debug("search_result.txt not found; no tickers loaded.")

    # チャートデータの保存先ディレクトリを作成
    output_dir = Path(__file__).with_name("charts")
    output_dir.mkdir(exist_ok=True)

    # ティッカーごとにチャート作成
    results = {}
    for code, company_name in company_names.items():
        try:
            df = make_chart(headers, code, company_name, start_date, end_date,output_dir)
            if not df.empty:
                results[code] = df
                print(f"Processed: {code} {company_name}")
            else:
                print(f"No data: {code} {company_name}")
        except Exception as e:
            debug(f"Processing failed for {code} {company_name}: {e}")
            print(f"Failed: {code} {company_name} - {e}")


if __name__ == "__main__":
    main()