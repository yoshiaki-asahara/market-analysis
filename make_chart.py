import json
import sys
import requests

from IPython.display import display
import pandas as pd

API_URL = "https://api.jquants.com"

# 固定パラメータ（引数ではなくコード内に埋め込み）
# 例: ティッカー、財務諸表の種類、期間を固定値として設定
TICKER = "186A0"
STATEMENT = "income_statement"  # 他の選択肢: "balance_sheet", "cash_flow"
PERIOD = "annual"               # 他の選択肢: "quarterly"

def search_drawdown(headers, tickers, top_n=20, lookback_days=252, threshold=0.3):
    """
    価格データから最大ドローダウンが閾値以上の銘柄を抽出する。
    Args:
        headers: 認証ヘッダ（Bearer idToken）
        tickers: ティッカーのリスト
        top_n: 上位何件返すか
        lookback_days: 直近何営業日で計算するか
        threshold: 最大ドローダウンの閾値（例: 0.3=30%）
    Returns:
        ドローダウンが大きい順のティッカーリスト
    """
    results = []
    for code in tickers:
        try:
            endpoint = f"{API_URL}/v1/prices/daily_quotes"
            resp = requests.get(endpoint, headers=headers, params={"code": code}, timeout=30)
            if resp.status_code != 200:
                continue
            payload = resp.json()
            rows = payload.get("daily_quotes") or payload.get("data") or payload.get("results") or []
            if not rows:
                continue

            df = pd.DataFrame(rows)

            # 価格列の推定
            price_col = None
            for col in ("Close", "EndPrice", "ClosePrice", "close", "endPrice"):
                if col in df.columns:
                    price_col = col
                    break
            if not price_col:
                continue

            # 日付列の推定
            date_col = None
            for col in ("Date", "date", "BaseDate"):
                if col in df.columns:
                    date_col = col
                    break

            if date_col:
                df = df.sort_values(by=date_col)

            # 直近期間に絞る
            df = df.tail(lookback_days)

            prices = pd.to_numeric(df[price_col], errors="coerce").dropna()
            if prices.empty:
                continue

            # 最大ドローダウン計算
            roll_max = prices.cummax()
            drawdown_series = prices / roll_max - 1.0
            mdd = drawdown_series.min()  # 負値
            mdd_abs = abs(mdd)

            if mdd_abs >= threshold:
                results.append((code, mdd_abs))
        except Exception:
            continue

    results.sort(key=lambda x: x[1], reverse=True)
    return [code for code, _ in results[:top_n]]


def get_all_tickers(headers) -> pd.DataFrame:
    """
    listed/info を使って全企業の情報を取得する。
    """
    endpoint = f"{API_URL}/v1/listed/info"
    resp = requests.get(endpoint, headers=headers, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    infos = payload.get("info")
    tickers = [info["Code"] for info in infos]
    return tickers


def main():
    pd.set_option("display.max_columns", None)

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
    res = requests.post(f"{API_URL}/v1/token/auth_refresh?refreshtoken={refreshtoken}")
    if res.status_code == 200:
        id_token = res.json()['idToken']
        headers = {'Authorization': 'Bearer {}'.format(id_token)}
        display("idTokenの取得に成功しました。")
    else:
        display(res.json()["message"])

    # 全企業情報のティッカー取得
    all_tickers = get_all_tickers(headers)

    # 検索フィルタ（ロジックで関数を入れ替える）
    filtered_tickers = search_drawdown(headers, all_tickers)

    with open("tickers.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(map(str, filtered_tickers)))
    display(f"Wrote {len(filtered_tickers)} tickers to tickers.txt")

if __name__ == "__main__":
    main()