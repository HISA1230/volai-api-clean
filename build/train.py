import json
import sys

def main():
    # 形式だけ整えたダミー結果を標準出力へ
    payload = {
        "model": "models/latest.pkl",
        "metrics": {
            "mse": 1.0, "rmse": 1.0,
            "baseline_mse": 1.0, "baseline_rmse": 1.0,
            "start": "2000-01-01 00:00:00", "end": "2000-01-02 00:00:00",
            "_promoted": False
        }
    }
    print(json.dumps(payload))

if __name__ == "__main__":
    main()
