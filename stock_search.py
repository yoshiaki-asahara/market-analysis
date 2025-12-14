import json
import sys
import requests

from IPython.display import display
import pandas as pd
from pathlib import Path
import yaml
from get_param import get_param
import traceback

API_URL = "https://api.jquants.com"

# 固定パラメータ（引数ではなくコード内に埋め込み）
# 例: ティッカー、財務諸表の種類、期間を固定値として設定
TICKER = "186A0"
STATEMENT = "income_statement"  # 他の選択肢: "balance_sheet", "cash_flow"
PERIOD = "annual"               # 他の選択肢: "quarterly"


def get_financial_data(headers,ticker: str, statement: str, period: str) -> pd.DataFrame:
    """
    指定した企業の財務データを取得する関数。

    Args:
        ticker (str): 企業のティッカーシンボル。
        statement (str): 財務諸表の種類（例：'income_statement', 'balance_sheet', 'cash_flow'）。
        period (str): 期間の種類（例：'annual', 'quarterly'）。

    """

    endpoint = f"{API_URL}/v1/financials/{statement}"
    params = {"code": ticker, "type": period}
    resp = requests.get(endpoint, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get("data") or payload.get("results") or []
    return pd.DataFrame(data)

def get_all_info(headers) -> pd.DataFrame:
    """
    listed/info を使って全企業の情報を取得する。
    """
    endpoint = f"{API_URL}/v1/listed/info"
    resp = requests.get(endpoint, headers=headers, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    return payload.get("info")

def search_drawdown(headers, tickers, lookback_days, threshold, top_n) -> list[str]:
    """
    指定期間の最大ドローダウンが閾値以下の銘柄を抽出して返す。

    戻り値:
        List[str]: 条件を満たしたティッカーのリスト（ドローダウンが大きい順に上位のみ）
    """
    delay_days = 12*7 # J-Quants APIのFreeプランのため12週間遅延
    to_date = (pd.Timestamp.today().normalize() - pd.Timedelta(days=delay_days)).strftime("%Y-%m-%d")
    from_date = (pd.Timestamp.today() - pd.Timedelta(days=lookback_days + delay_days)).strftime("%Y-%m-%d")

    results = []
    session = requests.Session()

    for code in tickers:
        print(f"Processing {code}...")
        try:
            resp = session.get(
                f"{API_URL}/v1/prices/daily_quotes",
                headers=headers,
                params={"code": code, "from": from_date, "to": to_date},
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()
            quotes = payload.get("daily_quotes") or payload.get("data") or payload.get("quotes") or []
            if not quotes:
                continue

            df = pd.DataFrame(quotes)

            # 日付でソート
            date_col = "Date" if "Date" in df.columns else ("date" if "date" in df.columns else None)
            if date_col:
                df = df.sort_values(date_col)

            s = pd.to_numeric(df["AdjustmentClose"], errors="coerce").dropna()
            # データ数が少ない場合はスキップ
            if s.size < 30:
                continue

            # 過去の最高価格と現在価格でドローダウンを算出
            peak_price = s.max() # 期間内の過去最高値
            current_price = s.iloc[-1]

            current_dd = current_price / peak_price  # 現在のドローダウン

            if current_dd <= threshold:
                print(f"  {code}: Found drawdown: {current_dd:.2%}")
                results.append({
                    "Code": code,
                    "max_drawdown": float(current_dd),
                })

        except Exception as e:
            print(f"  Error processing {code}: {e}")
            traceback.print_exc()
            continue

    results.sort(key=lambda x: x["max_drawdown"])  # 最も大きいドローダウン順（より負）に並べる

    return [r["Code"] for r in results[:top_n]]

def main():
    # refreshtokenを取得
    try:
        refreshtoken = get_param("refreshtoken")
    except Exception as e:
        print(f"Failed to retrieve refreshtoken: {e}")
        sys.exit(1)
    if not isinstance(refreshtoken, str) or not refreshtoken.strip():
        print("refreshtoken is missing or invalid.")
        sys.exit(1)
    refreshtoken = refreshtoken.strip()

    # idToken取得
    res = requests.post(f"{API_URL}/v1/token/auth_refresh?refreshtoken={refreshtoken}")
    if res.status_code == 200:
        id_token = res.json()['idToken']
        headers = {'Authorization': 'Bearer {}'.format(id_token)}
        display("idTokenの取得に成功しました。")
    else:
        display(res.json()["message"])

    # 全企業情報のティッカー取得
    infos = get_all_info(headers)
    all_tickers = [info["Code"] for info in infos]

    lookback_days = get_param("lookback_days")
    threshold = get_param("threshold")
    top_n = get_param("top_n")

    # 検索フィルタ（ロジックで関数を入れ替える）
    filtered_tickers = search_drawdown(headers, all_tickers, lookback_days=lookback_days, threshold=threshold, top_n=top_n)

    # ティッカーと会社名のペアをファイルに保存
    code_to_name = {info["Code"]: info.get("CompanyName") or info.get("CompanyNameEnglish") or "" for info in infos}
    lines = [f"{code},{code_to_name.get(code, '')}" for code in filtered_tickers]
    with open("search_result.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    display(f"Wrote {len(filtered_tickers)} ticker-name pairs to search_result.txt")

if __name__ == "__main__":
    main()