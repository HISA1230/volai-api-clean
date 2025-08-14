# utils/notifier.py
import os, json, re, requests, smtplib, ssl, certifi
from email.mime.text import MIMEText

# --- Windowsの証明書ストアを使う（Python 3.13 では certifi-win32 が無いため truststore を採用） ---
try:
    import truststore
    TRUSTSTORE = os.getenv("SMTP_USE_TRUSTSTORE", "true").lower() == "true"
    if TRUSTSTORE:
        # 以降の ssl.create_default_context() が OS の証明書ストアを使うように注入
        truststore.inject_into_ssl()
except Exception:
    TRUSTSTORE = False
# ------------------------------------------------------------------------------------------------------

def notify_slack(text: str):
    url = os.getenv("SLACK_WEBHOOK_URL")
    if not url:
        return {"ok": False, "reason": "no_webhook"}
    try:
        r = requests.post(url, json={"text": text}, timeout=10)
        return {"ok": r.ok, "status": r.status_code, "text": (r.text or "")[:200]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _parse_list(var_name: str):
    raw = os.getenv(var_name, "")
    return [e.strip() for e in re.split(r"[;,]", raw) if e.strip()]

def notify_email(subject: str, body: str):
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    pwd  = os.getenv("SMTP_PASS")
    rcpts = _parse_list("SMTP_TO")
    use_ssl = os.getenv("SMTP_SSL", "false").lower() == "true"
    verify  = os.getenv("SMTP_SSL_VERIFY", "true").lower() == "true"

    # truststore が有効なら OS ストアを使用（= ca_bundle は None）
    # 明示の CA バンドルが .env で指定されていればそれを優先
    ca_bundle = os.getenv("SMTP_CA_BUNDLE") or (None if TRUSTSTORE else certifi.where())

    if not (host and user and pwd and rcpts):
        return {"ok": False, "reason": "smtp_incomplete_or_no_recipients"}

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = ", ".join(rcpts)

    ctx = ssl.create_default_context()
    if verify:
        if ca_bundle:
            try:
                ctx.load_verify_locations(cafile=ca_bundle)
            except Exception:
                # certifi/外部CA読み込み失敗 → truststore 注入済みなら OS ストアで検証継続
                pass
    else:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # ← スペル注意

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
                s.login(user, pwd)
                s.sendmail(user, rcpts, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls(context=ctx)
                s.login(user, pwd)
                s.sendmail(user, rcpts, msg.as_string())
        return {"ok": True, "recipients": rcpts, "verify": verify, "truststore": TRUSTSTORE}
    except Exception as e:
        return {"ok": False, "error": str(e), "verify": verify, "truststore": TRUSTSTORE}

def notify_line(text: str):
    token = os.getenv("LINE_TOKEN")
    if not token:
        return {"ok": False, "reason": "no_line_token"}
    try:
        r = requests.post(
            "https://notify-api.line.me/api/notify",
            headers={"Authorization": f"Bearer {token}"},
            data={"message": text},
            timeout=10
        )
        return {"ok": r.ok, "status": r.status_code, "text": (r.text or "")[:200]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def notify_all(title: str, payload: dict):
    # Slackでも読みやすいようにコードフェンスで整形
    body = f"{title}\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    res = {
        "slack": notify_slack(body),
        "email": notify_email(title, body),
        "line":  notify_line(f"{title}\n{json.dumps(payload, ensure_ascii=False)}")
    }
    res["ok_any"] = any(v.get("ok") for v in res.values())
    return res
