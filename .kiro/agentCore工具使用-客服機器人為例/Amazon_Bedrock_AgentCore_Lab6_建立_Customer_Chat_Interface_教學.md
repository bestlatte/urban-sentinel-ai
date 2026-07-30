# Amazon Bedrock AgentCore Lab 6：建立 Customer Chat Interface

## 0. 本 Lab 要完成什麼？

前面的 Lab 已經完成：

- Lab 1：建立 Agent Prototype
- Lab 2：加入跨 Session Memory
- Lab 3：使用 Gateway 集中管理 Tool
- Lab 4：加入 Cognito JWT、Session 與 Observability
- Lab 5：加入持續品質評估

本 Lab 會建立一個使用 Flask 的 Web Chat Interface，讓使用者透過瀏覽器登入並與已部署的 CustomerSupport Agent 對話。

完成後，你會得到：

- Cognito Hosted UI 登入頁
- Flask Backend
- Web Chat Interface
- Agent Runtime 自動探索
- Authorization Code Flow
- Browser Session ID
- Quick Action Buttons
- Logout 功能

---

# 1. 完成後的架構

```text
Browser
  │
  │ http://localhost:8501
  ▼
Flask Backend
  ├── 顯示 Login Page
  ├── 重新導向 Cognito Hosted UI
  ├── 接收 Authorization Code
  ├── 交換 Cognito Access Token
  ├── 讀取 deployed-state.json
  └── 呼叫 AgentCore Runtime REST API
          │
          │ Authorization: Bearer <JWT>
          ▼
AgentCore Runtime
  ├── Session Management
  ├── AgentCore Memory
  ├── Local Tools
  ├── Exa AI MCP
  └── Secure AgentCore Gateway
          │
          ▼
      Warranty Lambda

CloudWatch + AgentCore Evaluations
```

---

# 2. 前置條件

開始前請確認：

- 已完成 Lab 1～5
- `CustomerSupport` Runtime 已部署
- Runtime 已設定 Cognito JWT
- Gateway 已設定 Cognito JWT
- Cognito Web Client 已存在
- 測試使用者已建立
- `agentcore status` 顯示資源正常
- AWS Credential 尚未過期
- Terminal 位於 `CustomerSupport` 專案根目錄

---

# 3. Step 1：安裝 Flask 相關依賴

進入 Agent 專案：

```powershell
cd app\CustomerSupport
```

安裝套件：

```powershell
uv add flask boto3 requests
```

回到專案根目錄：

```powershell
cd ..\..
```

---

## 3.1 套件用途

| 套件 | 用途 |
|---|---|
| `flask` | 建立 Web Server 與 Route |
| `boto3` | 讀取部分 AWS 資源或設定 |
| `requests` | 呼叫 Cognito 與 AgentCore REST API |

---

## 3.2 為什麼呼叫 AgentCore Runtime 使用 `requests`？

本 Lab 使用 Cognito JWT Bearer Token 呼叫 AgentCore Runtime。

工作坊說明指出：

```text
boto3 的 invoke_agent_runtime
不支援 JWT Bearer Token 呼叫方式
```

因此後端改用：

```python
requests
```

直接呼叫 AgentCore REST API，並帶入：

```http
Authorization: Bearer <ACCESS_TOKEN>
```

---

# 4. Step 2：允許 Web Client 存取 Runtime 與 Gateway

Lab 4 已設定 Cognito Authorizer，但 Frontend 使用的是支援 Authorization Code Flow 的 Web Client。

因此 Runtime 與 Gateway 的：

```json
allowedClients
```

都必須包含 Web Client ID。

---

## 4.1 取得 Web Client ID

```powershell
$WEB_CLIENT_ID = aws ssm get-parameter `
  --name "/app/customersupport/agentcore/web_client_id" `
  --query "Parameter.Value" `
  --output text
```

確認：

```powershell
Write-Host "Web Client ID: $WEB_CLIENT_ID"
```

---

## 4.2 修改 `agentcore.json`

開啟：

```text
agentcore/agentcore.json
```

找到兩個 `allowedClients`：

1. CustomerSupport Runtime
2. Secure AgentCore Gateway

將 Web Client ID 加入：

```json
"allowedClients": [
  "<existing-m2m-client-id>",
  "<WEB_CLIENT_ID>"
]
```

Runtime 與 Gateway 都要加入。

---

## 4.3 驗證設定

```powershell
agentcore validate
```

---

## 4.4 部署更新

```powershell
agentcore deploy -y -v
```

這次部署會更新：

- Runtime JWT Allowed Clients
- Gateway JWT Allowed Clients
- Cognito Web Client 存取權

---

# 5. Step 3：建立 Frontend 目錄

執行：

```powershell
New-Item `
  -ItemType Directory `
  -Path app\CustomerSupport\frontend\templates `
  -Force
```

建立 Python Package：

```powershell
New-Item `
  app\CustomerSupport\frontend\__init__.py `
  -ItemType File `
  -Force
```

建立 Flask Backend：

```powershell
New-Item `
  app\CustomerSupport\frontend\frontend.py `
  -ItemType File `
  -Force
```

建立 Login Page：

```powershell
New-Item `
  app\CustomerSupport\frontend\templates\login.html `
  -ItemType File `
  -Force
```

建立 Chat Page：

```powershell
New-Item `
  app\CustomerSupport\frontend\templates\index.html `
  -ItemType File `
  -Force
```

完成後：

```text
app/
└── CustomerSupport/
    ├── frontend/
    │   ├── __init__.py
    │   ├── frontend.py
    │   └── templates/
    │       ├── login.html
    │       └── index.html
    ├── main.py
    ├── memory/
    ├── model/
    ├── mcp_client/
    ├── tool/
    └── pyproject.toml
```

---

# 6. Step 4：Flask Backend 應負責什麼？

檔案：

```text
app/CustomerSupport/frontend/frontend.py
```

它應處理：

- Flask App 初始化
- Session Secret 設定
- Cognito Hosted UI Login URL
- OAuth Callback
- Authorization Code 交換 Access Token
- Access Token 保存
- Logout
- Agent Runtime ARN 自動探索
- `/chat` API
- 使用 JWT 呼叫 AgentCore REST API

---

## 6.1 自動找到 Runtime ARN

工作坊中的 `get_runtime_arn()` 會讀取：

```text
agentcore/.cli/deployed-state.json
```

從部署狀態中找出：

```text
CustomerSupport Runtime ARN
```

這樣就不必把 Runtime ARN 寫死在程式中。

---

## 6.2 Cognito Authorization Code Flow

流程：

```text
使用者開啟 Flask 網頁
    ↓
Flask 重新導向 Cognito Hosted UI
    ↓
使用者登入
    ↓
Cognito 回傳 Authorization Code
    ↓
Flask 用 Code 交換 Access Token
    ↓
Token 保存於 Flask Session
    ↓
使用 Token 呼叫 AgentCore Runtime
```

---

## 6.3 `/chat` Route

Browser 傳送：

```json
{
  "prompt": "Check warranty for PROD-002",
  "session_id": "UUID"
}
```

Flask Backend 應：

1. 從 Session 取得 Access Token
2. 取得 Runtime ARN
3. 建立 Runtime Invoke URL
4. 加入 Authorization Header
5. 傳送 Prompt 與 Session ID
6. 讀取 Runtime 回應
7. 回傳 JSON 給 Browser

---

## 6.4 原文件缺少 `frontend.py` 完整程式

原始工作坊文字只顯示：

```text
Click to see frontend.py code
```

但你提供的內容沒有包含展開後的完整程式碼。

因此目前必須另外保存：

- Workshop 中展開的 `frontend.py`
- 或已建立完成的 `frontend.py`
- Cognito Domain 與 Callback URL 設定

不要只保存這份整理文件，否則 Lab 6 的核心 Backend 仍缺一塊。

---

# 7. Step 5：建立 Login Page

檔案：

```text
app/CustomerSupport/frontend/templates/login.html
```

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
  >
  <title>Customer Support - Sign In</title>

  <style>
    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }

    body {
      font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        Roboto,
        sans-serif;
      background:
        linear-gradient(
          180deg,
          #d6eaf8 0%,
          #ebf0f5 40%,
          #f5f7fa 100%
        );
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .login-card {
      background: white;
      border-radius: 16px;
      padding: 48px 40px;
      box-shadow: 0 4px 24px rgba(0, 0, 0, 0.08);
      text-align: center;
      max-width: 400px;
      width: 100%;
    }

    .login-card h1 {
      font-size: 24px;
      font-weight: 600;
      color: #1a1a2e;
      margin-bottom: 8px;
    }

    .login-card p {
      color: #666;
      font-size: 14px;
      margin-bottom: 32px;
      line-height: 1.5;
    }

    .login-card .avatar {
      width: 64px;
      height: 64px;
      background:
        linear-gradient(
          135deg,
          #667eea,
          #764ba2
        );
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      color: white;
      font-size: 28px;
      margin: 0 auto 24px;
    }

    .login-btn {
      display: inline-block;
      padding: 14px 32px;
      background: #1a1a2e;
      color: white;
      text-decoration: none;
      border-radius: 28px;
      font-size: 15px;
      font-weight: 500;
    }

    .login-btn:hover {
      background: #2d2d4e;
    }

    .footer {
      margin-top: 24px;
      font-size: 11px;
      color: #aaa;
    }
  </style>
</head>

<body>
  <div class="login-card">
    <div class="avatar">🤖</div>

    <h1>Customer Support Agent</h1>

    <p>
      Sign in to chat with your AI-powered
      customer support assistant.
    </p>

    <a
      href="{{ login_url }}"
      class="login-btn"
    >
      Sign in with Cognito
    </a>

    <div class="footer">
      Powered by Amazon Bedrock AgentCore
    </div>
  </div>
</body>
</html>
```

---

## 7.1 `login_url` 從哪裡來？

Flask Route 應透過：

```python
render_template(
    "login.html",
    login_url=login_url,
)
```

將 Cognito Hosted UI URL 傳給 Template。

---

# 8. Step 6：建立 Chat Page

檔案：

```text
app/CustomerSupport/frontend/templates/index.html
```

此頁面包含：

- Runtime 連線狀態
- 使用者名稱
- Logout
- New Session
- Chat Message
- Thinking Animation
- Input Box
- Quick Actions
- Browser Session ID
- `/chat` Fetch Request

---

## 8.1 Template 變數

Backend 應傳入：

```text
runtime_arn
username
```

HTML 中使用：

```html
{{ runtime_arn }}
{{ username }}
```

---

## 8.2 Session ID

Browser 啟動時建立：

```javascript
let sessionId = crypto.randomUUID();
```

這個 UUID 會在每次傳送訊息時送給 Backend。

相同 Browser Session ID：

```text
維持同一段 Agent 對話
```

點擊 New Session：

```javascript
function newSession() {
  sessionId = crypto.randomUUID();
}
```

會開始新的 Agent Session。

---

## 8.3 呼叫 `/chat`

```javascript
const resp = await fetch("/chat", {
  method: "POST",
  headers: {
    "Content-Type": "application/json"
  },
  body: JSON.stringify({
    prompt: msg,
    session_id: sessionId
  })
});
```

Backend 預期收到：

```json
{
  "prompt": "使用者問題",
  "session_id": "UUID"
}
```

---

## 8.4 Quick Actions

頁面提供：

```text
Products
Returns
Warranty
Memory
```

分別測試：

- Local Product Tool
- Local Return Policy Tool
- Gateway Warranty Tool
- AgentCore Memory

---

# 9. Step 7：啟動 Flask App

進入 Frontend：

```powershell
cd app\CustomerSupport\frontend
```

啟動：

```powershell
uv run python frontend.py
```

預期輸出：

```text
Runtime ARN:
arn:aws:bedrock-agentcore:...

Running on:
http://127.0.0.1:8501
```

---

# 10. Step 8：開啟瀏覽器

開啟：

```text
http://localhost:8501
```

會先看到 Login Page。

點擊：

```text
Sign in with Cognito
```

---

# 11. Step 9：使用 Cognito 帳號登入

使用 Lab 4 建立的測試帳號：

```text
Email：
workshopuser@example.com

Password：
WorkshopPass1!
```

登入後流程：

```text
Cognito Hosted UI
    ↓
Callback 到 Flask
    ↓
交換 Access Token
    ↓
重新導向 Chat Interface
```

---

# 12. Step 10：測試 Chat Interface

## 12.1 商品查詢

```text
Tell me about the Wireless Headphones
```

預期使用：

```text
get_product_info
```

---

## 12.2 退貨政策

```text
What's the return policy for electronics?
```

預期使用：

```text
get_return_policy
```

---

## 12.3 Warranty Gateway

```text
Check warranty for PROD-002
```

預期流程：

```text
Flask
→ Runtime
→ Secure Gateway
→ Warranty Lambda
```

---

## 12.4 Memory

```text
Do you remember me?
```

預期使用：

```text
AgentCore Memory
```

---

## 12.5 Session Continuity

第一句：

```text
My name is Alex
```

第二句：

```text
What's my name?
```

兩句使用相同 Browser Session ID，因此 Agent 應能延續對話。

---

## 12.6 New Session

點擊：

```text
🔄 New Session
```

會建立新的 UUID。

結果：

```text
短期 Session Context 不延續
長期 Semantic Memory 仍可能存在
```

---

# 13. Browser Session 與 Agent Memory 差異

| 功能 | 保存位置 | 作用 |
|---|---|---|
| Chat 畫面 | Browser DOM | 顯示目前頁面的訊息 |
| Browser Session ID | JavaScript | 指定 AgentCore Session |
| Flask Login Session | Flask Session | 保存 Access Token / Login 狀態 |
| Runtime Session | AgentCore Runtime | 保存同一段對話 Context |
| Semantic Memory | AgentCore Memory | 跨 Session 保存使用者事實 |

重新整理 Browser 可能會清掉畫面內容，但不一定會清掉 AgentCore Memory。

---

# 14. Login 與 Chat 的完整流程

```text
1. 使用者開啟 localhost:8501
2. Flask 發現尚未登入
3. Flask 顯示 login.html
4. 使用者點擊 Sign in with Cognito
5. Browser 前往 Cognito Hosted UI
6. 使用者輸入帳號密碼
7. Cognito 回傳 Authorization Code
8. Flask 使用 Code 交換 Access Token
9. Flask 保存登入狀態
10. Flask 顯示 index.html
11. Browser 建立 Session UUID
12. 使用者輸入訊息
13. Browser POST /chat
14. Flask 取得 Access Token
15. Flask 呼叫 AgentCore Runtime
16. Runtime 驗證 Cognito JWT
17. Agent 使用 Tool、Gateway 與 Memory
18. Runtime 回傳結果
19. Flask 回傳 JSON
20. Browser 顯示 Agent 回答
```

---

# 15. Logout 流程

點擊：

```text
Logout
```

Backend 應：

1. 清除 Flask Session
2. 清除 Access Token
3. 重新導向 Cognito Logout Endpoint
4. 再導回 Login Page

只清除 Flask Session、不呼叫 Cognito Logout，可能仍保留 Cognito Hosted UI 登入狀態。

---

# 16. 為什麼 Runtime 與 Gateway 都要允許 Web Client？

使用者登入後取得的 Token 來自：

```text
Cognito Web Client
```

流程：

```text
Web Client Token
→ Runtime
→ Gateway
```

如果 Runtime 允許 Web Client，但 Gateway 不允許：

```text
登入成功
Runtime 呼叫成功
Warranty Tool 失敗
```

如果 Gateway 允許，但 Runtime 不允許：

```text
登入後連 Runtime 都進不去
```

所以兩邊的 `allowedClients` 都要更新。

---

# 17. 安全注意事項

## 17.1 不要把 Client Secret 寫進 HTML

Browser 可查看前端原始碼。

以下內容不可放進 HTML：

- Cognito Client Secret
- AWS Secret Access Key
- AWS Session Token
- AgentCore Credential
- Flask Secret Key

---

## 17.2 Access Token 應保存在 Server Session

較安全的做法：

```text
Browser
→ Flask Session Cookie
→ Flask Server 保存 Access Token
```

不要直接把 Access Token長期放在：

```text
localStorage
```

---

## 17.3 Flask Secret Key

正式環境不要寫死：

```python
app.secret_key = "1234"
```

應從：

```text
Environment Variable
Secrets Manager
Parameter Store
```

取得。

---

## 17.4 本 Lab 的 Flask 是本機開發模式

```text
http://localhost:8501
```

只適合：

- Workshop
- Demo
- 開發測試

正式環境還需要：

- HTTPS
- 正式 WSGI Server
- Reverse Proxy
- CSRF 防護
- Secure Cookie
- Session Store
- Secret Management
- Rate Limiting
- Error Handling

---

# 18. 常見錯誤排查

## 18.1 `uv add` 失敗

檢查：

- 是否位於 `app/CustomerSupport`
- Python Virtual Environment
- 公司 Proxy / Package Registry
- `pyproject.toml` 是否可寫入

---

## 18.2 Cognito Login 後 Callback 失敗

檢查：

- Cognito Callback URL
- Flask Callback Route
- Cognito Domain
- Web Client 是否啟用 Authorization Code Flow
- Redirect URI 是否完全一致

例如：

```text
http://localhost:8501/callback
```

字串必須完全一致。

---

## 18.3 Runtime 回傳 Unauthorized

檢查：

- Access Token 是否過期
- Web Client ID 是否加入 Runtime `allowedClients`
- Runtime 是否已重新部署
- Authorization Header 是否正確
- 使用的是 Access Token，不是任意字串

---

## 18.4 Warranty Tool 回傳 Unauthorized

檢查：

- Web Client ID 是否加入 Gateway `allowedClients`
- JWT 是否從 Runtime 傳給 Gateway
- Secure Gateway URL 是否正確
- Gateway MCP Client 是否帶 Authorization Header

---

## 18.5 找不到 Runtime ARN

檢查：

```text
agentcore/.cli/deployed-state.json
```

可能原因：

- 尚未部署
- 執行目錄錯誤
- `frontend.py` 使用錯誤相對路徑
- Deployment Target 名稱不同

---

## 18.6 Port 8501 被占用

PowerShell 查詢：

```powershell
Get-NetTCPConnection `
  -LocalPort 8501 `
  -ErrorAction SilentlyContinue
```

可以改用其他 Port，例如：

```python
app.run(
    host="127.0.0.1",
    port=8502,
    debug=True,
)
```

同時 Cognito Callback URL 也要跟著更新。

---

## 18.7 Chat 顯示 `No response`

檢查：

- `/chat` 是否回傳 JSON
- Runtime Response Format
- Flask Log
- Browser DevTools Network
- `data.response`
- `data.error`

---

## 18.8 New Session 後仍記得使用者

這不一定是錯誤。

可能是：

```text
Session Context 已清除
但 Semantic Memory 仍保存使用者事實
```

要測試 Session Isolation，應問只存在於上一段即時對話、尚未成為長期 Memory 的資訊。

---

# 19. 完整操作順序

```text
Step 1
安裝 Flask、boto3、requests
    ↓
Step 2
取得 Cognito Web Client ID
    ↓
Step 3
更新 Runtime allowedClients
    ↓
Step 4
更新 Gateway allowedClients
    ↓
Step 5
Validate 與 Deploy
    ↓
Step 6
建立 frontend/ 目錄
    ↓
Step 7
建立 frontend.py
    ↓
Step 8
建立 login.html
    ↓
Step 9
建立 index.html
    ↓
Step 10
啟動 Flask
    ↓
Step 11
開啟 localhost:8501
    ↓
Step 12
使用 Cognito Hosted UI 登入
    ↓
Step 13
進入 Chat Interface
    ↓
Step 14
測試 Product Tool
    ↓
Step 15
測試 Return Policy Tool
    ↓
Step 16
測試 Warranty Gateway
    ↓
Step 17
測試 Memory
    ↓
Step 18
測試 New Session 與 Logout
```

---

# 20. 指令速查表

| 指令 | 用途 |
|---|---|
| `uv add flask boto3 requests` | 安裝 Frontend 依賴 |
| `aws ssm get-parameter` | 取得 Cognito Web Client ID |
| `agentcore validate` | 驗證 AgentCore 設定 |
| `agentcore deploy -y -v` | 更新 Runtime 與 Gateway |
| `uv run python frontend.py` | 啟動 Flask App |
| `http://localhost:8501` | 開啟本機 Chat Interface |

---

# 21. 最後檢查清單

- [ ] Lab 1～5 已完成
- [ ] Flask、boto3、requests 已安裝
- [ ] Web Client ID 已取得
- [ ] Runtime `allowedClients` 已更新
- [ ] Gateway `allowedClients` 已更新
- [ ] `agentcore validate` 成功
- [ ] `agentcore deploy` 成功
- [ ] `frontend/` 目錄已建立
- [ ] `frontend.py` 已保存
- [ ] `login.html` 已建立
- [ ] `index.html` 已建立
- [ ] Runtime ARN 可自動取得
- [ ] Cognito Login 可正常開啟
- [ ] Callback 可交換 Access Token
- [ ] Chat Interface 可開啟
- [ ] Product Query 成功
- [ ] Return Policy Query 成功
- [ ] Warranty Query 成功
- [ ] Memory Query 成功
- [ ] New Session 可建立新 UUID
- [ ] Logout 可清除登入狀態

---

# 22. Lab 1～6 完整成果

| Lab | 完成內容 |
|---|---|
| Lab 1 | Agent Prototype 與 Local Tools |
| Lab 2 | Persistent Memory |
| Lab 3 | AgentCore Gateway |
| Lab 4 | JWT、Session、Observability |
| Lab 5 | Continuous Quality Monitoring |
| Lab 6 | Cognito Web Chat Interface |

---

# 23. 一句話總結

本 Lab 的核心流程是：

```text
建立 Flask Web App
→ 透過 Cognito Hosted UI 登入
→ 使用 Authorization Code 取得 Access Token
→ Flask 帶 JWT 呼叫 AgentCore Runtime
→ Browser 顯示 Agent 回答
```

這一步把原本只能透過 CLI 呼叫的 Agent，變成一般使用者可透過瀏覽器操作的完整 Web 應用程式。
